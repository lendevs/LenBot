"""Telegram adapter against a local stand-in for the Bot API."""

import asyncio
import base64
import json
import time

import httpx
import pytest

from len_bot.next.configuration.platforms import TelegramSettings
from len_bot.next.platform import telegram
from len_bot.next.platform.adapter import PlatformCallError, PlatformGroup
from len_bot.next.platform.messages import ChatMessage, Notice, Segment, Sender
from len_bot.next.platform.telegram import Telegram, parse_update

TOKEN = "7000000001:" + "s" * 35
BOT = 7000000001
GROUP = -1001234


def _message(text: str | None = None, *, message_id: int = 11, user: dict | None = None, date: float | None = None,
             **fields) -> dict:
    message = {"message_id": message_id, "date": int(time.time() if date is None else date),
               "chat": {"id": GROUP, "type": "supergroup", "title": "测试群"},
               "from": user or {"id": 501, "is_bot": False, "first_name": "Ann", "username": "ann"}, **fields}
    if text is not None:
        message["text"] = text
    return message


class BotAPI:
    """Answers Bot API methods for one bot; getUpdates long-polls the queued updates."""

    def __init__(self, bot: int = BOT):
        self.bot = bot
        self.updates: asyncio.Queue = asyncio.Queue()
        self.calls: list[tuple[str, dict]] = []
        self.failures: dict[str, list[httpx.Response]] = {}
        # Forum topic of each message a reply may point at.
        self.topics: dict[int, int] = {}
        self.next_id = 100
        self.update_id = 0

    def push(self, message: dict) -> None:
        self.update_id += 1
        self.updates.put_nowait({"update_id": self.update_id, "message": message})

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith(f"/file/bot{TOKEN}/"):
            self.calls.append(("file", {"path": request.url.path.removeprefix(f"/file/bot{TOKEN}/")}))
            return httpx.Response(200, content=b"photo-bytes" * 10)
        prefix, _, method = request.url.path.rpartition("/")
        assert prefix == f"/bot{TOKEN}"
        if request.headers.get("content-type", "").startswith("multipart/"):
            params = {"multipart": request.content}
        else:
            params = json.loads(request.content or b"{}")
        self.calls.append((method, params))
        if self.failures.get(method):
            return self.failures[method].pop(0)
        if method == "getMe":
            return self._ok({"id": self.bot, "is_bot": True, "first_name": "Len", "username": "len_bot"})
        if method == "getUpdates":
            try:
                first = await asyncio.wait_for(self.updates.get(), min(params["timeout"], 0.2))
            except TimeoutError:
                return self._ok([])
            return self._ok([first])
        if method in {"sendMessage", "sendPhoto", "sendDocument"}:
            self.next_id += 1
            result = {"message_id": self.next_id, "date": int(time.time()), "chat": {"id": GROUP, "type": "supergroup"}}
            topic = params.get("message_thread_id") or self.topics.get(params.get("reply_parameters", {}).get("message_id"))
            if topic is not None:
                result.update(is_topic_message=True, message_thread_id=topic)
            if method == "sendDocument":
                result["document"] = {"file_id": "BQAC-document", "file_unique_id": "doc"}
            return self._ok(result)
        if method == "getChat":
            return self._ok({"id": params["chat_id"], "type": "supergroup", "title": "测试群"})
        if method == "getChatMemberCount":
            return self._ok(42)
        if method == "getFile":
            return self._ok({"file_id": params["file_id"], "file_unique_id": "u", "file_size": 110,
                             "file_path": f"photos/{params['file_id']}.jpg"})
        return httpx.Response(404, json={"ok": False, "error_code": 404, "description": "Not Found"})

    @staticmethod
    def _ok(result) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": result})


@pytest.fixture
def api(monkeypatch):
    stand_in = BotAPI()
    monkeypatch.setattr(telegram, "_transport", lambda proxy: httpx.MockTransport(stand_in.handle))
    monkeypatch.setattr(telegram, "RECONNECT_INITIAL_SECONDS", 0.01)
    return stand_in


