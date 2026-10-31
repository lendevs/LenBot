"""Feishu adapter against a local long-connection server and a stand-in for the Open API."""

import asyncio
import json
import time

import httpx
import pytest
import pytest_asyncio
from websockets.asyncio.server import serve

from len_bot.next.configuration.platforms import FeishuSettings
from len_bot.next.platform import feishu
from len_bot.next.platform.adapter import PlatformCallError
from len_bot.next.platform.feishu import Feishu, decode_frame, encode_frame, parse_event
from len_bot.next.platform.messages import ChatMessage, Notice, Segment, Sender

SECRET = "synthetic-app-secret"
GROUP = "oc_room"


def _event(event_id: str, message: dict, *, sender: str = "ou_ann") -> dict:
    return {"schema": "2.0",
            "header": {"event_id": event_id, "event_type": "im.message.receive_v1",
                       "create_time": str(int(time.time() * 1000)), "app_id": "cli_app"},
            "event": {"sender": {"sender_id": {"open_id": sender}, "sender_type": "user"},
                      "message": {"chat_id": GROUP, "chat_type": "group", "create_time": str(int(time.time() * 1000)),
                                  **message}}}


def _text(event_id: str, message_id: str, text: str, mentions: list | None = None, **fields) -> dict:
    return _event(event_id, {"message_id": message_id, "message_type": "text",
                             "content": json.dumps({"text": text}, ensure_ascii=False),
                             "mentions": mentions or [], **fields})


class OpenAPI:
    """Answers the Open API calls the adapter makes and records them."""

    def __init__(self, bot: str = "ou_bot"):
        self.bot = bot
        self.url = ""
        self.calls: list[tuple[str, str, object]] = []
        self.failures: dict[str, list[dict]] = {}
        self.tokens = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content)
        else:
            body = request.content
        self.calls.append((request.method, path, body))
        if self.failures.get(path):
            return httpx.Response(200, json=self.failures[path].pop(0))
        if path == "/open-apis/auth/v3/tenant_access_token/internal":
            assert body == {"app_id": "cli_app", "app_secret": SECRET}
            self.tokens += 1
            return httpx.Response(200, json={"code": 0, "tenant_access_token": f"t-{self.tokens}", "expire": 7200})
        if path == "/callback/ws/endpoint":
            return httpx.Response(200, json={"code": 0, "data": {"URL": self.url, "ClientConfig": {"PingInterval": 120}}})
        assert request.headers["authorization"] == f"Bearer t-{self.tokens}"
        if path == "/open-apis/bot/v3/info":
            return httpx.Response(200, json={"code": 0, "bot": {"open_id": self.bot, "app_name": "Len"}})
        if path == f"/open-apis/im/v1/chats/{GROUP}/members":
            return httpx.Response(200, json={"code": 0, "data": {"items": [
                {"member_id": "ou_ann", "name": "Ann"}, {"member_id": "ou_bob", "name": "Bob"}], "has_more": False}})
        if path == f"/open-apis/im/v1/chats/{GROUP}":
            return httpx.Response(200, json={"code": 0, "data": {"name": "测试群", "user_count": "12"}})
        if path == "/open-apis/im/v1/images":
            return httpx.Response(200, json={"code": 0, "data": {"image_key": "img_v2_sent"}})
        if path == "/open-apis/im/v1/files":
            return httpx.Response(200, json={"code": 0, "data": {"file_key": "file_v2_sent"}})
        if path.startswith("/open-apis/im/v1/messages"):
            return httpx.Response(200, json={"code": 0, "data": {"message_id": f"om_sent{len(self.calls)}"}})
        return httpx.Response(404, json={"code": 404, "msg": "not found"})


