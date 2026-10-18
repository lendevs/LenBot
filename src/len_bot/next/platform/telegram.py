"""The Telegram adapter: Bot API long polling for input, Bot API methods for output.

Scenes are ``telegram:private:<chat id>`` and ``telegram:group:<chat id>`` (groups and supergroups,
whose ids are negative); accounts are ``telegram:<user id>``. Only text, replies, mentions and one
image per message are sent; other media arrive as a short placeholder in the text.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from uuid import uuid4

import httpx

from ..configuration.telegram import TelegramSettings
from ..runtime.logs import REDACTED
from .adapter import PlatformCallError
from .messages import ChatMessage, Notice, Segment, Sender, SendResult, UploadResult

RETRY_INITIAL_SECONDS = 1.0
RETRY_MAX_SECONDS = 30.0
NAMES_KEPT = 4096
PLACEHOLDERS = {"photo": "[图片]", "sticker": "[表情]", "voice": "[语音]", "audio": "[音频]", "video": "[视频]",
                "document": "[文件]", "animation": "[动图]", "location": "[位置]", "contact": "[联系人]"}


# getUpdates answers that retrying cannot fix: a revoked token, or a webhook or another poller on this bot.
TERMINAL_POLL_ERRORS = {401, 409}


class TelegramError(PlatformCallError):
    """A Bot API answer with ``ok: false``; ``error_code`` is Telegram's (the HTTP status)."""

    def __init__(self, message: str, *, submitted: bool, error_code: int):
        super().__init__(message, submitted=submitted)
        self.error_code = error_code


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class Telegram:
    name = "telegram"

    def __init__(self, settings: TelegramSettings, *, bot_id: str, on_event: Callable[[dict], None],
                 on_error: Callable[[str], None], on_connection_change: Callable[[], None] | None = None):
        self.settings, self.bot_id = settings, bot_id
        self.account = bot_id.split(":", 1)[1]
        self.on_event, self.on_error, self.on_connection_change = on_event, on_error, on_connection_change
        self.username: str | None = None
        # Display names of accounts seen in received messages, newest last; a sent mention shows the name.
        self.names: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None
        self._poller: asyncio.Task | None = None
        self._connected = False
        self._connection_changed = asyncio.Event()
        self._terminated = asyncio.Event()
        self._offset: int | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def addresses(self) -> list[tuple]:
        return []

    def _safe(self, text: str) -> str:
        return text.replace(self.settings.bot_token, REDACTED)[:2000]

    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            self._connection_changed.set()
            self._connection_changed = asyncio.Event()
            if self.on_connection_change is not None:
                self.on_connection_change()

    async def call(self, action: str, params: dict, *, files: dict | None = None,
                   timeout: float | None = None) -> dict:
        """One Bot API method; returns its ``result``. ``submitted`` is False only when nothing was sent."""
        if self._client is None:
            raise PlatformCallError("Telegram 适配器没有启动", submitted=False)
        url = f"{self.settings.api_base}/bot{self.settings.bot_token}/{action}"
        try:
            if files:
                response = await self._client.post(url, data={key: str(value) for key, value in params.items()},
                                                   files=files, timeout=timeout)
            else:
                response = await self._client.post(url, json=params, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise PlatformCallError(self._safe(f"Telegram {action} 连接失败：{type(error).__name__}: {error}"),
                                    submitted=False) from None
        except httpx.HTTPError as error:
            raise PlatformCallError(self._safe(f"Telegram {action} 没有确认：{type(error).__name__}: {error}"),
                                    submitted=True) from None
        try:
            body = response.json()
        except ValueError:
            raise PlatformCallError(self._safe(f"Telegram {action} HTTP {response.status_code}: {response.text[:300]}"),
                                    submitted=True) from None
        if not isinstance(body, dict) or body.get("ok") is not True:
            description = body.get("description") if isinstance(body, dict) else body
            # A refused request (bad chat, no rights) was not delivered.
            raise TelegramError(self._safe(f"Telegram {action} 失败：{description}"),
                                submitted=response.status_code >= 500, error_code=response.status_code)
        return body["result"]

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)
        try:
            me = await self.call("getMe", {})
            if str(me.get("id")) != self.account:
                raise ValueError(f"Telegram bot token belongs to {me.get('id')}, not configured bot_id {self.bot_id}")
        except BaseException:
            await self._client.aclose()
            self._client = None
            raise
        self.username = me.get("username")
        # Connected only once getUpdates answers: getMe also succeeds while a webhook or another poller
        # holds the updates, and the updater and the ready check read this flag.
        self._poller = asyncio.create_task(self._poll(), name="telegram-poll")

    async def _poll(self) -> None:
        delay = RETRY_INITIAL_SECONDS
        timeout = self.settings.poll_timeout_seconds
        while True:
            params = {"timeout": timeout, "allowed_updates": ["message"]}
            if self._offset is not None:
                params["offset"] = self._offset
            try:
                updates = await self.call("getUpdates", params, timeout=timeout + self.settings.request_timeout_seconds)
            except PlatformCallError as error:
                self._set_connected(False)
                if isinstance(error, TelegramError) and error.error_code in TERMINAL_POLL_ERRORS:
                    self.on_error(f"{error}；不再重试，处理后重启")
                    self._terminated.set()
                    return
                self.on_error(str(error))
                await asyncio.sleep(delay)
                delay = min(delay * 2, RETRY_MAX_SECONDS)
                continue
            delay = RETRY_INITIAL_SECONDS
            self._set_connected(True)
            for update in updates:
                self._offset = update["update_id"] + 1
                self.on_event(update)

    async def close(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            await asyncio.gather(self._poller, return_exceptions=True)
            self._poller = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._set_connected(False)
        self._terminated.set()

    async def wait_connected(self, timeout_seconds: float | None) -> None:
        async with asyncio.timeout(timeout_seconds):
            while not self._connected:
                await self._connection_changed.wait()

    async def wait_terminated(self) -> None:
        await self._terminated.wait()

    async def identify(self) -> str:
        me = await self.call("getMe", {})
        return "telegram:" + str(me["id"])

    def parse(self, raw: dict) -> ChatMessage | Notice | None:
        message = raw.get("message")
        if not isinstance(message, dict) or "from" not in message:
            return None
        chat, sender = message["chat"], message["from"]
        if chat["type"] == "private":
            scene = f"telegram:private:{chat['id']}"
        elif chat["type"] in {"group", "supergroup"}:
            scene = f"telegram:group:{chat['id']}"
        else:
            return None
        segments: list[Segment] = []
        mentions_bot = False
        reply = message.get("reply_to_message")
        reply_to = None
        if isinstance(reply, dict):
            reply_to = str(reply["message_id"])
            segments.append(Segment("reply", {"id": reply_to}))
            mentions_bot = str(reply.get("from", {}).get("id")) == self.account
        text = message.get("text", message.get("caption", ""))
        entities = message.get("entities", message.get("caption_entities", []))
        units = text.encode("utf-16-le")
        cursor, pending = 0, ""
        for entity in sorted(entities, key=lambda item: item["offset"]):
            start, end = entity["offset"] * 2, (entity["offset"] + entity["length"]) * 2
            word = units[start:end].decode("utf-16-le")
            if entity["type"] == "bot_command" and "@" in word:
                # ``/status@OurBot`` (menus and groups with several bots) is our ``/status`` and addresses us;
                # a command for another bot stays as typed.
                name, _, target = word.partition("@")
                if self.username and target.lower() == self.username.lower():
                    pending += units[cursor:start].decode("utf-16-le") + name
                    mentions_bot, cursor = True, end
                continue
            user = None
            if entity["type"] == "mention" and self.username and word.lower() == "@" + self.username.lower():
                user = self.bot_id
            elif entity["type"] == "text_mention" and "user" in entity:
                user = "telegram:" + str(entity["user"]["id"])
                self._remember(user, entity["user"])
            if user is None:
                continue
            before = pending + units[cursor:start].decode("utf-16-le")
            if before:
                segments.append(Segment("text", {"text": before}))
            segments.append(Segment("mention", {"user": user}))
            mentions_bot = mentions_bot or user == self.bot_id
            cursor, pending = end, ""
        rest = pending + units[cursor:].decode("utf-16-le")
        media = next((label for key, label in PLACEHOLDERS.items() if key in message), None)
        if media is not None:
            rest = media + (" " + rest if rest else "")
        if rest:
            segments.append(Segment("text", {"text": rest}))
        name = self._remember("telegram:" + str(sender["id"]), sender)
        return ChatMessage(
            id=str(uuid4()), platform="telegram", bot_id=self.bot_id, scene=scene,
            platform_message_id=str(message["message_id"]),
            sender=Sender(uid="telegram:" + str(sender["id"]), nickname=name, card=None, role=None),
            time=float(message["date"]), segments=segments, reply_to=reply_to, mentions_bot=mentions_bot,
            is_self=str(sender["id"]) == self.account, send_status="received")

    def _remember(self, account: str, user: dict) -> str | None:
        name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part) or None
        if name is not None:
            self.names.pop(account, None)
            self.names[account] = name
            if len(self.names) > NAMES_KEPT:
                del self.names[next(iter(self.names))]
        return name

    async def send_message(self, message: ChatMessage, *, image_bytes: bytes | None = None) -> SendResult:
        platform, _, destination = message.scene.partition(":")
        kind, _, chat = destination.partition(":")
        if platform != "telegram" or kind not in {"group", "private"} or not chat.lstrip("-").isdecimal():
            return SendResult("failed", None, f"Invalid Telegram scene: {message.scene!r}")
        unsupported = [segment.type for segment in message.segments
                       if segment.type not in {"text", "mention", "reply", "image"}]
        if unsupported:
            return SendResult("failed", None, f"Unsupported Telegram message segments: {unsupported!r}")
        images = sum(segment.type == "image" for segment in message.segments)
        if images > 1 or bool(images) != (image_bytes is not None):
            return SendResult("failed", None, "Telegram message needs exactly one image segment with its bytes")
        text, entities, reply = "", [], None
        for segment in message.segments:
            if segment.type == "text":
                text += segment.data["text"]
            elif segment.type == "reply":
                reply = segment.data["id"]
            elif segment.type == "mention":
                user = segment.data["user"]
                if user == "all" or not user.startswith("telegram:"):
                    return SendResult("failed", None, f"Invalid Telegram mention: {user!r}")
                label = "@" + self.names.get(user, user.split(":", 1)[1])
                entities.append({"type": "text_mention", "offset": _utf16(text), "length": _utf16(label),
                                 "user": {"id": int(user.split(":", 1)[1])}})
                text += label
        params: dict = {"chat_id": int(chat)}
        if reply is not None and str(reply).isdecimal():
            params["reply_parameters"] = {"message_id": int(reply), "allow_sending_without_reply": True}
        try:
            if image_bytes is not None:
                if text:
                    params["caption"] = text
                    if entities:
                        params["caption_entities"] = json.dumps(entities)
                if "reply_parameters" in params:
                    params["reply_parameters"] = json.dumps(params["reply_parameters"])
                result = await self.call("sendPhoto", params, files={"photo": ("image", image_bytes)})
            else:
                if not text.strip():
                    return SendResult("failed", None, "Telegram message has no text")
                result = await self.call("sendMessage", {**params, "text": text,
                                                         **({"entities": entities} if entities else {})})
        except PlatformCallError as error:
            return SendResult("unconfirmed" if error.submitted else "failed", None, str(error))
        return SendResult("sent", str(result["message_id"]), None)

    async def scene_title(self, scene: str) -> tuple[str, int | None]:
        """``getChat`` (and ``getChatMemberCount`` for groups); the Bot API has no OneBot group actions."""
        platform, kind, chat = scene.split(":", 2)
        if platform != "telegram" or kind not in {"group", "private"}:
            raise ValueError(f"Invalid Telegram scene: {scene!r}")
        found = await self.call("getChat", {"chat_id": int(chat)})
        if kind == "group":
            title = found.get("title")
            if not isinstance(title, str) or not title:
                raise ValueError(f"Telegram getChat 没有群名：{json.dumps(found, ensure_ascii=False)[:300]}")
            members = await self.call("getChatMemberCount", {"chat_id": int(chat)})
            if type(members) is not int or members < 0:
                raise ValueError(f"Telegram getChatMemberCount 不是人数：{members!r}")
            return title, members
        name = " ".join(part for part in (found.get("first_name"), found.get("last_name")) if part)
        if not name:
            raise ValueError(f"Telegram getChat 没有名字：{json.dumps(found, ensure_ascii=False)[:300]}")
        return name, None

    async def upload_file(self, scene: str, file: str, name: str) -> UploadResult:
        return UploadResult("failed", None, "Telegram 适配器暂不支持上传文件", None)
