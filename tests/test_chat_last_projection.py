import json
from string import Template

import pytest

from len_bot.next.chat.context import ChatContext, turn_state
from len_bot.next.chat.recap import estimate_text_request, recap_source
from len_bot.next.chat.tools import build_tools
from len_bot.next.models.client import ChatModel, ModelSettings
from len_bot.next.models.protocols import build_request
from len_bot.next.models.request import request_estimate
from len_bot.next.persona.profile import load_persona
from len_bot.next.prompt_files import bundled, check
from len_bot.next.storage.store import Store, encode
from test_next_persona_permissions import _config, _package


def user(content):
    return {"role": "user", "content": content}


@pytest.fixture
def context(tmp_path):
    package = _package(tmp_path, "plain", tools=[], documents={})
    config = _config(tmp_path / "instance", package)
    persona = load_persona(package)
    with Store(config.database) as store:
        chat = ChatContext(config, persona, store, platform=False, memory=None)
        chat.configure_tools(build_tools(config, persona, platform=False), [], skills=())
        yield chat


@pytest.mark.asyncio
async def test_chat_last_projects_settled_history_snapshot_and_current_in_order(context):
    freshness = "\n<话题新鲜度>\n两分钟前开始的话题。\n</话题新鲜度>\n"
    missing_close = user("这条记录还开着\n<话题新鲜度>\n正文")
    old = user("上一轮的群消息" + freshness)
    new = user("这一轮的群消息" + freshness)
    entries = [(3, missing_close), (4, old), (5, new)]
    state = turn_state(context.config, context.store, now=context.store.now())
    parts = await context.project_parts(None, entries, state, turn_floor_seq=4)

    assert parts.history == [missing_close, user("上一轮的群消息")]
    assert parts.current == [new]
    assert parts.snapshot["content"].startswith(state["content"])
    assert parts.snapshot_index == 3
    assert parts.messages() == [parts.system, *parts.history, parts.snapshot, new]
    assert await context.project(None, entries, state, turn_floor_seq=4) == parts.messages()
    assert entries[1][1]["content"] == "上一轮的群消息" + freshness

    all_history = await context.project_parts(None, entries, state)
    assert all_history.history == [*parts.history, user("这一轮的群消息")]
    assert all_history.current == []