class LongConnection:
    """A long-connection server: queues frames to push and records every frame and answer it receives."""

    def __init__(self):
        self.received: list[dict] = []
        self.outgoing: asyncio.Queue = asyncio.Queue()
        self.connections = 0
        self.drop = asyncio.Event()

    async def handle(self, websocket) -> None:
        self.connections += 1
        self.drop.clear()

        async def read():
            async for data in websocket:
                self.received.append(decode_frame(data))

        reader = asyncio.create_task(read())
        try:
            while True:
                push = asyncio.create_task(self.outgoing.get())
                dropped = asyncio.create_task(self.drop.wait())
                done, _ = await asyncio.wait({push, dropped, reader}, return_when=asyncio.FIRST_COMPLETED)
                dropped.cancel()
                if push not in done:
                    push.cancel()
                    return
                await websocket.send(push.result())
        finally:
            reader.cancel()

    def push(self, raw: dict, *, parts: int = 1, message_id: str = "frame-1") -> None:
        payload = json.dumps(raw, ensure_ascii=False).encode()
        size = -(-len(payload) // parts)
        for seq in range(parts):
            self.outgoing.put_nowait(encode_frame({
                "seq_id": seq, "log_id": 7, "service": 33, "method": 1,
                "headers": {"type": "event", "message_id": message_id, "sum": str(parts), "seq": str(seq),
                            "trace_id": "trace"},
                "payload": payload[seq * size:(seq + 1) * size]}))


@pytest_asyncio.fixture
async def platform(monkeypatch):
    api, server = OpenAPI(), LongConnection()
    monkeypatch.setattr(feishu, "_transport", lambda: httpx.MockTransport(api.handle))
    monkeypatch.setattr(feishu, "RECONNECT_INITIAL_SECONDS", 0.01)
    async with serve(server.handle, "127.0.0.1", 0) as listening:
        port = listening.sockets[0].getsockname()[1]
        api.url = f"ws://127.0.0.1:{port}/ws?device_id=d1&service_id=33"
        yield api, server


def _settings() -> FeishuSettings:
    return FeishuSettings(bot_id="feishu:ou_bot", app_id="cli_app", app_secret=SECRET)


async def _until(condition, seconds: float = 3) -> None:
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.01)


def test_frames_round_trip():
    frame = {"seq_id": 300, "log_id": 2 ** 40, "service": 33, "method": 1,
             "headers": {"type": "event", "message_id": "m"}, "payload": "事件".encode()}
    assert decode_frame(encode_frame(frame)) == frame


def test_messages_posts_recalls_and_members():
    text = _text("e1", "om_1", "@_user_1 你好 @_user_2", mentions=[
        {"key": "@_user_1", "id": {"open_id": "ou_bot"}, "name": "Len"},
        {"key": "@_user_2", "id": {"open_id": "ou_bob"}, "name": "Bob"}], parent_id="om_0")
    parsed = parse_event(text, bot="ou_bot", names={"ou_ann": "Ann"}, scenes={})
    assert isinstance(parsed, ChatMessage) and parsed.scene == f"feishu:group:{GROUP}"
    assert parsed.sender == Sender("feishu:ou_ann", "Ann", None, None) and parsed.bot_id == "feishu:ou_bot"
    assert parsed.mentions_bot and parsed.reply_to == "om_0"
    assert parsed.segments == [Segment("reply", {"id": "om_0"}), Segment("mention", {"user": "feishu:ou_bot"}),
                               Segment("text", {"text": " 你好 "}), Segment("mention", {"user": "feishu:ou_bob"})]
    post = _event("e2", {"message_id": "om_2", "message_type": "post", "mentions": [],
                         "content": json.dumps({"title": "标题", "content": [
                             [{"tag": "text", "text": "看"}, {"tag": "img", "image_key": "img_1"}],
                             [{"tag": "at", "user_id": "ou_bot", "user_name": "Len"}]]})})
    parsed = parse_event(post, bot="ou_bot", names={}, scenes={})
    assert [segment.type for segment in parsed.segments] == ["text", "text", "image", "text", "mention"]
    assert parsed.segments[2].data == {"image_key": "img_1", "message_id": "om_2"} and parsed.mentions_bot
    private = _text("e3", "om_3", "私聊", chat_type="p2p", chat_id="oc_p2p")
    assert parse_event(private, bot="ou_bot", names={}, scenes={}).scene == "feishu:private:ou_ann"
    recall = {"header": {"event_id": "e4", "event_type": "im.message.recalled_v1", "create_time": "0"},
              "event": {"message_id": "om_3", "chat_id": "oc_p2p", "recall_time": "1790000000000"}}
    notice = parse_event(recall, bot="ou_bot", names={}, scenes={"oc_p2p": "feishu:private:ou_ann"})
    assert isinstance(notice, Notice) and (notice.scene, notice.notice_type) == ("feishu:private:ou_ann", "friend_recall")
    joined = {"header": {"event_id": "e5", "event_type": "im.chat.member.user.added_v1", "create_time": "1790000000000"},
              "event": {"chat_id": GROUP, "operator_id": {"open_id": "ou_ann"},
                        "users": [{"name": "Dee", "user_id": {"open_id": "ou_dee"}}]}}
    notice = parse_event(joined, bot="ou_bot", names={}, scenes={})
    assert (notice.notice_type, notice.sub_type, notice.user_id, notice.operator_id) == (
        "group_increase", "invite", "feishu:ou_dee", "feishu:ou_ann")
    other = {"header": {"event_id": "e6", "event_type": "im.chat.updated_v1", "create_time": "0"}, "event": {}}
    assert parse_event(other, bot="ou_bot", names={}, scenes={}) is None


