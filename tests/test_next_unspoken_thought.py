"""Neutral projection of unspoken plain-text thoughts, recap failure cooldown, and direct send interruption."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.context import ChatContext
from len_bot.next.chat.expression import ChatExpression
from len_bot.next.chat.session import Chat
from len_bot.next.chat.tools import SayArguments, build_tools
from len_bot.next.config import load_config
from len_bot.next.models.client import ChatModel, ModelHTTPError, ModelProtocolError, ModelSettings
from len_bot.next.models.protocols import build_request
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.messages import SendResult
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message as onebot_message, response as tool_response
from test_next_native_models import peer_server
from test_next_persona_permissions import _config, _package

SCENE = "onebot:group:80001"


def _make_context(tmp_path: Path, *, history_policy: str = "native"):
    package = _package(tmp_path, "plain", tools=["say"], documents={})
    config = _config(tmp_path / "instance", package)
    config.models.roles.mind.history_policy = history_policy
    persona = load_persona(package)
    return config, persona


def test_unspoken_plain_text_assistant_projects_neutrally_and_keeps_db_untouched(tmp_path):
    config, persona = _make_context(tmp_path)
    with Store(config.database) as store:
        context = ChatContext(config, persona, store, platform=False, memory=None)
        raw_unspoken = {
            "role": "assistant",
            "content": "  先看看大家怎么聊，暂时不插话  ",
            "tool_calls": None,
            "reasoning_content": "internal reasoning",
            "_continuation": {"binding": {"api": "anthropic", "model": "m", "base_url": "u"}, "data": []},
            "_binding": {"api": "openai-chat", "model": "m", "base_url": "u"},
        }
        with_call = {
            "role": "assistant",
            "content": "我来看看",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "say", "arguments": '{"content":"来了"}'}}],
        }
        empty_assistant = {"role": "assistant", "content": "   ", "tool_calls": None}
        store.append(SCENE, {"role": "user", "content": "大家晚饭吃什么"})
        store.append(SCENE, raw_unspoken)
        store.append(SCENE, {"role": "user", "content": "有人在吗"})
        store.append(SCENE, with_call)
        store.append(SCENE, {"role": "tool", "tool_call_id": "c1", "content": "来了"})
        store.append(SCENE, empty_assistant)

        _, stored_entries = store.active_history(SCENE)
        assert stored_entries[1][1]["role"] == "assistant"
        assert stored_entries[1][1]["content"] == "  先看看大家怎么聊，暂时不插话  "

        projected = context.project_entries(stored_entries)
        messages = [entry for _, entry in projected]

        assert messages[1] == {"role": "user", "content": "[上一轮未发出的内部想法：先看看大家怎么聊，暂时不插话]"}
        assert "不要模仿" not in messages[1]["content"]
        assert "必须调用" not in messages[1]["content"]
        assert "_continuation" not in messages[1] and "_binding" not in messages[1]
        assert messages[3]["role"] == "assistant" and messages[3]["tool_calls"] is not None
        assert messages[5]["role"] == "assistant"

        # Adjacent user entries convert cleanly across Anthropic, Gemini and OpenAI protocols.
        wire_messages = [{"role": "system", "content": "system"}, *messages[:3]]
        for api in ("openai-chat", "openai-responses", "anthropic", "gemini"):
            settings = ModelSettings(api=api, base_url="https://example.invalid/v1", api_key="k", model="m")
            _, payload = build_request(settings, wire_messages, [])
            if api == "anthropic":
                assert len(payload["messages"]) == 1
                assert payload["messages"][0]["role"] == "user"
                assert len(payload["messages"][0]["content"]) == 3
            elif api == "gemini":
                assert len(payload["contents"]) == 1
                assert payload["contents"][0]["role"] == "user"
                assert len(payload["contents"][0]["parts"]) == 3


@pytest.mark.asyncio
async def test_context_project_reads_off_the_event_loop(tmp_path, monkeypatch):
    import threading

    config, persona = _make_context(tmp_path)
    main_thread = threading.get_ident()
    read_threads: list[int] = []
    with Store(config.database) as store:
        real_read = store.load_discovered_tools

        def tracked_read(scene: str):
            read_threads.append(threading.get_ident())
            return real_read(scene)

        monkeypatch.setattr(store, "load_discovered_tools", tracked_read)
        context = ChatContext(config, persona, store, platform=False, memory=None)
        context.configure_tools(build_tools(config, persona, platform=False), [], skills=())
        read_threads.clear()
        state = {"role": "user", "content": "本轮开始时间：2026-10-21T00:00:00+00:00"}
        # Even while the write connection holds an open transaction, project() finishes via the read pool.
        store.db.execute("BEGIN IMMEDIATE")
        try:
            projected = await asyncio.wait_for(context.project(None, [], state), 2)
        finally:
            store.db.commit()
        assert projected[0]["role"] == "system"
        assert "<当前关注>" in projected[-1]["content"]
        assert read_threads and all(tid != main_thread for tid in read_threads)


def _chat_config(root: Path, *, trigger: int, window: int, max_output: int = 512):
    role = root / "role"
    role.mkdir(parents=True)
    (role / "persona.yaml").write_text(json.dumps({
        "id": "synthetic", "name": "合成角色", "brief": "合成。", "behavior": "正常对话。",
        "self_reference": ["我"], "aliases": [], "tools": "all", "skills": [], "styles": []}, ensure_ascii=False))
    for name, body in [("voice.md", "简短。"), ("boundaries.md", "合成。"), ("examples.yaml", "[]\n")]:
        (role / name).write_text(body, encoding="utf-8")
    (root / "lenbot.config.json").write_text(json.dumps({
        "compaction": {"input_tokens": trigger, "keep_recent_tokens": 50, "max_output_tokens": max_output},
        "mode": "isolated", "scene": SCENE, "bot_id": "onebot:90001",
        "owners": ["onebot:70001"], "timezone": "UTC", "database": "state.sqlite3", "persona": str(role),
        "voice_mode": "direct", "max_steps": 3,
        "models": {
            "providers": {"synthetic": {"api": "openai-chat", "base_url": "http://127.0.0.1:9/v1",
                                        "api_key": "synthetic-unused-key"}},
            "roles": {"mind": {"provider": "synthetic", "model": "synthetic-mind",
                               "context_window_tokens": window, "max_output_tokens": max_output}},
        },
    }, ensure_ascii=False), encoding="utf-8")
    return load_config(root), load_persona(role)


@pytest.mark.asyncio
async def test_recap_transient_failure_enters_300s_cooldown_and_hard_overflow_still_raises(tmp_path):
    now = [START]
    config, persona = _chat_config(tmp_path / "soft", trigger=6500, window=64000, max_output=512)
    recap_calls = 0

    def respond(request):
        nonlocal recap_calls
        recap_calls += 1
        return httpx.Response(502, json={"error": {"message": "bad gateway"}})

    with Store(config.database, now=lambda: now[0]) as store:
        for index in range(10):
            store.append(SCENE, {"role": "user", "content": f"聊天记录 {index}：" + ("测试内容" * 120)})
        store.append(SCENE, {"role": "user", "content": "最新一条短消息"})
        async with ChatModel(config.model_settings("mind")) as mind:
            await mind._client.aclose()
            mind._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="https://fixture.invalid/")
            chat = Chat(config, persona, store, mind, now=lambda: now[0])
            turn_id = store.start_turn(SCENE)

            # First failure records 300s cooldown and continues uncompacted while fitting in window.
            prepared1 = await chat.prepare_context(turn_id, observed_at=now[0])
            assert prepared1.messages and recap_calls == 1
            assert chat._recap_cooldown_until == START + 300.0
            assert chat.turn_model_failure is None

            # Within 300s cooldown, automatic recap is skipped completely.
            now[0] += 120.0
            prepared2 = await chat.prepare_context(turn_id, observed_at=now[0])
            assert prepared2.messages and recap_calls == 1

            # After 300s cooldown expires, automatic recap is attempted again.
            now[0] = START + 301.0
            prepared3 = await chat.prepare_context(turn_id, observed_at=now[0])
            assert prepared3.messages and recap_calls == 2
            assert chat._recap_cooldown_until == START + 601.0

    # When the uncompacted request reaches the context window hard limit, failure is NOT swallowed.
    hard_config, hard_persona = _chat_config(tmp_path / "hard", trigger=6500, window=8500, max_output=512)
    with Store(hard_config.database, now=lambda: now[0]) as store:
        for index in range(10):
            store.append(SCENE, {"role": "user", "content": f"超窗记录 {index}：" + ("长文本内容" * 120)})
        store.append(SCENE, {"role": "user", "content": "最新一条短消息"})
        async with ChatModel(hard_config.model_settings("mind")) as mind:
            await mind._client.aclose()
            mind._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="https://fixture.invalid/")
            chat = Chat(hard_config, hard_persona, store, mind, now=lambda: now[0])
            turn_id = store.start_turn(SCENE)
            with pytest.raises(ModelHTTPError):
                await chat.prepare_context(turn_id, observed_at=now[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("recap_body", "hard_error"),
    [
        (
            {"choices": [{"message": {"role": "assistant", "content": "   ", "tool_calls": None}, "finish_reason": "stop"}]},
            ValueError,
        ),
        (
            {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": None}, "finish_reason": "content_filter"}]},
            ModelProtocolError,
        ),
        (
            {"choices": []},
            ModelProtocolError,
        ),
    ],
    ids=["empty-text", "content-filter", "empty-choices"],
)
async def test_recap_empty_or_protocol_failure_enters_cooldown_and_mind_still_replies(tmp_path, recap_body, hard_error):
    now = [START]
    config, persona = _chat_config(tmp_path / "soft", trigger=8000, window=64000, max_output=512)
    config.attention.direct_idle_seconds = 0
    config.attention.focus_seconds = 0
    sent: list[str] = []
    requests: list = []
    replies = [
        (200, "application/json", json.dumps(recap_body).encode()),
        tool_response("say", {"content": "压缩失败也不影响回复", "end_turn": True}, "say1"),
    ]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers["synthetic"].base_url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
        with Store(config.database, now=lambda: now[0]) as store:
            for index in range(10):
                store.append(SCENE, {"role": "user", "content": f"聊天记录 {index}：" + ("测试内容" * 120)})

            async def send_message(part, *, image_bytes=None):
                sent.append("".join(seg.data["text"] for seg in part.segments if seg.type == "text"))
                return SendResult(status="sent", platform_message_id=f"sent-{len(sent)}", error=None)

            async with ChatModel(config.model_settings("mind")) as mind:
                chat = Chat(config, persona, store, mind, send_message=send_message, now=lambda: now[0])
                events: list[dict] = []
                runner = SceneRunner(chat, events.append)
                runner.closing = True
                runner.receive(onebot_message(70001, 100, "在吗", direct=True))
                await asyncio.wait_for(runner.run(), 5)

                assert chat._recap_cooldown_until == START + 300.0
                assert chat.turn_model_failure is None

            assert sent == ["压缩失败也不影响回复"]
            assert len(requests) == 2
            turns = [event for event in events if "turn_id" in event]
            assert len(turns) == 1 and turns[0]["status"] == "settled" and turns[0]["failed_tools"] == 0

    hard_config, hard_persona = _chat_config(tmp_path / "hard", trigger=6500, window=8500, max_output=512)
    with Store(hard_config.database, now=lambda: now[0]) as store:
        for index in range(10):
            store.append(SCENE, {"role": "user", "content": f"超窗记录 {index}：" + ("长文本内容" * 120)})
        store.append(SCENE, {"role": "user", "content": "最新一条短消息"})
        async with ChatModel(hard_config.model_settings("mind")) as mind:
            await mind._client.aclose()
            mind._client = httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=recap_body)),
                base_url="https://fixture.invalid/",
            )
            chat = Chat(hard_config, hard_persona, store, mind, now=lambda: now[0])
            turn_id = store.start_turn(SCENE)
            with pytest.raises(hard_error):
                await chat.prepare_context(turn_id, observed_at=now[0])


@pytest.mark.asyncio
async def test_non_direct_multipart_send_interrupts_on_new_direct_message(tmp_path):
    config, persona = _chat_config(tmp_path, trigger=20000, window=64000)
    config.text_delivery.max_chars = 7
    config.text_delivery.min_interval_seconds = 0.05
    config.text_delivery.max_interval_seconds = 0.05
    config.attention.direct_idle_seconds = 0
    config.attention.focus_seconds = 0
    config.permissions.blacklist = ["onebot:70005"]

    sent_parts: list[str] = []
    requests: list = []
    replies = [
        tool_response("say", {"content": "第一段旧话题。第二段旧话题。", "end_turn": True}, "old1"),
        tool_response("say", {"content": "收到直接提问", "end_turn": True}, "new1"),
    ]
    now = [START]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers["synthetic"].base_url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
        with Store(config.database, now=lambda: now[0]) as store:
            runner_holder: list[SceneRunner] = []

            async def send_message(part, *, image_bytes=None):
                text = "".join(seg.data["text"] for seg in part.segments if seg.type == "text")
                sent_parts.append(text)
                if len(sent_parts) == 1:
                    # Blacklisted @Bot must not interrupt; real member @Bot interrupts before part 2.
                    runner_holder[0].receive(onebot_message(70005, 901, "黑名单打断", direct=True))
                    runner_holder[0].receive(onebot_message(70002, 902, "先问你个事", direct=True))
                return SendResult(status="sent", platform_message_id=f"sent-{len(sent_parts)}", error=None)

            async with ChatModel(config.model_settings("mind")) as mind:
                chat = Chat(config, persona, store, mind, send_message=send_message, now=lambda: now[0])
                events: list[dict] = []
                runner = SceneRunner(chat, events.append)
                runner_holder.append(runner)
                runner.closing = True
                runner.receive(onebot_message(70001, 100, "大家聊聊今天天气怎么样"))
                assert runner.state.pending.channel == "ambient"
                await asyncio.wait_for(runner.run(), 5)

            assert sent_parts == ["第一段旧话题。", "收到直接提问"]
            assert len(requests) == 2
            turns = [event for event in events if "turn_id" in event]
            assert len(turns) == 1 and turns[0]["status"] == "settled" and turns[0]["failed_tools"] == 0
            # Only actually sent parts are stored as own chat messages (no phantom second part).
            own_rows = store.db.execute(
                "SELECT json_extract(body,'$.send_status') FROM messages WHERE json_extract(body,'$.is_self')=1"
            ).fetchall()
            assert [row[0] for row in own_rows] == ["sent", "sent"]
            tool_entries = [entry for entry in store.entries(SCENE) if entry["role"] == "tool"]
            assert "第二段旧话题" in tool_entries[0]["content"]
            assert "余段因收到新消息未发" in tool_entries[0]["content"]


@pytest.mark.asyncio
async def test_deliver_expression_holds_before_first_part_when_causal_gate_triggers(tmp_path):
    config, persona = _make_context(tmp_path)
    config.text_delivery.max_chars = 6
    config.text_delivery.min_interval_seconds = 0
    config.text_delivery.max_interval_seconds = 0
    with Store(config.database) as store:
        sent: list[str] = []

        async def send_message(part, *, image_bytes=None):
            sent.append("".join(seg.data["text"] for seg in part.segments if seg.type == "text"))
            return SendResult(status="sent", platform_message_id=f"m-{len(sent)}", error=None)

        context = ChatContext(config, persona, store, platform=True, memory=None)
        expression = ChatExpression(config, persona, store, context=context, send_message=send_message,
                                    notify=lambda: None, on_reply_sample=None, now=store.now)
        raw_direct = onebot_message(70002, 501, "急事问你", direct=True)
        store.enqueue(parse_message(raw_direct, own_message_ids=set()), raw_direct, START)

        turn_id = store.start_turn(SCENE)
        said = await expression.express(turn_id, SayArguments(content="第一段内容。第二段内容。"))

        async def hold_always(_semantic_reply_to: str | None) -> bool:
            return True

        content, status = await expression.deliver_expression(
            "c-held", said, turn_id=turn_id, channels={"ambient"}, hold_expression=hold_always,
        )
        assert status == "held" and sent == [] and content.startswith("say 未发：")
        assert store.db.execute("SELECT COUNT(*) FROM messages WHERE json_extract(body,'$.is_self')=1").fetchone()[0] == 0

        async def hold_never(_semantic_reply_to: str | None) -> bool:
            return False

        said_allowed = await expression.express(turn_id, SayArguments(content="直接回复"))
        _, allowed_status = await expression.deliver_expression(
            "c-allowed", said_allowed, turn_id=turn_id, channels={"direct"}, hold_expression=hold_never,
        )
        assert allowed_status == "sent" and sent == ["直接回复"]


@pytest.mark.asyncio
async def test_preview_stickers_runs_sheet_rendering_in_worker_thread(tmp_path, monkeypatch):
    import threading
    from test_next_sticker_preview import _role
    from len_bot.next.chat import expression as expression_module
    from len_bot.next.chat.tools import ReactArguments

    config, persona = _role(tmp_path, 3)
    threads: list[int] = []
    real_sheet = expression_module.sticker_sheet

    def tracked(images):
        threads.append(threading.get_ident())
        return real_sheet(images)

    monkeypatch.setattr(expression_module, "sticker_sheet", tracked)
    main_thread = threading.get_ident()
    with Store(config.database) as store:
        context = ChatContext(config, persona, store, platform=False, memory=None)
        expression = ChatExpression(config, persona, store, context=context, send_message=None,
                                    notify=lambda: None, on_reply_sample=None, now=store.now)
        entries, sheet, _ = await expression.preview_stickers(ReactArguments(preview=True))
    assert len(entries) == 3 and sheet
    assert threads and threads[0] != main_thread


@pytest.mark.asyncio
async def test_unread_tool_result_is_not_folded_when_new_group_messages_arrive_same_turn(tmp_path):
    config, persona = _chat_config(tmp_path, trigger=50000, window=64000, max_output=512)
    config.compaction.keep_recent_tokens = 80
    config.max_steps = 4
    body_marker = "重要历史聊天内容明细" * 160
    requests: list = []

    with Store(config.database, now=lambda: START) as store:
        raw_msg = onebot_message(70001, 501, body_marker)
        record = store.enqueue(parse_message(raw_msg, own_message_ids=set()), raw_msg, START)
        replies = [
            tool_response("recall_chat", {"action": "read", "record": record}, "recall1"),
            tool_response("say", {"content": "已经查完历史消息", "end_turn": True}, "say1"),
        ]
        server = await peer_server(replies, requests)
        async with server:
            config.models.providers["synthetic"].base_url = (
                f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
            )
            store.append(SCENE, {"role": "user", "content": "帮我查一下刚才的历史消息"})
            async with ChatModel(config.model_settings("mind")) as mind:
                chat = Chat(config, persona, store, mind, now=lambda: START)
                appended = False

                async def append_new(_has_tools: bool, _turn_id: str) -> bool:
                    nonlocal appended
                    if not appended:
                        appended = True
                        store.append(SCENE, {"role": "user", "content": "群里突然刷屏 " * 250})
                        return True
                    return False

                async def wait_for_messages(_seconds: float) -> str:
                    return "no_messages"

                result = await chat.run_turn(
                    batch=None,
                    append_new=append_new,
                    wait_for_messages=wait_for_messages,
                    attention_state={},
                )
                assert result["status"] == "settled"
                assert chat._unseen_tool_seq is None

                # Step 2 request MUST still contain the full unread recall_chat result despite arriving user messages.
                assert len(requests) == 2
                step2_tools = [m for m in requests[1][2]["messages"] if m["role"] == "tool"]
                assert len(step2_tools) == 1
                assert body_marker in step2_tools[0]["content"]

                # After mind has read it, a subsequent projection folds the old recall_chat result normally.
                store.append(SCENE, {"role": "user", "content": "后续闲聊 " * 200})
                turn_id = store.start_turn(SCENE)
                later = await chat.prepare_context(turn_id, observed_at=START)
                later_tools = [m for m in later.messages if m["role"] == "tool" and m["tool_call_id"] == "recall1"]
                assert len(later_tools) == 1
                assert body_marker not in later_tools[0]["content"]


@pytest.mark.asyncio
async def test_prepare_context_holds_compaction_on_plan_budget_error_and_uses_continuation_for_oversized_source(tmp_path):
    from string import Template
    from len_bot.next.prompt_files import read_prompt
    from len_bot.next.storage.codec import encode

    # Case 1: Only a single entry exceeds trigger while still fitting in window -> enters compaction_held_at.
    config1, persona1 = _chat_config(tmp_path / "single", trigger=4000, window=64000, max_output=512)
    with Store(config1.database, now=lambda: START) as store:
        store.append(SCENE, {"role": "user", "content": "单条超长消息" * 1200})
        async with ChatModel(config1.model_settings("mind")) as mind:
            chat = Chat(config1, persona1, store, mind, now=lambda: START)
            turn_id = store.start_turn(SCENE)
            prepared = await chat.prepare_context(turn_id, observed_at=START)
            assert prepared.messages
            assert chat.compaction_held_at == prepared.input_tokens

    # Case 2: Old web_read raw source exceeds window_tokens, while folded chat still fits ->
    # prepare_context uses continuation_request on folded chat and commits recap cleanly.
    config2, persona2 = _chat_config(tmp_path / "cont", trigger=6500, window=14000, max_output=512)
    config2.compaction.keep_recent_tokens = 100
    huge_web = Template(read_prompt("next_web_read.md")).substitute(
        result=encode({"document": 7, "url": "https://example.invalid", "text": "超长原始网页内容" * 4000}),
    )
    requests: list = []
    recap_reply = (200, "application/json", json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "## 近期对话\n- 读过一个长网页。", "tool_calls": None},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 40},
    }, ensure_ascii=False).encode())
    server = await peer_server([recap_reply], requests)
    async with server:
        config2.models.providers["synthetic"].base_url = (
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
        )
        with Store(config2.database, now=lambda: START) as store:
            store.append(SCENE, {"role": "assistant", "content": None, "tool_calls": [
                {"id": "w1", "type": "function", "function": {"name": "web_read", "arguments": "{}"}},
            ]})
            store.append(SCENE, {"role": "tool", "tool_call_id": "w1", "content": huge_web})
            for index in range(10):
                store.append(SCENE, {"role": "user", "content": f"后续对话 {index}：" + ("继续聊聊" * 120)})
            async with ChatModel(config2.model_settings("mind")) as mind:
                chat = Chat(config2, persona2, store, mind, now=lambda: START)
                turn_id = store.start_turn(SCENE)
                prepared = await chat.prepare_context(turn_id, observed_at=START)
                assert prepared.messages
                assert len(requests) == 1
                assert store.recap(SCENE) == "## 近期对话\n- 读过一个长网页。"


@pytest.mark.asyncio
async def test_hand_over_folds_all_batches_and_unread_tool_blocks_compaction_past_it(tmp_path):
    # 1. Multi-batch hand_over folds every entry through the final seq before committing once.
    config, persona = _chat_config(tmp_path / "handover", trigger=8000, window=9500, max_output=256)
    requests: list = []
    replies = [
        (200, "application/json", json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "第一批交接摘要", "tool_calls": None},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 20},
        }, ensure_ascii=False).encode()),
        (200, "application/json", json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "完整角色交接摘要", "tool_calls": None},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 25},
        }, ensure_ascii=False).encode()),
    ]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers["synthetic"].base_url = (
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
        )
        with Store(config.database, now=lambda: START) as store:
            store.append(SCENE, {"role": "user", "content": "第一段历史讨论内容 " * 550})
            store.append(SCENE, {"role": "assistant", "content": None, "tool_calls": [
                {"id": "s1", "type": "function", "function": {"name": "say", "arguments": '{"content":"旧角色第一句"}'}},
            ]})
            store.append(SCENE, {"role": "tool", "tool_call_id": "s1", "content": '{"status":"simulated"}'})
            store.append(SCENE, {"role": "user", "content": "第二段历史讨论内容 " * 550})
            store.append(SCENE, {"role": "assistant", "content": None, "tool_calls": [
                {"id": "s2", "type": "function", "function": {"name": "say", "arguments": '{"content":"旧角色最后承诺"}'}},
            ]})
            store.append(SCENE, {"role": "tool", "tool_call_id": "s2", "content": '{"status":"simulated"}'})
            last_seq = store.active_history(SCENE)[1][-1][0]
            async with ChatModel(config.model_settings("mind")) as mind:
                chat = Chat(config, persona, store, mind, now=lambda: START)
                assert await chat.hand_over("旧角色", "新角色") == "done"
                recap, remaining = store.active_history(SCENE)
                assert len(requests) == 2
                assert remaining == []
                assert recap == "完整角色交接摘要"
                through = store.db.execute(
                    "SELECT compact_through FROM mind_sessions WHERE scene=?", (SCENE,)
                ).fetchone()[0]
                assert through == last_seq == 6

    # 2. Unread tool result is never compacted away even if a follow-up user message triggers prepare_context.
    config2, persona2 = _chat_config(tmp_path / "protect_compact", trigger=6500, window=24000, max_output=256)
    config2.compaction.keep_recent_tokens = 50
    unread_marker = "本轮刚读取尚未交给模型的网页核心正文" * 180
    with Store(config2.database, now=lambda: START) as store:
        store.append(SCENE, {"role": "user", "content": "先聊几句旧话 " * 300})
        store.append(SCENE, {"role": "assistant", "content": None, "tool_calls": [
            {"id": "s0", "type": "function", "function": {"name": "say", "arguments": '{"content":"好的"}'}},
        ]})
        store.append(SCENE, {"role": "tool", "tool_call_id": "s0", "content": '{"status":"simulated"}'})
        store.append(SCENE, {"role": "assistant", "content": None, "tool_calls": [
            {"id": "t_unread", "type": "function", "function": {"name": "web_read", "arguments": "{}"}},
        ]})
        store.append(SCENE, {"role": "tool", "tool_call_id": "t_unread", "content": unread_marker})
        tool_seq = store.active_history(SCENE)[1][-1][0]
        store.append(SCENE, {"role": "user", "content": "顺便再问一句"})
        recap_requests: list = []
        recap_ok = (200, "application/json", json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "## 早期摘要", "tool_calls": None},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 20},
        }, ensure_ascii=False).encode())
        server2 = await peer_server([recap_ok], recap_requests)
        async with server2:
            config2.models.providers["synthetic"].base_url = (
                f"http://127.0.0.1:{server2.sockets[0].getsockname()[1]}/v1"
            )
            async with ChatModel(config2.model_settings("mind")) as mind:
                chat = Chat(config2, persona2, store, mind, now=lambda: START)
                chat._unseen_tool_seq = tool_seq
                turn_id = store.start_turn(SCENE)
                prepared = await chat.prepare_context(turn_id, observed_at=START)
                tool_msgs = [m for m in prepared.messages if m["role"] == "tool" and m["tool_call_id"] == "t_unread"]
                assert len(tool_msgs) == 1
                assert unread_marker in tool_msgs[0]["content"]
