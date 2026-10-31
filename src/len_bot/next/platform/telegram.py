"""Telegram Bot API adapter: getUpdates long polling in, Bot API methods out."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import httpx

from ..configuration.platforms import TelegramSettings
from ..runtime.logs import REDACTED
from .adapter import PlatformCallError, read_capped
from .messages import ChatMessage, Notice, Segment, Sender, SendResult, UploadResult


# A failed poll is retried; each attempt doubles the wait up to the maximum, a successful poll resets it.
RECONNECT_INITIAL_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0
# Joins and leaves arrive as service messages, so plain messages cover every event the adapter maps.
ALLOWED_UPDATES = ["message"]
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
DOCUMENT_LIMIT_BYTES = 50 * 1024 * 1024
# A rate-limited send is retried once when Telegram asks to wait at most this long.
RETRY_AFTER_LIMIT_SECONDS = 30
# Telegram keeps undelivered updates for a day. Messages older than this before the adapter started are
# acknowledged without delivery, as OneBot does not replay what arrived while the host was down.
BACKLOG_GRACE_SECONDS = 60
CONTENT_FIELDS = ("text", "caption", "photo", "sticker", "voice", "audio", "document", "video", "animation",
                  "video_note", "location", "venue", "contact", "poll", "dice")


class TelegramCallError(PlatformCallError):
    """A Bot API request that failed; ``retry_after`` is set when Telegram rate-limited it."""

    def __init__(self, message: str, *, submitted: bool, retry_after: int | None = None):
        super().__init__(message, submitted=submitted)
        self.retry_after = retry_after


def _transport(proxy: str | None) -> httpx.AsyncBaseTransport:
    return httpx.AsyncHTTPTransport(retries=0, trust_env=False, proxy=proxy)


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def chat_id(scene: str) -> int | None:
    platform, _, rest = scene.partition(":")
    kind, separator, target = rest.partition(":")
    if (platform != "telegram" or not separator or kind not in {"group", "private"}
            or re.fullmatch(r"-?[1-9][0-9]*", target) is None):
        return None
    return int(target)


def _name(user: dict) -> str:
    return " ".join(part for part in (user.get("first_name"), user.get("last_name")) if isinstance(part, str) and part)


def _text_segments(text: str, entities: list, *, bot: int, username: str | None) -> tuple[list[Segment], bool]:
    """Text split around mentions of known accounts; entity offsets count UTF-16 code units."""
    data = text.encode("utf-16-le")
    segments: list[Segment] = []
    mentioned, position = False, 0
    for entity in sorted((item for item in entities if item.get("type") in {"mention", "text_mention"}),
                         key=lambda item: item["offset"]):
        start, end = entity["offset"] * 2, (entity["offset"] + entity["length"]) * 2
        if start < position:
            continue
        if entity["type"] == "text_mention":
            user = entity["user"]["id"]
        elif username is not None and data[start:end].decode("utf-16-le").casefold() == "@" + username.casefold():
            user = bot
        else:
            # @username of another member: the Bot API does not resolve it to an account, so it stays text.
            continue
        if start > position:
            segments.append(Segment("text", {"text": data[position:start].decode("utf-16-le")}))
        segments.append(Segment("mention", {"user": f"telegram:{user}"}))
        mentioned |= user == bot
        position = end
    if position < len(data):
        segments.append(Segment("text", {"text": data[position:].decode("utf-16-le")}))
    return segments, mentioned


def _media_segments(message: dict) -> list[Segment]:
    if "photo" in message:
        largest = max(message["photo"], key=lambda size: size["width"] * size["height"])
        return [Segment("image", {"file_id": largest["file_id"], "file_unique_id": largest["file_unique_id"]})]
    if "sticker" in message:
        sticker = message["sticker"]
        data = {"file_id": sticker["file_id"], "file_unique_id": sticker["file_unique_id"]}
        if isinstance(sticker.get("emoji"), str):
            data["summary"] = sticker["emoji"]
        if sticker.get("is_animated") or sticker.get("is_video"):
            return [Segment("sticker", data)]
        return [Segment("image", {**data, "sub_type": 1})]
    if "voice" in message:
        voice = message["voice"]
        return [Segment("audio", {"file_id": voice["file_id"], "duration": voice.get("duration"),
                                  "mime_type": voice.get("mime_type")})]
    for field in ("document", "audio"):
        if field in message:
            item = message[field]
            name = item.get("file_name") or item.get("title") or field
            return [Segment("file", {"file_id": item["file_id"], "name": name, "size": item.get("file_size")})]
    for field in ("video", "animation", "video_note"):
        if field in message:
            return [Segment("video", {"file_id": message[field]["file_id"]})]
    if "poll" in message:
        return [Segment("poll", {"name": message["poll"].get("question")})]
    return [Segment(field, {}) for field in ("location", "venue", "contact", "dice") if field in message][:1]


def _notice(update: dict, message: dict, scene: str, moment: float, author: dict, bot: int) -> Notice | None:
    if "new_chat_members" in message and message["new_chat_members"]:
        # One notice per service message; it names the first member, raw keeps the full list.
        member = message["new_chat_members"][0]
        operator = author.get("id")
        return Notice(scene=scene, notice_type="group_increase",
                      sub_type="approve" if operator in (None, member["id"]) else "invite",
                      user_id=f"telegram:{member['id']}",
                      operator_id=None if operator in (None, member["id"]) else f"telegram:{operator}",
                      time=moment, raw=update, platform_message_id=None, duration=None)
    if "left_chat_member" in message:
        member, operator = message["left_chat_member"], author.get("id")
        sub_type = "kick_me" if member["id"] == bot else "leave" if operator in (None, member["id"]) else "kick"
        return Notice(scene=scene, notice_type="group_decrease", sub_type=sub_type,
                      user_id=f"telegram:{member['id']}",
                      operator_id=None if operator in (None, member["id"]) else f"telegram:{operator}",
                      time=moment, raw=update, platform_message_id=None, duration=None)
    return None


def parse_update(update: dict, *, bot: int, username: str | None) -> ChatMessage | Notice | None:
    """The message or join/leave notice of one update; None for chats and updates LenBot does not follow."""
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    try:
        chat = message["chat"]
        if chat["type"] in {"group", "supergroup"}:
            scene = f"telegram:group:{chat['id']}"
        elif chat["type"] == "private":
            scene = f"telegram:private:{chat['id']}"
        else:
            return None
        moment = float(message["date"])
        author = message.get("from") or {}
        notice = _notice(update, message, scene, moment, author, bot)
        if notice is not None:
            return notice
        if not any(field in message for field in CONTENT_FIELDS):
            return None
        origin = message.get("sender_chat")
        if isinstance(origin, dict):
            sender = Sender(uid=f"telegram:{origin['id']}", nickname=origin.get("title"), card=None, role=None)
        else:
            sender = Sender(uid=f"telegram:{author['id']}", nickname=_name(author) or author.get("username"),
                            card=None, role=None)
        segments: list[Segment] = []
        reply_to, mentioned = None, False
        replied = message.get("reply_to_message")
        # In a forum, a message outside any reply carries its topic's opening message as reply_to_message.
        if isinstance(replied, dict) and "forum_topic_created" not in replied:
            reply_to = str(replied["message_id"])
            segments.append(Segment("reply", {"id": reply_to}))
            mentioned |= (replied.get("from") or {}).get("id") == bot
        forwarded = message.get("forward_origin")
        if isinstance(forwarded, dict):
            source = (forwarded.get("sender_user") or forwarded.get("sender_chat") or forwarded.get("chat") or {})
            name = _name(source) or source.get("title") or forwarded.get("sender_user_name")
            segments.append(Segment("forward", {} if not name else {"name": name}))
        segments.extend(_media_segments(message))
        text = message.get("text", message.get("caption"))
        if isinstance(text, str) and text:
            entities = message.get("entities", message.get("caption_entities", []))
            words, addressed = _text_segments(text, entities, bot=bot, username=username)
            segments.extend(words)
            mentioned |= addressed
        return ChatMessage(
            id=str(uuid4()), platform="telegram", bot_id=f"telegram:{bot}", scene=scene,
            platform_message_id=str(message["message_id"]), sender=sender, time=moment, segments=segments,
            reply_to=reply_to, mentions_bot=mentioned, is_self=author.get("id") == bot, send_status="received",
        )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Telegram update parse failed: {type(error).__name__}: {error}; "
                         f"raw={json.dumps(update, ensure_ascii=False)[:500]}") from error


class Telegram:
    """The Telegram Bot API adapter; one bot, any number of groups and private chats."""

    name = "telegram"

    def __init__(self, settings: TelegramSettings, *, on_event: Callable[[dict], None],
                 on_error: Callable[[str], None], on_connection_change: Callable[[], None] | None = None):
        self.settings = settings
        self.bot = int(settings.bot_id.split(":", 1)[1])
        self.username: str | None = None
        self.on_event, self.on_error = on_event, on_error
        self.on_connection_change = on_connection_change
        self._running = False
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._poller: asyncio.Task | None = None
        self._changed = asyncio.Event()
        self._closing = asyncio.Event()
        self._since = 0.0
        # Usernames and display names seen in chats, so an outgoing mention can name the member.
        self._members: dict[str, tuple[str | None, str | None]] = {}
        # The forum topic each chat last spoke in; a send without a reply goes there.
        self._threads: dict[int, int] = {}

    def _safe(self, text: str) -> str:
        return text.replace(self.settings.bot_token, REDACTED)[:2000]

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def addresses(self) -> list[tuple]:
        return []

    def parse(self, raw: dict) -> ChatMessage | Notice | None:
        return parse_update(raw, bot=self.bot, username=self.username)

    async def start(self) -> None:
        if self._running:
            raise RuntimeError("Telegram transport is already started; close it before restarting")
        self._running = True
        self._closing.clear()
        self._changed.clear()
        try:
            self._client = httpx.AsyncClient(
                base_url=f"{self.settings.api_url}/bot{self.settings.bot_token}/",
                transport=_transport(self.settings.proxy), timeout=self.settings.request_timeout_seconds,
                follow_redirects=False)
            await self.identify()
        except asyncio.CancelledError:
            await self.close()
            raise
        except TelegramCallError:
            await self.close()
            raise
        except Exception as error:
            await self.close()
            raise TelegramCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=False) from None
        self._since = time.time()
        self._set_connected(True)
        self._poller = asyncio.create_task(self._poll())

    async def close(self) -> None:
        self._running = False
        self._closing.set()
        self._changed.set()
        try:
            if self._poller is not None and not self._poller.done():
                self._poller.cancel()
                await asyncio.gather(self._poller, return_exceptions=True)
        finally:
            self._set_connected(False)
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def wait_terminated(self) -> None:
        if self._poller is not None:
            await asyncio.wait({self._poller})

    async def wait_connected(self, timeout_seconds: float | None) -> None:
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    if not self._running:
                        raise TelegramCallError("Telegram transport is not running", submitted=False)
                    if self._connected:
                        return
                    self._changed.clear()
                    await self._changed.wait()
        except TimeoutError:
            raise TelegramCallError(f"Telegram connection did not arrive within {timeout_seconds}s",
                                    submitted=False) from None

    def _set_connected(self, connected: bool) -> None:
        if self._connected != connected:
            self._connected = connected
            self._changed.set()
            if self.on_connection_change is not None:
                self.on_connection_change()

    async def _stopped_within(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._closing.wait(), seconds)
        except TimeoutError:
            return False
        return True

    async def _poll(self) -> None:
        """Fetch updates until close(); a failed poll marks the bot disconnected until one succeeds again."""
        offset: int | None = None
        delay = RECONNECT_INITIAL_SECONDS
        while True:
            params: dict = {"timeout": self.settings.poll_timeout_seconds, "allowed_updates": ALLOWED_UPDATES}
            if offset is not None:
                params["offset"] = offset
            try:
                updates = await self._request(
                    "getUpdates", params,
                    timeout=self.settings.poll_timeout_seconds + self.settings.request_timeout_seconds)
                if not isinstance(updates, list) or not all(isinstance(item, dict) for item in updates):
                    raise TelegramCallError(f"getUpdates returned {repr(updates)[:300]}", submitted=False)
            except TelegramCallError as error:
                self._set_connected(False)
                self.on_error(f"Telegram getUpdates failed, next attempt in {delay:g}s: {error}")
                if await self._stopped_within(delay):
                    return
                delay = min(delay * 2, RECONNECT_MAX_SECONDS)
                continue
            delay = RECONNECT_INITIAL_SECONDS
            self._set_connected(True)
            for update in updates:
                try:
                    offset = int(update["update_id"]) + 1
                    message = update.get("message")
                    if isinstance(message, dict):
                        if float(message.get("date", 0)) < self._since - BACKLOG_GRACE_SECONDS:
                            continue
                        self._remember(message)
                    self.on_event(update)
                except Exception as error:
                    self.on_error(self._safe(f"{type(error).__name__}: {error}; "
                                             f"raw={json.dumps(update, ensure_ascii=False)[:1500]}"))

    def _remember(self, message: dict) -> None:
        for user in [message.get("from"), (message.get("reply_to_message") or {}).get("from"),
                     *message.get("new_chat_members", [])]:
            if isinstance(user, dict) and isinstance(user.get("id"), int):
                self._members[f"telegram:{user['id']}"] = (user.get("username"), _name(user) or None)
        if message.get("is_topic_message") and isinstance(message.get("message_thread_id"), int):
            self._threads[message["chat"]["id"]] = message["message_thread_id"]

    async def _post(self, method: str, params: dict, *, files: dict | None = None,
                    timeout: float | None = None) -> dict:
        """The decoded Bot API answer, including ok=false answers; raises only when no answer came back."""
        if not self._running or self._client is None:
            raise TelegramCallError("Telegram transport has not been started", submitted=False)
        try:
            if files is None:
                request = self._client.build_request("POST", method, json=params, timeout=timeout or httpx.USE_CLIENT_DEFAULT)
            else:
                fields = {key: value if isinstance(value, str) else json.dumps(value) for key, value in params.items()}
                request = self._client.build_request("POST", method, data=fields, files=files,
                                                     timeout=timeout or httpx.USE_CLIENT_DEFAULT)
        except Exception as error:
            raise TelegramCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=False) from None
        try:
            response = await self._client.send(request)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ProxyError) as error:
            raise TelegramCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=False) from None
        except httpx.HTTPError as error:
            raise TelegramCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=True) from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("ok"), bool):
            raise TelegramCallError(self._safe(f"Telegram {method} HTTP {response.status_code}: {response.text[:500]}"),
                                    submitted=True)
        return body

    async def _request(self, method: str, params: dict | None = None, *, files: dict | None = None,
                       timeout: float | None = None) -> object:
        body = await self._post(method, params or {}, files=files, timeout=timeout)
        if body["ok"]:
            return body.get("result")
        parameters = body.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        # An ok=false answer means Telegram did not carry out the method.
        raise TelegramCallError(self._safe(f"Telegram {method} {body.get('error_code')}: {body.get('description')}"),
                                submitted=False, retry_after=retry_after if type(retry_after) is int else None)

    async def _send(self, method: str, params: dict, *, files: dict | None = None) -> object:
        try:
            return await self._request(method, params, files=files)
        except TelegramCallError as error:
            if error.retry_after is None or error.retry_after > RETRY_AFTER_LIMIT_SECONDS:
                raise
            wait = error.retry_after
        await asyncio.sleep(wait)
        return await self._request(method, params, files=files)

    async def identify(self) -> str:
        me = await self._request("getMe")
        if not isinstance(me, dict) or me.get("id") != self.bot:
            raise TelegramCallError(f"getMe did not confirm the configured bot_id {self.settings.bot_id}: "
                                    f"{repr(me)[:300]}", submitted=False)
        self.username = me.get("username") if isinstance(me.get("username"), str) else None
        return self.settings.bot_id

    def _compose(self, segments: list[Segment]) -> tuple[str, list[dict]]:
        parts: list[str] = []
        entities: list[dict] = []
        length = 0
        for segment in segments:
            if segment.type == "text":
                piece = segment.data["text"]
            elif segment.type == "mention":
                user = segment.data["user"]
                username, name = self._members.get(user, (None, None))
                if user == "all":
                    piece = "@all"
                elif username:
                    piece = "@" + username
                else:
                    piece = name or user.split(":", 1)[1]
                    entities.append({"type": "text_mention", "offset": length, "length": _utf16_length(piece),
                                     "user": {"id": int(user.split(":", 1)[1]), "is_bot": False, "first_name": piece}})
            else:
                continue
            parts.append(piece)
            length += _utf16_length(piece)
        return "".join(parts), entities

    def _target(self, chat: int, reply: str | None) -> dict:
        if reply is not None and reply.isdecimal():
            return {"chat_id": chat, "reply_parameters": {"message_id": int(reply), "allow_sending_without_reply": True}}
        thread = self._threads.get(chat)
        return {"chat_id": chat, **({} if thread is None else {"message_thread_id": thread})}

    async def send_message(self, message: ChatMessage, *, image_bytes: bytes | None = None) -> SendResult:
        chat = chat_id(message.scene)
        if chat is None:
            return SendResult("failed", None, f"Invalid Telegram scene: {message.scene!r}")
        unsupported = [segment.type for segment in message.segments
                       if segment.type not in {"text", "mention", "reply", "image"}]
        if unsupported:
            return SendResult("failed", None, f"Unsupported Telegram message segments: {unsupported!r}")
        for segment in message.segments:
            if (segment.type == "mention" and segment.data["user"] != "all"
                    and re.fullmatch(r"telegram:[1-9][0-9]*", segment.data["user"]) is None):
                return SendResult("failed", None, f"Invalid Telegram mention: {segment.data['user']!r}")
        image_count = sum(segment.type == "image" for segment in message.segments)
        if image_count > 1:
            return SendResult("failed", None, "Telegram message supports only one image segment")
        if image_count and not image_bytes:
            return SendResult("failed", None, "Telegram image segment requires nonempty image bytes")
        if not image_count and image_bytes is not None:
            return SendResult("failed", None, "Telegram image bytes require an image segment")
        text, entities = self._compose(message.segments)
        limit = CAPTION_LIMIT if image_count else TEXT_LIMIT
        if _utf16_length(text) > limit:
            return SendResult("failed", None, f"Telegram {'caption' if image_count else 'text'} exceeds {limit} characters")
        if not image_count and not text.strip():
            return SendResult("failed", None, "Telegram text message is empty")
        reply = next((str(segment.data["id"]) for segment in message.segments if segment.type == "reply"),
                     message.reply_to)
        params = self._target(chat, reply)
        if image_count:
            method, files = "sendPhoto", {"photo": ("image", image_bytes)}
            params.update({"caption": text} if text else {})
            params.update({"caption_entities": entities} if entities else {})
        else:
            method, files = "sendMessage", None
            params.update(text=text, **({"entities": entities} if entities else {}))
        if not self._running or self._client is None:
            return SendResult("failed", None, "Telegram transport is not running; message was not sent")
        try:
            result = await self._send(method, params, files=files)
        except TelegramCallError as error:
            return SendResult("unconfirmed" if error.submitted else "failed", None, str(error))
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if type(message_id) is int:
            return SendResult("sent", str(message_id), None)
        return SendResult("unconfirmed", None, self._safe(repr(result)[:500]))

    async def upload_file(self, scene: str, file: str, name: str) -> UploadResult:
        """Send a file as a document; ``file`` is base64:// data or a local path."""
        chat = chat_id(scene)
        if chat is None:
            return UploadResult("failed", None, f"Invalid Telegram scene: {scene!r}", None)
        if not file or not name:
            return UploadResult("failed", None, "Telegram upload requires a file and name", None)
        try:
            data = (base64.b64decode(file.removeprefix("base64://"), validate=True) if file.startswith("base64://")
                    else await asyncio.to_thread(Path(file).read_bytes))
        except (ValueError, OSError) as error:
            return UploadResult("failed", None, f"{type(error).__name__}: {error}", None)
        if len(data) > DOCUMENT_LIMIT_BYTES:
            return UploadResult("failed", None, f"Telegram documents are limited to {DOCUMENT_LIMIT_BYTES} bytes", None)
        try:
            result = await self._send("sendDocument", self._target(chat, None), files={"document": (name, data)})
        except TelegramCallError as error:
            return UploadResult("unconfirmed" if error.submitted else "failed", None, str(error), None)
        document = result.get("document") if isinstance(result, dict) else None
        file_id = document.get("file_id") if isinstance(document, dict) else None
        if isinstance(file_id, str) and file_id:
            return UploadResult("uploaded", file_id, None, result)
        return UploadResult("unconfirmed", None, self._safe(repr(result)[:500]), None)

    async def scene_title(self, scene: str) -> tuple[str, int | None]:
        chat = chat_id(scene)
        if chat is None:
            raise TelegramCallError(f"Invalid Telegram scene: {scene!r}", submitted=False)
        info = await self._request("getChat", {"chat_id": chat})
        if not isinstance(info, dict):
            raise TelegramCallError(f"getChat returned {repr(info)[:300]}", submitted=False)
        if scene.startswith("telegram:group:"):
            count = await self._request("getChatMemberCount", {"chat_id": chat})
            return info.get("title") or str(chat), count if type(count) is int else None
        return _name(info) or info.get("username") or str(chat), None

    async def call(self, action: str, params: dict) -> dict:
        """One Bot API method with Telegram's answer as sent, ok=false included."""
        return await self._post(action, params)

    async def download(self, data: dict, max_bytes: int) -> bytes:
        """An inbound file by its file_id; the Bot API serves files up to 20 MB."""
        file_id = data.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            raise ValueError(f"segment has no Telegram file_id: {repr(data)[:200]}")
        info = await self._request("getFile", {"file_id": file_id})
        path = info.get("file_path") if isinstance(info, dict) else None
        if not isinstance(path, str) or not path:
            raise TelegramCallError(f"getFile returned no file_path: {repr(info)[:300]}", submitted=False)
        if type(info.get("file_size")) is int and info["file_size"] > max_bytes:
            raise ValueError(f"Telegram file is {info['file_size']} bytes, above {max_bytes}")
        try:
            async with self._client.stream("GET", f"{self.settings.api_url}/file/bot{self.settings.bot_token}/{path}") as response:
                if response.status_code != 200:
                    raise TelegramCallError(f"Telegram file download HTTP {response.status_code}", submitted=False)
                return await read_capped(response.aiter_bytes(), max_bytes)
        except httpx.HTTPError as error:
            raise TelegramCallError(self._safe(f"Telegram file download: {type(error).__name__}: {error}"),
                                    submitted=False) from None