def _settings(**changes) -> TelegramSettings:
    return TelegramSettings(bot_id=f"telegram:{BOT}", bot_token=TOKEN, **changes)


async def _until(condition, seconds: float = 3) -> None:
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.01)


def test_text_mentions_are_split_on_utf16_offsets():
    # The emoji is two UTF-16 code units, so the @username entity starts at offset 3, not 2.
    message = _message("😀 @len_bot 看 @bob 和 Carl", entities=[
        {"type": "mention", "offset": 3, "length": 8},
        {"type": "mention", "offset": 14, "length": 4},
        {"type": "text_mention", "offset": 21, "length": 4, "user": {"id": 502, "is_bot": False, "first_name": "Carl"}},
    ])
    parsed = parse_update({"update_id": 1, "message": message}, bot=BOT, username="len_bot")
    assert isinstance(parsed, ChatMessage)
    assert parsed.scene == f"telegram:group:{GROUP}" and parsed.bot_id == f"telegram:{BOT}"
    assert parsed.sender == Sender(uid="telegram:501", nickname="Ann", card=None, role=None)
    assert parsed.mentions_bot and not parsed.is_self and parsed.platform_message_id == "11"
    assert parsed.segments == [
        Segment("text", {"text": "😀 "}), Segment("mention", {"user": f"telegram:{BOT}"}),
        Segment("text", {"text": " 看 @bob 和 "}), Segment("mention", {"user": "telegram:502"})]


def test_commands_addressed_to_this_bot_lose_the_bot_suffix():
    message = _message("/日程@Len_Bot 明天 /start@other_bot", entities=[
        {"type": "bot_command", "offset": 0, "length": 11},
        {"type": "bot_command", "offset": 15, "length": 16},
    ])
    parsed = parse_update({"update_id": 1, "message": message}, bot=BOT, username="len_bot")
    assert parsed.mentions_bot
    assert parsed.segments == [Segment("text", {"text": "/日程"}), Segment("text", {"text": " 明天 /start@other_bot"})]
    other = parse_update({"update_id": 2, "message": _message("/start@other_bot", entities=[
        {"type": "bot_command", "offset": 0, "length": 16}])}, bot=BOT, username="len_bot")
    assert not other.mentions_bot and other.segments == [Segment("text", {"text": "/start@other_bot"})]