def test_chat_and_recap_compact_only_complete_say_receipts(context):
    body = "第一段台词含有状态=failed\n第二段台词提到了余段因收到新消息未发"
    sent = (
        'onebot:group:80001｜2026-11-26｜UTC +0000\n12:30:02 "我"(onebot:90001) [id="41"，状态=sent]\n'
        '  第一段台词含有状态=failed\nonebot:group:80001｜2026-11-26｜UTC +0000\n'
        '12:30:03 "我"(onebot:90001) [id="42"，状态=sent]\n  第二段台词提到了余段因收到新消息未发'
    )
    simulated = (
        '模拟表达：onebot:group:80001｜2026-11-26｜UTC +0000\n'
        '12:30:04 "我"(onebot:90001) [id="simulated:43"，状态=simulated]\n  第一段台词'
    )
    sent_summary = encode({"status": "sent", "parts": 2, "message_ids": ["41", "42"],
                           "times": ["12:30:02", "12:30:03"]})
    simulated_summary = encode({"status": "simulated", "parts": 1, "message_ids": ["simulated:43"],
                                "times": ["12:30:04"]})
    react = '12:30:01 "我"(onebot:90001) [id="40"，状态=sent]\n  [表情]'
    partial = sent + "\n本次剩余待发送内容：\n还剩一段"
    held = sent + "\n共 3 段，第 1..2 段已发出；余段因收到新消息未发：\n还剩一段"
    failed_without_id = '12:30:05 "我"(onebot:90001) [状态=failed]\n  发言台词\n平台发送失败'
    preserved = [
        partial, held, failed_without_id, sent.replace("状态=sent", "状态=failed"),
        sent.replace("状态=sent", "状态=unconfirmed"), "say 失败：发送异常", "say 中断：新消息", "say 未发：已停机",
    ]
    entries = []
    originals = [sent, simulated, react, *preserved]
    for index, receipt in enumerate(originals):
        call_id = f"call-{index}"
        is_react = receipt == react
        tool = {"name": "react" if is_react else "say",
                "arguments": encode({"emotion": "开心"} if is_react else {"content": body})}
        entries.extend([
            (2 * index, {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": call_id, "function": tool}]}),
            (2 * index + 1, {"role": "tool", "tool_call_id": call_id, "content": receipt}),
        ])

    projected = [message for _, message in context.project_entries(entries)]
    transcript = json.loads(recap_source(None, entries))["新增旧会话"]
    for messages in (projected, transcript):
        receipts = [message["content"] for message in messages if message["role"] == "tool"]
        assert receipts == [sent_summary, simulated_summary, react, *preserved]
    assert json.loads(projected[0]["tool_calls"][0]["function"]["arguments"])["content"] == body
    assert json.loads(transcript[0]["tool_calls"][0]["arguments"])["content"] == body
    assert [message["content"] for _, message in entries if message["role"] == "tool"] == originals


@pytest.mark.asyncio
async def test_usage_anchor_follows_shared_chat_last_history(context):
    config, store = context.config, context.store
    system = {"role": "system", "content": "角色设定"}
    settled = user("已经结束的对话")
    prior = [system, settled, user("<当前场景状态与参考>\n上一轮"),
             user("上一轮新消息"), {"role": "assistant", "content": "上一轮回复"}]
    current = [system, settled, user("<当前场景状态与参考>\n这一轮"), user("这一轮新消息")]
    tools = []
    output_tokens = 32
    async with ChatModel(config.model_settings("mind")) as model:
        call_id = store.start_scene_call(config.scene, "mind", {
            "provider": config.models.roles.mind.provider,
            "settings": model.settings.model_dump(exclude={"api_key"}),
            "history_policy": config.models.roles.mind.history_policy,
            "messages": prior, "tools": tools,
        })
        store.end_call(call_id, None, {"prompt_tokens": 1000}, model=("synthetic", "fixture"))
        expected = 1000 + estimate_text_request(current, tools, output_tokens) - estimate_text_request(prior, tools, 0)
        assert request_estimate(config, store, model, scene=config.scene, role="mind",
                                messages=current, tools=tools, output_tokens=output_tokens) == (expected, "usage_assisted")
        changed_system = [{"role": "system", "content": "另一套角色设定"}, *current[1:]]
        assert request_estimate(config, store, model, scene=config.scene, role="mind", messages=changed_system,
                                tools=tools, output_tokens=output_tokens)[1] == "utf8_bytes_estimate"


@pytest.mark.parametrize("history_message_count", [None, 2])
def test_anthropic_breakpoint_targets_last_settled_block_in_merged_user_content(history_message_count):
    settings = ModelSettings(api="anthropic", base_url="http://127.0.0.1/v1", api_key="fixture", model="fixture")
    snapshot = ("<当前场景状态与参考>\n本轮状态" if history_message_count is None else "本轮状态")
    messages = [
        {"role": "system", "content": "角色设定"},
        user("历史第一段"),
        user([{"type": "text", "text": "历史最后一段"}, {"type": "text", "text": "  "}]),
        user(snapshot),
        user("这一轮刚收到的话"),
    ]
    tools = [{"type": "function", "function": {"name": "end_turn", "parameters": {"type": "object"}}}]

    _, payload = build_request(settings, messages, tools, history_message_count=history_message_count)

    control = {"type": "ephemeral"}
    assert payload["system"][-1]["cache_control"] == control
    assert payload["tools"][-1]["cache_control"] == control
    assert payload["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "历史第一段"},
        {"type": "text", "text": "历史最后一段", "cache_control": control},
        {"type": "text", "text": "  "},
        {"type": "text", "text": snapshot},
        {"type": "text", "text": "这一轮刚收到的话"},
    ]}]


def test_next_mind_keeps_the_template_placeholders():
    name = "next_mind.md"
    prompt = bundled(name)
    check(name, prompt)
    assert Template(prompt).get_identifiers() == [
        "name", "scene", "bot_id", "character", "response_choice", "expression_principles", "outlet",
    ]
