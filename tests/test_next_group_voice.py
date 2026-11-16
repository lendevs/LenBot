"""How members of a group write, measured at the upkeep fork and given to later turns as reference."""

import pytest

from len_bot.next.chat.context import ChatContext
from len_bot.next.chat.session import Chat
from len_bot.next.chat.tools import build_tools
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store

from test_next_persona_permissions import _config, _package

# Synthetic short chat: members mostly send a few characters, some pictures, often two in a row.
SHORT = ["笑死", "真的假的", "我也想去", "绷不住了", "来了来了", "？", "好耶", "什么情况", "冲", "离谱"]


def _event(text: str | None, user: int, message_id: int, at: float) -> dict:
    segments = ([{'type': 'text', 'data': {'text': text}}] if text is not None else
                [{'type': 'image', 'data': {'url': 'https://example.invalid/a.png', 'file': 'a.png'}}])
    return {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
            'user_id': user, 'message_id': message_id, 'time': at,
            'sender': {'nickname': f'成员{user}', 'role': 'member'}, 'message': segments}


def _fill(store: Store, *, bot_lines: int = 0) -> None:
    at, message_id = 1790000000.0, 1
    for round_ in range(4):
        for index, text in enumerate(SHORT):
            user = 70001 + index % 3
            for item in ([text] if index % 4 else [text, None]):
                raw = _event(item, user, message_id, at)
                store.enqueue(parse_message(raw, own_message_ids=set()), raw, at)
                at, message_id = at + 5, message_id + 1
    # Lines from this bot are not members' and are not measured.
    for _ in range(bot_lines):
        raw = _event("这是一条很长很长的、由机器人自己发出的说明文字，不应该算进群友的长度里。", 90001, message_id, at)
        store.enqueue(parse_message(raw, own_message_ids={str(message_id)}), raw, at)
        at, message_id = at + 5, message_id + 1


async def _forked(tmp_path, fill):
    package = _package(tmp_path, "plain", tools=["say"], documents={})
    config = _config(tmp_path / "instance", package)
    persona = load_persona(package)
    with Store(config.database) as store:
        fill(store)
        async with ChatModel(config.model_settings("mind")) as mind:
            chat = Chat(config, persona, store, mind)
            await chat.upkeep_fork()
            state = {"role": "user", "content": "本轮开始时间：2026-10-21T00:00:00+00:00"}
            messages = await chat.context.project(None, [], state)
    return messages[-1]["content"]


@pytest.mark.asyncio
async def test_upkeep_fork_measures_members_and_later_turns_see_it(tmp_path):
    content = await _forked(tmp_path, lambda store: _fill(store, bot_lines=20))
    assert "<本群发言形态>" in content
    voice = content.split("<本群发言形态>")[1].split("</本群发言形态>")[0]
    # 40 member texts plus 12 pictures; the bot's own long lines are not in it.
    assert "最近 52 条消息" in voice
    assert "文字消息一般 2 个字左右，九成不超过 4 个字" in voice and "只发图片的占 23%" in voice
    assert "100% 的消息只有一句" in voice
    assert "连着发" in voice and "按角色材料" in voice


@pytest.mark.asyncio
async def test_too_few_member_messages_give_no_reference(tmp_path):
    def few(store):
        for message_id, text in enumerate(SHORT, start=1):
            raw = _event(text, 70001, message_id, 1790000000.0 + message_id * 300)
            store.enqueue(parse_message(raw, own_message_ids=set()), raw, raw['time'])
    assert "<本群发言形态>" not in await _forked(tmp_path, few)


@pytest.mark.asyncio
async def test_without_an_upkeep_pass_there_is_no_reference(tmp_path):
    package = _package(tmp_path, "plain", tools=["say"], documents={})
    config = _config(tmp_path / "instance", package)
    persona = load_persona(package)
    with Store(config.database) as store:
        _fill(store)
        context = ChatContext(config, persona, store, platform=False, memory=None)
        context.configure_tools(build_tools(config, persona, platform=False), [], skills=())
        projected = await context.project(None, [], {"role": "user", "content": "本轮开始时间：2026-10-21T00:00:00+00:00"})
    assert "<本群发言形态>" not in projected[-1]["content"]