def test_media_replies_and_forum_topics():
    photo = _message(caption="看图", photo=[
        {"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90},
        {"file_id": "large", "file_unique_id": "l", "width": 800, "height": 600}],
        reply_to_message={"message_id": 9, "date": 0, "chat": {"id": GROUP, "type": "supergroup"},
                          "from": {"id": BOT, "is_bot": True, "first_name": "Len"}})
    parsed = parse_update({"update_id": 1, "message": photo}, bot=BOT, username="len_bot")
    assert parsed.reply_to == "9" and parsed.mentions_bot
    assert [segment.type for segment in parsed.segments] == ["reply", "image", "text"]
    assert parsed.segments[1].data == {"file_id": "large", "file_unique_id": "l"}
    topic = _message("话题里的话", is_topic_message=True, message_thread_id=7,
                     reply_to_message={"message_id": 7, "date": 0, "chat": {"id": GROUP, "type": "supergroup"},
                                       "forum_topic_created": {"name": "闲聊", "icon_color": 0}})
    parsed = parse_update({"update_id": 2, "message": topic}, bot=BOT, username="len_bot")
    assert parsed.reply_to is None and not parsed.mentions_bot
    sticker = _message(sticker={"file_id": "st", "file_unique_id": "u", "emoji": "😂", "is_animated": False,
                                "is_video": False, "type": "regular", "width": 512, "height": 512})
    assert parse_update({"update_id": 3, "message": sticker}, bot=BOT, username=None).segments == [
        Segment("image", {"file_id": "st", "file_unique_id": "u", "summary": "😂", "sub_type": 1})]
    voice = _message(voice={"file_id": "vo", "file_unique_id": "v", "duration": 3, "mime_type": "audio/ogg"})
    assert parse_update({"update_id": 4, "message": voice}, bot=BOT, username=None).segments[0].type == "audio"


def test_joins_leaves_and_unfollowed_chats():
    joined = _message(new_chat_members=[{"id": 503, "is_bot": False, "first_name": "Dee"}])
    notice = parse_update({"update_id": 1, "message": joined}, bot=BOT, username=None)
    assert isinstance(notice, Notice) and notice.notice_type == "group_increase" and notice.sub_type == "invite"
    assert notice.user_id == "telegram:503" and notice.operator_id == "telegram:501"
    left = _message(left_chat_member={"id": 501, "is_bot": False, "first_name": "Ann"})
    notice = parse_update({"update_id": 2, "message": left}, bot=BOT, username=None)
    assert (notice.notice_type, notice.sub_type, notice.operator_id) == ("group_decrease", "leave", None)
    channel = {**_message("频道"), "chat": {"id": -100999, "type": "channel", "title": "频道"}}
    assert parse_update({"update_id": 3, "message": channel}, bot=BOT, username=None) is None
    assert parse_update({"update_id": 4, "message": _message(new_chat_title="新群名")}, bot=BOT, username=None) is None
    assert parse_update({"update_id": 5, "edited_message": _message("改")}, bot=BOT, username=None) is None


@pytest.mark.asyncio
async def test_receives_updates_and_sends_mentions_replies_photos_and_files(api):
    received, errors = [], []
    adapter = Telegram(_settings(), on_event=received.append, on_error=errors.append)
    api.push(_message("昨天的话", message_id=1, date=time.time() - 3600))
    await adapter.start()
    try:
        assert adapter.connected and adapter.username == "len_bot"
        api.push(_message("在吗", message_id=2, user={"id": 502, "is_bot": False, "first_name": "Carl"}))
        await _until(lambda: received)
        assert [adapter.parse(raw).platform_message_id for raw in received] == ["2"]
        scene = f"telegram:group:{GROUP}"

        def outgoing(*segments: Segment) -> ChatMessage:
            return ChatMessage(id="out", platform="telegram", bot_id=f"telegram:{BOT}", scene=scene,
                               platform_message_id=None, sender=Sender(f"telegram:{BOT}", None, None, None),
                               time=time.time(), segments=list(segments), reply_to=None, mentions_bot=False,
                               is_self=True, send_status="sent")

        result = await adapter.send_message(outgoing(
            Segment("reply", {"id": "2"}), Segment("text", {"text": "😀 "}),
            Segment("mention", {"user": "telegram:502"}), Segment("text", {"text": " 在"})))
        assert result.status == "sent" and result.platform_message_id == "101"
        method, params = api.calls[-1]
        assert method == "sendMessage" and params["text"] == "😀 Carl 在"
        assert params["reply_parameters"] == {"message_id": 2, "allow_sending_without_reply": True}
        assert params["entities"] == [{"type": "text_mention", "offset": 3, "length": 4,
                                       "user": {"id": 502, "is_bot": False, "first_name": "Carl"}}]
        # Ann's only message was backlog, so the adapter knows no name for her yet.
        await adapter.send_message(outgoing(Segment("mention", {"user": "telegram:501"}), Segment("text", {"text": "?"})))
        assert api.calls[-1][1]["text"] == "501?" and api.calls[-1][1]["entities"][0]["user"]["id"] == 501
        api.push(_message("我在", message_id=4))
        await _until(lambda: len(received) == 2)
        await adapter.send_message(outgoing(Segment("mention", {"user": "telegram:501"}), Segment("text", {"text": "?"})))
        assert api.calls[-1][1]["text"] == "@ann?" and "entities" not in api.calls[-1][1]
        result = await adapter.send_message(outgoing(Segment("image", {"sub_type": 1})), image_bytes=b"\x89PNG-bytes")
        assert result.status == "sent" and api.calls[-1][0] == "sendPhoto" and b"\x89PNG-bytes" in api.calls[-1][1]["multipart"]
        upload = await adapter.upload_file(scene, "base64://" + base64.b64encode(b"report").decode(), "报告.txt")
        assert upload.status == "uploaded" and upload.file_id == "BQAC-document"
        assert "报告.txt".encode() in api.calls[-1][1]["multipart"]
        assert (await adapter.scene_title(scene)) == ("测试群", 42)
        assert await adapter.download({"file_id": "large"}, 1000) == b"photo-bytes" * 10
        assert api.calls[-1] == ("file", {"path": "photos/large.jpg"})
        with pytest.raises(ValueError, match="above 100"):
            await adapter.download({"file_id": "large"}, 100)
        # Longer text goes out as several messages, cut after a line break; only the first one replies.
        api.calls.clear()
        long = "甲" * 3000 + "\n" + "乙" * 3000
        split = await adapter.send_message(outgoing(Segment("reply", {"id": "2"}), Segment("text", {"text": long}),
                                                    Segment("mention", {"user": "telegram:502"})))
        sends = [params for method, params in api.calls if method == "sendMessage"]
        assert split.status == "sent" and split.platform_message_id == str(api.next_id - 1)
        assert [len(params["text"]) for params in sends] == [3001, 3004]
        assert sends[0]["text"].endswith("\n") and sends[0]["reply_parameters"]["message_id"] == 2
        assert "reply_parameters" not in sends[1]
        assert sends[1]["entities"] == [{"type": "text_mention", "offset": 3000, "length": 4,
                                         "user": {"id": 502, "is_bot": False, "first_name": "Carl"}}]
        api.calls.clear()
        photo = await adapter.send_message(outgoing(Segment("image", {"file": "x"}), Segment("text", {"text": "图" * 1500})),
                                           image_bytes=b"png")
        assert photo.status == "sent"
        assert [(method, len(params.get("text", ""))) for method, params in api.calls] == [("sendPhoto", 0), ("sendMessage", 476)]
        api.failures["sendMessage"] = [
            api._ok({"message_id": 900, "date": int(time.time()), "chat": {"id": GROUP, "type": "supergroup"}}),
            httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad"})]
        partial = await adapter.send_message(outgoing(Segment("text", {"text": "x" * 5000})))
        assert partial.status == "unconfirmed" and partial.platform_message_id == "900" and "part 2 of 2" in partial.error
    finally:
        await adapter.close()
    assert not adapter.connected and errors == []
    await asyncio.wait_for(adapter.wait_terminated(), 1)


@pytest.mark.asyncio
async def test_long_messages_stay_in_the_first_parts_topic(api):
    received = []
    adapter = Telegram(_settings(), on_event=received.append, on_error=lambda error: None)
    await adapter.start()
    try:
        api.topics = {20: 7}
        api.push(_message("话题 7", message_id=20, is_topic_message=True, message_thread_id=7))
        api.push(_message("话题 9", message_id=21, is_topic_message=True, message_thread_id=9))
        api.push(_message("综合区", message_id=22))
        await _until(lambda: len(received) == 3)
        scene = f"telegram:group:{GROUP}"

        def outgoing(*segments: Segment) -> ChatMessage:
            return ChatMessage(id="out", platform="telegram", bot_id=f"telegram:{BOT}", scene=scene,
                               platform_message_id=None, sender=Sender(f"telegram:{BOT}", None, None, None),
                               time=time.time(), segments=list(segments), reply_to=None, mentions_bot=False,
                               is_self=True, send_status="sent")

        long = Segment("text", {"text": "甲" * 3000 + "\n" + "乙" * 3000})
        for reply, topic in (("20", 7), ("22", None), (None, 9)):
            api.calls.clear()
            segments = [long] if reply is None else [Segment("reply", {"id": reply}), long]
            assert (await adapter.send_message(outgoing(*segments))).status == "sent"
            sends = [params for method, params in api.calls if method == "sendMessage"]
            assert len(sends) == 2 and sends[1].get("message_thread_id") == topic
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_rate_limit_is_waited_out_once_and_errors_keep_the_token_out(api):
    errors = []
    adapter = Telegram(_settings(), on_event=lambda raw: None, on_error=errors.append)
    await adapter.start()
    try:
        limited = httpx.Response(429, json={"ok": False, "error_code": 429, "description": "Too Many Requests",
                                            "parameters": {"retry_after": 0}})
        api.failures["sendMessage"] = [limited]
        message = ChatMessage(id="out", platform="telegram", bot_id=f"telegram:{BOT}", scene="telegram:private:501",
                              platform_message_id=None, sender=Sender(f"telegram:{BOT}", None, None, None),
                              time=time.time(), segments=[Segment("text", {"text": "好"})], reply_to=None,
                              mentions_bot=False, is_self=True, send_status="sent")
        assert (await adapter.send_message(message)).status == "sent"
        assert [method for method, _ in api.calls].count("sendMessage") == 2
        api.failures["sendMessage"] = [httpx.Response(403, json={
            "ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})]
        blocked = await adapter.send_message(message)
        assert blocked.status == "failed" and "blocked" in blocked.error
        # A dropped poll marks the bot disconnected, and the next successful poll connects it again.
        api.failures["getUpdates"] = [httpx.Response(502, text=f"bad gateway for /bot{TOKEN}/getUpdates")]
        await _until(lambda: errors)
        await _until(lambda: adapter.connected)
        assert "getUpdates" in errors[0] and TOKEN not in errors[0]
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_start_fails_when_the_token_belongs_to_another_bot(monkeypatch):
    stand_in = BotAPI(bot=7000000002)
    monkeypatch.setattr(telegram, "_transport", lambda proxy: httpx.MockTransport(stand_in.handle))
    adapter = Telegram(_settings(), on_event=lambda raw: None, on_error=lambda text: None)
    with pytest.raises(PlatformCallError, match="did not confirm") as failure:
        await adapter.start()
    assert TOKEN not in str(failure.value) and not adapter.connected


@pytest.mark.asyncio
async def test_a_group_routes_events_and_sends_by_scene_prefix(api):
    received, errors = [], []

    def open_telegram(**callbacks):
        return Telegram(_settings(), **callbacks)

    def open_other(**callbacks):
        other = Telegram(_settings(), **callbacks)
        other.name = "other"
        return other

    group = PlatformGroup({"telegram": open_telegram, "other": open_other},
                          on_event=lambda raw: received.append(group.parse(raw)), on_error=errors.append)
    assert group.name == "telegram+other"
    await group.start()
    try:
        await asyncio.wait_for(group.wait_connected(None), 1)
        api.push(_message("你好", message_id=3))
        await _until(lambda: received)
        assert isinstance(received[0], ChatMessage) and received[0].scene == f"telegram:group:{GROUP}"
        with pytest.raises(ValueError, match="delivering"):
            group.parse({"update_id": 9})
        missing = ChatMessage(id="out", platform="feishu", bot_id="feishu:ou_bot", scene="feishu:group:oc_room",
                              platform_message_id=None, sender=Sender("feishu:ou_bot", None, None, None),
                              time=time.time(), segments=[Segment("text", {"text": "x"})], reply_to=None,
                              mentions_bot=False, is_self=True, send_status="sent")
        assert (await group.send_message(missing)).status == "failed"
        assert (await group.scene_title(f"telegram:group:{GROUP}")) == ("测试群", 42)
    finally:
        await group.close()
    assert not group.connected
    await asyncio.wait_for(group.wait_terminated(), 1)


@pytest.mark.asyncio
async def test_a_group_does_not_start_unless_every_platform_starts(api):
    started = []

    def open_good(**callbacks):
        adapter = Telegram(_settings(), **callbacks)
        started.append(adapter)
        return adapter

    def open_bad(**callbacks):
        adapter = Telegram(_settings(), **callbacks)
        adapter.name = "bad"
        adapter.bot = BOT + 1
        return adapter

    group = PlatformGroup({"telegram": open_good, "bad": open_bad}, on_event=lambda raw: None,
                          on_error=lambda text: None)
    with pytest.raises(PlatformCallError, match="bad: getMe did not confirm"):
        await group.start()
    assert not started[0].connected
