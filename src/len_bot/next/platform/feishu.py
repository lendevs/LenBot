"""Feishu (Lark) bot adapter: events over the long connection, messages through the Open API."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ..configuration.platforms import FEISHU_DOMAINS, FeishuSettings
from ..runtime.logs import REDACTED
from .adapter import PlatformCallError, read_capped
from .messages import ChatMessage, Notice, Segment, Sender, SendResult, UploadResult


RECONNECT_INITIAL_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0
PING_INTERVAL_SECONDS = 120
# Tenant tokens last two hours; one is replaced when less than this is left.
TOKEN_MARGIN_SECONDS = 300
# Member names of a chat are listed again at most this often when an unknown sender speaks.
MEMBER_LIST_SECONDS = 600
# The long connection may deliver an event again; this many recent event IDs are remembered.
SEEN_EVENTS = 1024
# Payloads split over several frames wait for their remaining parts; at most this many are held.
PENDING_PARTS = 64
FILE_LIMIT_BYTES = 30 * 1024 * 1024
FEISHU_ERROR_TOKEN = {99991661, 99991663, 99991668}
FEISHU_ERROR_RATE = 99991400


class FeishuCallError(PlatformCallError):
    """An Open API or long-connection request that failed."""


def _transport() -> httpx.AsyncBaseTransport:
    return httpx.AsyncHTTPTransport(retries=0, trust_env=False)


def _connect(url: str) -> object:
    return connect(url, proxy=None, open_timeout=15, close_timeout=5, max_size=16 * 1024 * 1024)


# The long connection exchanges protobuf frames (pbbp2.Frame); only varint and length-delimited fields occur.
def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return result, position


def _fields(data: bytes):
    position = 0
    while position < len(data):
        key, position = _read_varint(data, position)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, position = _read_varint(data, position)
        elif wire == 2:
            length, position = _read_varint(data, position)
            value, position = data[position:position + length], position + length
        else:
            raise ValueError(f"unexpected protobuf wire type {wire}")
        yield number, value


def encode_frame(frame: dict) -> bytes:
    out = bytearray()
    for number, name in ((1, "seq_id"), (2, "log_id"), (3, "service"), (4, "method")):
        out += _varint(number << 3) + _varint(frame.get(name, 0))
    for key, value in frame.get("headers", {}).items():
        header = (_varint(1 << 3 | 2) + _varint(len(key.encode())) + key.encode()
                  + _varint(2 << 3 | 2) + _varint(len(value.encode())) + value.encode())
        out += _varint(5 << 3 | 2) + _varint(len(header)) + header
    if frame.get("payload") is not None:
        out += _varint(8 << 3 | 2) + _varint(len(frame["payload"])) + frame["payload"]
    return bytes(out)


def decode_frame(data: bytes) -> dict:
    frame: dict = {"headers": {}, "payload": b""}
    for number, value in _fields(data):
        if number in (1, 2, 3, 4):
            frame[{1: "seq_id", 2: "log_id", 3: "service", 4: "method"}[number]] = value
        elif number == 5:
            header = dict(_fields(value))
            frame["headers"][header[1].decode()] = header[2].decode()
        elif number == 8:
            frame["payload"] = value
    return frame


def chat_target(scene: str) -> tuple[str, str] | None:
    """The receive_id_type and receive_id of a scene: chat_id for groups, open_id for private chats."""
    platform, _, rest = scene.partition(":")
    kind, separator, target = rest.partition(":")
    if platform != "feishu" or not separator:
        return None
    if kind == "group" and re.fullmatch(r"oc_[A-Za-z0-9]+", target):
        return "chat_id", target
    if kind == "private" and re.fullmatch(r"ou_[A-Za-z0-9]+", target):
        return "open_id", target
    return None


def _text_segments(text: str, mentions: dict[str, str], bot: str) -> tuple[list[Segment], bool]:
    """Text with @_user_N placeholders replaced by mention segments."""
    segments: list[Segment] = []
    mentioned, position = False, 0
    for match in re.finditer(r"@_user_\d+|@_all", text):
        user = "all" if match.group() == "@_all" else mentions.get(match.group())
        if user is None:
            continue
        if match.start() > position:
            segments.append(Segment("text", {"text": text[position:match.start()]}))
        segments.append(Segment("mention", {"user": user if user == "all" else "feishu:" + user}))
        mentioned |= user == bot
        position = match.end()
    if position < len(text):
        segments.append(Segment("text", {"text": text[position:]}))
    return segments, mentioned


def _post_segments(content: dict, mentions: dict[str, str], bot: str, message_id: str) -> tuple[list[Segment], bool]:
    segments: list[Segment] = []
    mentioned = False
    if isinstance(content.get("title"), str) and content["title"]:
        segments.append(Segment("text", {"text": content["title"] + "\n"}))
    for line_number, line in enumerate(content.get("content") or []):
        if line_number:
            segments.append(Segment("text", {"text": "\n"}))
        for item in line:
            tag = item.get("tag")
            if tag in {"text", "a", "code_block"}:
                segments.append(Segment("text", {"text": item.get("text", "")}))
            elif tag == "at":
                user = item.get("user_id")
                user = mentions.get(user, user)
                if user in {"all", "@_all"}:
                    segments.append(Segment("mention", {"user": "all"}))
                elif isinstance(user, str) and user.startswith("ou_"):
                    segments.append(Segment("mention", {"user": "feishu:" + user}))
                    mentioned |= user == bot
            elif tag == "img":
                segments.append(Segment("image", {"image_key": item["image_key"], "message_id": message_id}))
            elif tag == "emotion":
                segments.append(Segment("text", {"text": f"[{item.get('emoji_type')}]"}))
    return segments, mentioned


def _content_segments(kind: str, content: dict, mentions: dict[str, str], bot: str,
                      message_id: str) -> tuple[list[Segment], bool]:
    if kind == "text":
        return _text_segments(content.get("text", ""), mentions, bot)
    if kind == "post":
        return _post_segments(content, mentions, bot, message_id)
    if kind == "image":
        return [Segment("image", {"image_key": content["image_key"], "message_id": message_id})], False
    if kind == "audio":
        return [Segment("audio", {"file_key": content["file_key"], "message_id": message_id,
                                  "duration": content.get("duration")})], False
    if kind == "file":
        return [Segment("file", {"file_key": content["file_key"], "message_id": message_id,
                                 "name": content.get("file_name")})], False
    if kind == "media":
        return [Segment("video", {"file_key": content["file_key"], "message_id": message_id,
                                  "name": content.get("file_name")})], False
    if kind == "merge_forward":
        return [Segment("forward", {"id": message_id})], False
    return [Segment(kind, {})], False


def parse_event(raw: dict, *, bot: str, names: dict[str, str], scenes: dict[str, str]) -> ChatMessage | Notice | None:
    """The message or notice of one event callback; ``bot`` is the bot's open_id."""
    try:
        header, event = raw["header"], raw["event"]
        kind = header["event_type"]
        if kind == "im.message.receive_v1":
            message, sender = event["message"], event["sender"]
            author = sender["sender_id"]["open_id"]
            scene = (f"feishu:private:{author}" if message["chat_type"] == "p2p"
                     else f"feishu:group:{message['chat_id']}")
            mentions = {item["key"]: item["id"]["open_id"] for item in message.get("mentions") or []
                        if isinstance(item.get("id"), dict) and item["id"].get("open_id")}
            content = json.loads(message["content"])
            segments, mentioned = _content_segments(message["message_type"], content, mentions, bot,
                                                    message["message_id"])
            reply_to = message.get("parent_id") or None
            if reply_to is not None:
                segments.insert(0, Segment("reply", {"id": reply_to}))
            return ChatMessage(
                id=str(uuid4()), platform="feishu", bot_id="feishu:" + bot, scene=scene,
                platform_message_id=message["message_id"],
                sender=Sender(uid="feishu:" + author, nickname=names.get(author), card=None, role=None),
                time=int(message["create_time"]) / 1000, segments=segments, reply_to=reply_to,
                mentions_bot=mentioned, is_self=author == bot, send_status="received",
            )
        if kind == "im.message.recalled_v1":
            scene = scenes.get(event["chat_id"], f"feishu:group:{event['chat_id']}")
            return Notice(scene=scene, notice_type="group_recall" if ":group:" in scene else "friend_recall",
                          sub_type=None, user_id=None, operator_id=None, time=int(event["recall_time"]) / 1000,
                          raw=raw, platform_message_id=event["message_id"], duration=None)
        if kind in {"im.chat.member.user.added_v1", "im.chat.member.user.deleted_v1"}:
            users = event.get("users") or []
            if not users:
                return None
            # One notice per event; it names the first member, raw keeps the full list.
            user = users[0]["user_id"]["open_id"]
            operator = (event.get("operator_id") or {}).get("open_id")
            added = kind.endswith("added_v1")
            sub_type = ("approve" if operator in (None, user) else "invite") if added else (
                "leave" if operator in (None, user) else "kick")
            return Notice(scene=f"feishu:group:{event['chat_id']}",
                          notice_type="group_increase" if added else "group_decrease", sub_type=sub_type,
                          user_id="feishu:" + user,
                          operator_id=None if operator in (None, user) else "feishu:" + operator,
                          time=int(header["create_time"]) / 1000, raw=raw, platform_message_id=None, duration=None)
        return None
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise ValueError(f"Feishu event parse failed: {type(error).__name__}: {error}; "
                         f"raw={json.dumps(raw, ensure_ascii=False)[:500]}") from error