@pytest.mark.asyncio
async def test_receives_answers_and_sends_through_the_open_api(platform):
    api, server = platform
    received, errors = [], []
    adapter = Feishu(_settings(), on_event=received.append, on_error=errors.append)
    await adapter.start()
    try:
        assert adapter.connected
        await _until(lambda: server.received)
        assert server.received[0]["headers"] == {"type": "ping"} and server.received[0]["service"] == 33
        event = _text("e1", "om_1", "@_user_1 在吗", mentions=[{"key": "@_user_1", "id": {"open_id": "ou_bot"}, "name": "Len"}])
        server.push(event)
        server.push(event, message_id="frame-2")
        server.push(_text("e2", "om_2", "长消息" * 200), parts=3, message_id="frame-3")
        # The repeated event is answered but not delivered; a split payload is answered once it is whole.
        await _until(lambda: len(received) == 2 and len(server.received) >= 4)
        answers = [frame for frame in server.received if frame.get("method") == 1]
        assert [json.loads(frame["payload"]) for frame in answers] == [{"code": 200}] * 3
        assert answers[2]["headers"]["message_id"] == "frame-3"
        assert answers[0]["headers"]["message_id"] == "frame-1" and answers[0]["seq_id"] == 0
        first = adapter.parse(received[0])
        assert first.sender.nickname == "Ann" and first.mentions_bot
        assert "".join(segment.data["text"] for segment in adapter.parse(received[1]).segments) == "长消息" * 200
        scene = f"feishu:group:{GROUP}"

        def outgoing(*segments: Segment) -> ChatMessage:
            return ChatMessage(id="out", platform="feishu", bot_id="feishu:ou_bot", scene=scene,
                               platform_message_id=None, sender=Sender("feishu:ou_bot", None, None, None),
                               time=time.time(), segments=list(segments), reply_to=None, mentions_bot=False,
                               is_self=True, send_status="sent")

        api.failures["/open-apis/im/v1/messages/om_1/reply"] = [{"code": 99991663, "msg": "token invalid"}]
        result = await adapter.send_message(outgoing(Segment("reply", {"id": "om_1"}),
                                                     Segment("mention", {"user": "feishu:ou_ann"}),
                                                     Segment("text", {"text": " 在的"})))
        assert result.status == "sent" and api.tokens == 2
        method, path, body = api.calls[-1]
        assert path == "/open-apis/im/v1/messages/om_1/reply" and body["msg_type"] == "text"
        assert json.loads(body["content"]) == {"text": '<at user_id="ou_ann">Ann</at> 在的'}
        result = await adapter.send_message(outgoing(Segment("text", {"text": "看图"}), Segment("image", {})),
                                            image_bytes=b"\x89PNG-bytes")
        assert result.status == "sent" and [call[1] for call in api.calls[-2:]] == [
            "/open-apis/im/v1/images", "/open-apis/im/v1/messages"]
        assert json.loads(api.calls[-1][2]["content"]) == {"zh_cn": {"content": [[
            {"tag": "text", "text": "看图"}, {"tag": "img", "image_key": "img_v2_sent"}]]}}
        upload = await adapter.upload_file(scene, "base64://cmVwb3J0", "报告.txt")
        assert upload.status == "uploaded" and upload.file_id == "file_v2_sent"
        assert json.loads(api.calls[-1][2]["content"]) == {"file_key": "file_v2_sent"}
        assert (await adapter.scene_title(scene)) == ("测试群", 12)
        private = await adapter.send_message(ChatMessage(
            id="out", platform="feishu", bot_id="feishu:ou_bot", scene="feishu:private:ou_ann",
            platform_message_id=None, sender=Sender("feishu:ou_bot", None, None, None), time=time.time(),
            segments=[Segment("text", {"text": "好"})], reply_to=None, mentions_bot=False, is_self=True,
            send_status="sent"))
        assert private.status == "sent"
        assert api.calls[-1][2]["receive_id"] == "ou_ann"
        # A dropped connection is dialed again through a fresh endpoint.
        server.drop.set()
        await _until(lambda: server.connections == 2 and adapter.connected)
    finally:
        await adapter.close()
    assert not adapter.connected
    assert all(SECRET not in text and "t-1" not in text for text in errors)
    await asyncio.wait_for(adapter.wait_terminated(), 1)


@pytest.mark.asyncio
async def test_start_fails_for_another_app_bot(monkeypatch):
    api = OpenAPI(bot="ou_other")
    monkeypatch.setattr(feishu, "_transport", lambda: httpx.MockTransport(api.handle))
    adapter = Feishu(_settings(), on_event=lambda raw: None, on_error=lambda text: None)
    with pytest.raises(PlatformCallError, match="did not confirm") as failure:
        await adapter.start()
    assert SECRET not in str(failure.value) and not adapter.connected