class Feishu:
    """The Feishu bot of one self-built app."""

    name = "feishu"

    def __init__(self, settings: FeishuSettings, *, on_event: Callable[[dict], None],
                 on_error: Callable[[str], None], on_connection_change: Callable[[], None] | None = None):
        self.settings = settings
        self.bot = settings.bot_id.split(":", 1)[1]
        self.on_event, self.on_error = on_event, on_error
        self.on_connection_change = on_connection_change
        self._running = False
        self._client: httpx.AsyncClient | None = None
        self._ws: ClientConnection | None = None
        self._receiver: asyncio.Task | None = None
        self._changed = asyncio.Event()
        self._closing = asyncio.Event()
        self._token: tuple[str, float] | None = None
        self._token_lock = asyncio.Lock()
        self._service = 0
        self._ping_seconds = PING_INTERVAL_SECONDS
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._parts: dict[str, list[bytes | None]] = {}
        # Display names by open_id, from mentions and member lists; private chats by chat_id for recalls.
        self.names: dict[str, str] = {}
        self.scenes: dict[str, str] = {}
        self._listed: dict[str, float] = {}
        self._list_failed: set[str] = set()

    def _safe(self, text: str) -> str:
        text = text.replace(self.settings.app_secret, REDACTED)
        if self._token is not None:
            text = text.replace(self._token[0], REDACTED)
        return text[:2000]

    @property
    def connected(self) -> bool:
        return self._ws is not None

    @property
    def addresses(self) -> list[tuple]:
        return []

    def parse(self, raw: dict) -> ChatMessage | Notice | None:
        return parse_event(raw, bot=self.bot, names=self.names, scenes=self.scenes)

    async def start(self) -> None:
        if self._running:
            raise RuntimeError("Feishu transport is already started; close it before restarting")
        self._running = True
        self._closing.clear()
        self._changed.clear()
        try:
            self._client = httpx.AsyncClient(base_url=self.settings.base_url, transport=_transport(),
                                             timeout=self.settings.request_timeout_seconds, follow_redirects=False)
            await self.identify()
            websocket = await self._dial()
        except asyncio.CancelledError:
            await self.close()
            raise
        except FeishuCallError:
            await self.close()
            raise
        except Exception as error:
            await self.close()
            raise FeishuCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=False) from None
        self._attach(websocket)
        self._receiver = asyncio.create_task(self._run(websocket))

    async def close(self) -> None:
        self._running = False
        self._closing.set()
        self._changed.set()
        try:
            if self._ws is not None:
                await self._ws.close()
            if self._receiver is not None and not self._receiver.done():
                self._receiver.cancel()
                await asyncio.gather(self._receiver, return_exceptions=True)
        finally:
            self._detach()
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def wait_terminated(self) -> None:
        if self._receiver is not None:
            await asyncio.wait({self._receiver})

    async def wait_connected(self, timeout_seconds: float | None) -> None:
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    if not self._running:
                        raise FeishuCallError("Feishu transport is not running", submitted=False)
                    if self.connected:
                        return
                    self._changed.clear()
                    await self._changed.wait()
        except TimeoutError:
            raise FeishuCallError(f"Feishu connection did not arrive within {timeout_seconds}s", submitted=False) from None

    def _attach(self, websocket: ClientConnection) -> None:
        self._ws = websocket
        self._changed.set()
        if self.on_connection_change is not None:
            self.on_connection_change()

    def _detach(self) -> None:
        if self._ws is not None:
            self._ws = None
            self._changed.set()
            if self.on_connection_change is not None:
                self.on_connection_change()

    async def _stopped_within(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._closing.wait(), seconds)
        except TimeoutError:
            return False
        return True

    async def _dial(self) -> ClientConnection:
        """Ask for a long-connection endpoint with the app credentials and open it."""
        if self._client is None:
            raise FeishuCallError("Feishu transport has not been started", submitted=False)
        try:
            response = await self._client.post("/callback/ws/endpoint", headers={"locale": "zh"},
                                               json={"AppID": self.settings.app_id, "AppSecret": self.settings.app_secret})
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise FeishuCallError(self._safe(f"long-connection endpoint: {type(error).__name__}: {error}"),
                                  submitted=False) from None
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or body.get("code") != 0 or not isinstance(data.get("URL"), str):
            raise FeishuCallError(self._safe(f"long-connection endpoint refused: {repr(body)[:300]}"), submitted=False)
        config = data.get("ClientConfig") or {}
        if type(config.get("PingInterval")) is int and config["PingInterval"] > 0:
            self._ping_seconds = config["PingInterval"]
        query = parse_qs(urlsplit(data["URL"]).query)
        self._service = int(query.get("service_id", ["0"])[0])
        try:
            return await _connect(data["URL"])
        except InvalidStatus as error:
            headers = error.response.headers
            raise FeishuCallError(self._safe(f"long connection refused: {headers.get('handshake-status')} "
                                             f"{headers.get('handshake-msg')}"), submitted=False) from None
        except Exception as error:
            raise FeishuCallError(self._safe(f"long connection: {type(error).__name__}: {error}"), submitted=False) from None

    async def _run(self, websocket: ClientConnection) -> None:
        """Own the long connection until close(); a dropped one is dialed again with backoff."""
        delay = RECONNECT_INITIAL_SECONDS
        while True:
            pinger = asyncio.create_task(self._ping(websocket))
            try:
                await self._consume(websocket)
            finally:
                pinger.cancel()
                await asyncio.gather(pinger, return_exceptions=True)
                self._detach()
            while True:
                if not self._running or await self._stopped_within(delay):
                    return
                delay = min(delay * 2, RECONNECT_MAX_SECONDS)
                try:
                    websocket = await self._dial()
                except FeishuCallError as error:
                    self.on_error(f"Feishu reconnect failed, next attempt in {delay:g}s: {error}")
                    continue
                if not self._running:
                    await websocket.close()
                    return
                self._attach(websocket)
                delay = RECONNECT_INITIAL_SECONDS
                break

    async def _ping(self, websocket: ClientConnection) -> None:
        while True:
            await websocket.send(encode_frame({"service": self._service, "method": 0, "headers": {"type": "ping"}}))
            await asyncio.sleep(self._ping_seconds)

    async def _consume(self, websocket: ClientConnection) -> None:
        while True:
            try:
                data = await websocket.recv()
            except ConnectionClosed as error:
                if self._running:
                    self.on_error(self._safe(f"Feishu long connection closed: {error}"))
                return
            try:
                frame = decode_frame(data if isinstance(data, bytes) else data.encode())
                if frame.get("method") == 0:
                    if frame["headers"].get("type") == "pong" and frame["payload"]:
                        config = json.loads(frame["payload"])
                        if type(config.get("PingInterval")) is int and config["PingInterval"] > 0:
                            self._ping_seconds = config["PingInterval"]
                    continue
                await self._data(websocket, frame)
            except Exception as error:
                self.on_error(self._safe(f"Feishu frame: {type(error).__name__}: {error}"))

    async def _data(self, websocket: ClientConnection, frame: dict) -> None:
        headers = frame["headers"]
        payload = frame["payload"]
        total = int(headers.get("sum", "1"))
        if total > 1:
            while len(self._parts) >= PENDING_PARTS and headers["message_id"] not in self._parts:
                self._parts.pop(next(iter(self._parts)))
            parts = self._parts.setdefault(headers["message_id"], [None] * total)
            parts[int(headers["seq"])] = payload
            if any(part is None for part in parts):
                return
            payload = b"".join(self._parts.pop(headers["message_id"]))
        # Feishu sends an event again unless it is answered within three seconds, so it is answered first.
        answer = dict(frame, headers={**headers, "biz_rt": "0"}, payload=json.dumps({"code": 200}).encode())
        await websocket.send(encode_frame(answer))
        if headers.get("type") != "event":
            return
        raw = json.loads(payload)
        event_id = (raw.get("header") or {}).get("event_id")
        if event_id in self._seen:
            return
        if event_id is not None:
            self._seen[event_id] = None
            while len(self._seen) > SEEN_EVENTS:
                self._seen.popitem(last=False)
        await self._learn(raw)
        try:
            self.on_event(raw)
        except Exception as error:
            self.on_error(self._safe(f"{type(error).__name__}: {error}; raw={json.dumps(raw, ensure_ascii=False)[:1500]}"))

    async def _learn(self, raw: dict) -> None:
        """Record names and private chats an event reveals, listing a chat's members for an unknown sender."""
        event = raw.get("event") or {}
        message = event.get("message")
        for user in event.get("users") or []:
            if isinstance(user.get("name"), str):
                self.names[user["user_id"]["open_id"]] = user["name"]
        if not isinstance(message, dict):
            return
        for item in message.get("mentions") or []:
            if isinstance(item.get("name"), str) and isinstance(item.get("id"), dict) and item["id"].get("open_id"):
                self.names[item["id"]["open_id"]] = item["name"]
        author = ((event.get("sender") or {}).get("sender_id") or {}).get("open_id")
        chat = message.get("chat_id")
        if message.get("chat_type") == "p2p" and author:
            self.scenes[chat] = f"feishu:private:{author}"
        if (author and chat and author not in self.names and message.get("chat_type") != "p2p"
                and time.monotonic() - self._listed.get(chat, -MEMBER_LIST_SECONDS) >= MEMBER_LIST_SECONDS):
            self._listed[chat] = time.monotonic()
            try:
                await self._list_members(chat)
            except FeishuCallError as error:
                if chat not in self._list_failed:
                    self._list_failed.add(chat)
                    self.on_error(f"Feishu member list of {chat} failed; senders show as open_id: {error}")

    async def _list_members(self, chat: str) -> None:
        token = ""
        while True:
            data = await self._api("GET", f"/open-apis/im/v1/chats/{chat}/members",
                                   params={"member_id_type": "open_id", "page_size": 100,
                                           **({"page_token": token} if token else {})})
            for item in data.get("items") or []:
                if isinstance(item.get("member_id"), str) and isinstance(item.get("name"), str):
                    self.names[item["member_id"]] = item["name"]
            token = data.get("page_token") or ""
            if not data.get("has_more") or not token:
                return

    async def _tenant_token(self, *, renew: bool = False) -> str:
        async with self._token_lock:
            if not renew and self._token is not None and self._token[1] - time.time() > TOKEN_MARGIN_SECONDS:
                return self._token[0]
            body = await self._post_json("/open-apis/auth/v3/tenant_access_token/internal",
                                         {"app_id": self.settings.app_id, "app_secret": self.settings.app_secret})
            token, expire = body.get("tenant_access_token"), body.get("expire")
            if body.get("code") != 0 or not isinstance(token, str) or type(expire) is not int:
                raise FeishuCallError(self._safe(f"tenant_access_token refused: {body.get('code')} {body.get('msg')}"),
                                      submitted=False)
            self._token = (token, time.time() + expire)
            return token

    async def _post_json(self, path: str, payload: dict) -> dict:
        if self._client is None:
            raise FeishuCallError("Feishu transport has not been started", submitted=False)
        try:
            response = await self._client.post(path, json=payload)
            body = response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise FeishuCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=False) from None
        except (httpx.HTTPError, ValueError) as error:
            raise FeishuCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=True) from None
        if not isinstance(body, dict):
            raise FeishuCallError(self._safe(f"{path} answered {repr(body)[:300]}"), submitted=True)
        return body

    async def _api(self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None,
                   files: dict | None = None, data: dict | None = None) -> dict:
        """The ``data`` of one Open API call; a stale token is renewed and a rate limit waited out once."""
        if self._client is None:
            raise FeishuCallError("Feishu transport has not been started", submitted=False)
        renew = False
        for attempt in range(2):
            token = await self._tenant_token(renew=renew)
            try:
                response = await self._client.request(method, path, params=params, json=json_body, files=files,
                                                      data=data, headers={"Authorization": f"Bearer {token}"})
                body = response.json()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
                raise FeishuCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=False) from None
            except (httpx.HTTPError, ValueError) as error:
                raise FeishuCallError(self._safe(f"{type(error).__name__}: {error}"), submitted=True) from None
            code = body.get("code") if isinstance(body, dict) else None
            if code == 0:
                return body.get("data") or {}
            if attempt == 0 and code in FEISHU_ERROR_TOKEN:
                renew = True
                continue
            if attempt == 0 and code == FEISHU_ERROR_RATE:
                await asyncio.sleep(1)
                continue
            # A nonzero code means the platform rejected the call before carrying it out.
            raise FeishuCallError(self._safe(f"Feishu {path} {code}: {(body or {}).get('msg')}"), submitted=False)
        raise AssertionError("unreachable")

    async def identify(self) -> str:
        await self._tenant_token(renew=True)
        if self._client is None:
            raise FeishuCallError("Feishu transport has not been started", submitted=False)
        try:
            response = await self._client.get("/open-apis/bot/v3/info",
                                              headers={"Authorization": f"Bearer {self._token[0]}"})
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise FeishuCallError(self._safe(f"bot info: {type(error).__name__}: {error}"), submitted=False) from None
        bot = body.get("bot") if isinstance(body, dict) else None
        open_id = bot.get("open_id") if isinstance(bot, dict) else None
        if body.get("code") != 0 or open_id != self.bot:
            raise FeishuCallError(self._safe(f"bot info did not confirm the configured bot_id {self.settings.bot_id}: "
                                             f"{repr(body)[:300]}"), submitted=False)
        return self.settings.bot_id

    def _text(self, segments: list[Segment]) -> str:
        parts = []
        for segment in segments:
            if segment.type == "text":
                parts.append(segment.data["text"])
            elif segment.type == "mention":
                user = segment.data["user"]
                if user == "all":
                    parts.append('<at user_id="all">所有人</at>')
                else:
                    open_id = user.split(":", 1)[1]
                    parts.append(f'<at user_id="{open_id}">{self.names.get(open_id, "")}</at>')
        return "".join(parts)

    async def send_message(self, message: ChatMessage, *, image_bytes: bytes | None = None) -> SendResult:
        target = chat_target(message.scene)
        if target is None:
            return SendResult("failed", None, f"Invalid Feishu scene: {message.scene!r}")
        unsupported = [segment.type for segment in message.segments
                       if segment.type not in {"text", "mention", "reply", "image"}]
        if unsupported:
            return SendResult("failed", None, f"Unsupported Feishu message segments: {unsupported!r}")
        for segment in message.segments:
            if (segment.type == "mention" and segment.data["user"] != "all"
                    and re.fullmatch(r"feishu:ou_[A-Za-z0-9]+", segment.data["user"]) is None):
                return SendResult("failed", None, f"Invalid Feishu mention: {segment.data['user']!r}")
        image_count = sum(segment.type == "image" for segment in message.segments)
        if image_count > 1:
            return SendResult("failed", None, "Feishu message supports only one image segment")
        if image_count and not image_bytes:
            return SendResult("failed", None, "Feishu image segment requires nonempty image bytes")
        if not image_count and image_bytes is not None:
            return SendResult("failed", None, "Feishu image bytes require an image segment")
        text = self._text(message.segments)
        if not image_count and not text.strip():
            return SendResult("failed", None, "Feishu text message is empty")
        if not self._running or self._client is None:
            return SendResult("failed", None, "Feishu transport is not running; message was not sent")
        try:
            if image_count:
                uploaded = await self._api("POST", "/open-apis/im/v1/images", data={"image_type": "message"},
                                           files={"image": ("image", image_bytes)})
                image_key = uploaded["image_key"]
                if text:
                    msg_type, content = "post", {"zh_cn": {"content": [[*self._post_items(message.segments),
                                                                         {"tag": "img", "image_key": image_key}]]}}
                else:
                    msg_type, content = "image", {"image_key": image_key}
            else:
                msg_type, content = "text", {"text": text}
            reply = next((str(segment.data["id"]) for segment in message.segments if segment.type == "reply"),
                         message.reply_to)
            body = {"msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)}
            if reply is not None and reply.startswith("om_"):
                sent = await self._api("POST", f"/open-apis/im/v1/messages/{reply}/reply", json_body=body)
            else:
                sent = await self._api("POST", "/open-apis/im/v1/messages", params={"receive_id_type": target[0]},
                                       json_body={"receive_id": target[1], **body})
        except FeishuCallError as error:
            return SendResult("unconfirmed" if error.submitted else "failed", None, str(error))
        except (KeyError, TypeError) as error:
            # The image upload answered without a key, so no message was sent.
            return SendResult("failed", None, f"image upload: {type(error).__name__}: {error}")
        message_id = sent.get("message_id")
        if isinstance(message_id, str) and message_id:
            return SendResult("sent", message_id, None)
        return SendResult("unconfirmed", None, self._safe(repr(sent)[:500]))

    def _post_items(self, segments: list[Segment]) -> list[dict]:
        items = []
        for segment in segments:
            if segment.type == "text":
                items.append({"tag": "text", "text": segment.data["text"]})
            elif segment.type == "mention":
                user = segment.data["user"]
                items.append({"tag": "at", "user_id": "all" if user == "all" else user.split(":", 1)[1]})
        return items

    async def upload_file(self, scene: str, file: str, name: str) -> UploadResult:
        """Send a file message; ``file`` is base64:// data or a local path."""
        target = chat_target(scene)
        if target is None:
            return UploadResult("failed", None, f"Invalid Feishu scene: {scene!r}", None)
        if not file or not name:
            return UploadResult("failed", None, "Feishu upload requires a file and name", None)
        try:
            data = (base64.b64decode(file.removeprefix("base64://"), validate=True) if file.startswith("base64://")
                    else await asyncio.to_thread(Path(file).read_bytes))
        except (ValueError, OSError) as error:
            return UploadResult("failed", None, f"{type(error).__name__}: {error}", None)
        if not data or len(data) > FILE_LIMIT_BYTES:
            return UploadResult("failed", None, f"Feishu files must be 1 to {FILE_LIMIT_BYTES} bytes", None)
        try:
            uploaded = await self._api("POST", "/open-apis/im/v1/files", data={"file_type": "stream", "file_name": name},
                                       files={"file": (name, data)})
            sent = await self._api("POST", "/open-apis/im/v1/messages", params={"receive_id_type": target[0]},
                                   json_body={"receive_id": target[1], "msg_type": "file",
                                              "content": json.dumps({"file_key": uploaded["file_key"]})})
        except FeishuCallError as error:
            return UploadResult("unconfirmed" if error.submitted else "failed", None, str(error), None)
        except (KeyError, TypeError) as error:
            # The file upload answered without a key, so no message was sent.
            return UploadResult("failed", None, f"file upload: {type(error).__name__}: {error}", None)
        return UploadResult("uploaded", uploaded["file_key"], None, sent)

    async def scene_title(self, scene: str) -> tuple[str, int | None]:
        target = chat_target(scene)
        if target is None:
            raise FeishuCallError(f"Invalid Feishu scene: {scene!r}", submitted=False)
        if target[0] == "open_id":
            return self.names.get(target[1], target[1]), None
        data = await self._api("GET", f"/open-apis/im/v1/chats/{target[1]}")
        count = data.get("user_count")
        count = int(count) if isinstance(count, int | str) and str(count).isdecimal() else None
        return data.get("name") or target[1], count

    async def download(self, data: dict, max_bytes: int) -> bytes:
        """An inbound image or file through the message resource API."""
        message_id, key = data.get("message_id"), data.get("image_key") or data.get("file_key")
        if not isinstance(message_id, str) or not isinstance(key, str):
            raise ValueError(f"segment names no Feishu message resource: {repr(data)[:200]}")
        if self._client is None:
            raise FeishuCallError("Feishu transport has not been started", submitted=False)
        token = await self._tenant_token()
        try:
            async with self._client.stream(
                    "GET", f"/open-apis/im/v1/messages/{message_id}/resources/{key}",
                    params={"type": "image" if "image_key" in data else "file"},
                    headers={"Authorization": f"Bearer {token}"}) as response:
                if response.status_code != 200 or response.headers.get("content-type", "").startswith("application/json"):
                    detail = (await response.aread())[:300].decode(errors="replace")
                    raise FeishuCallError(self._safe(f"Feishu resource {key} HTTP {response.status_code}: {detail}"),
                                          submitted=False)
                return await read_capped(response.aiter_bytes(), max_bytes)
        except httpx.HTTPError as error:
            raise FeishuCallError(self._safe(f"Feishu resource {key}: {type(error).__name__}: {error}"),
                                  submitted=False) from None

    async def joined_groups(self) -> list[dict]:
        """The group chats the bot is a member of."""
        chats = await _list_chats(lambda params: self._api("GET", "/open-apis/im/v1/chats", params=params))
        return [{"scene": f"feishu:group:{chat}", "name": name, "members": None} for chat, name in chats]

    async def call(self, action: str, params: dict) -> dict:
        """One Open API call: ``action`` is "<METHOD> <path>", ``params`` the query or JSON body."""
        method, _, path = action.partition(" ")
        if method == "GET":
            return await self._api(method, path, params=params)
        return await self._api(method, path, json_body=params)


async def _list_chats(get: Callable[[dict], object]) -> list[tuple[str, str]]:
    chats: list[tuple[str, str]] = []
    token = ""
    while True:
        data = await get({"page_size": 100, **({"page_token": token} if token else {})})
        for item in data.get("items") or []:
            if isinstance(item.get("chat_id"), str):
                chats.append((item["chat_id"], item.get("name") or item["chat_id"]))
        token = data.get("page_token") or ""
        if not data.get("has_more") or not token:
            return chats


async def probe(app_id: str, app_secret: str, *, domain: str = "feishu", timeout_seconds: float = 15.0) -> dict:
    """Check an app's credentials: its tenant token, the bot's open_id and the group chats the bot is in."""
    def safe(text: str) -> str:
        return text.replace(app_secret, REDACTED)[:2000]

    async def answer(response_call) -> dict:
        try:
            body = (await response_call).json()
        except (httpx.HTTPError, ValueError) as error:
            raise FeishuCallError(safe(f"{type(error).__name__}: {error}"), submitted=False) from None
        if not isinstance(body, dict) or body.get("code") != 0:
            detail = f"{body.get('code')} {body.get('msg')}" if isinstance(body, dict) else repr(body)[:300]
            raise FeishuCallError(safe(f"Feishu: {detail}"), submitted=False)
        return body

    async with httpx.AsyncClient(base_url=FEISHU_DOMAINS[domain], transport=_transport(), timeout=timeout_seconds,
                                 follow_redirects=False) as client:
        body = await answer(client.post("/open-apis/auth/v3/tenant_access_token/internal",
                                        json={"app_id": app_id, "app_secret": app_secret}))
        headers = {"Authorization": f"Bearer {body.get('tenant_access_token')}"}
        bot = (await answer(client.get("/open-apis/bot/v3/info", headers=headers))).get("bot") or {}
        if not isinstance(bot.get("open_id"), str):
            raise FeishuCallError(f"bot info has no open_id: {repr(bot)[:300]}", submitted=False)

        async def get(params: dict) -> dict:
            return (await answer(client.get("/open-apis/im/v1/chats", params=params, headers=headers))).get("data") or {}

        try:
            chats = await _list_chats(get)
        except FeishuCallError:
            # Listing chats needs its own permission; the credentials themselves passed.
            chats = []
    return {"bot_id": f"feishu:{bot['open_id']}", "name": bot.get("app_name") or bot["open_id"],
            "groups": [{"id": chat, "name": name} for chat, name in chats]}
