"""What the persona material itself says not to do is repeated at the end of each turn's reference."""

import json

import pytest

from len_bot.next.chat.context import ChatContext
from len_bot.next.chat.persona_avoid import avoidances
from len_bot.next.chat.tools import build_tools
from len_bot.next.persona.profile import load_persona
from len_bot.next.storage.store import Store

from test_next_persona_permissions import _config, _package

# A fictional persona: some sentences say what she does not do, others only describe her.
VOICE = """她说话直，句子短，多数不带句号。
不知道的就说不知道，不是每句都要逗人笑。
不要每句都加颜文字！
难过的时候不必硬撑，随口应一句也行。
朋友抱怨加班时，她陪着骂两句，不在结尾劝人早点休息。
- 别把同一个梗连着用三次
"""
BOUNDARIES = """有人问她住哪，她不回答具体地址。
聊到考试，她会帮着出主意。
"""


def _persona(tmp_path):
    package = _package(tmp_path, "plain", tools=["say"], documents={})
    (package / "voice.md").write_text(VOICE, encoding="utf-8")
    (package / "boundaries.md").write_text(BOUNDARIES, encoding="utf-8")
    return package, load_persona(package)


def test_only_the_persona_sentences_that_forbid_are_taken(tmp_path):
    _, persona = _persona(tmp_path)
    assert avoidances(persona) == [
        "不要每句都加颜文字！",
        "朋友抱怨加班时，她陪着骂两句，不在结尾劝人早点休息。",
        "别把同一个梗连着用三次",
        "有人问她住哪，她不回答具体地址。",
    ]


@pytest.mark.asyncio
async def test_they_close_the_turn_reference_after_the_habit_reminder(tmp_path):
    package, persona = _persona(tmp_path)
    config = _config(tmp_path / "instance", package)
    say = {"role": "assistant", "content": None, "tool_calls": [{"id": "s", "type": "function", "function": {
        "name": "say", "arguments": json.dumps({"content": "草，又是你！", "end_turn": True}, ensure_ascii=False)}}]}
    with Store(config.database) as store:
        context = ChatContext(config, persona, store, platform=False, memory=None)
        context.configure_tools(build_tools(config, persona, platform=False), [], skills=())
        state = {"role": "user", "content": "本轮开始时间：2026-10-21T00:00:00+00:00"}
        content = (await context.project(None, list(enumerate([say] * 8, start=1)), state))[-1]["content"]
    assert content.index("<最近的说法>") < content.index("<角色材料里写明不做的>")
    assert content.rstrip().endswith("</角色材料里写明不做的>")
    block = content.split("<角色材料里写明不做的>")[1]
    assert "- 不要每句都加颜文字！" in block and "- 别把同一个梗连着用三次" in block
    assert "不知道" not in block and "出主意" not in block


@pytest.mark.asyncio
async def test_a_persona_without_prohibitions_gets_none(tmp_path):
    package = _package(tmp_path, "plain", tools=["say"], documents={})
    config = _config(tmp_path / "instance", package)
    persona = load_persona(package)
    with Store(config.database) as store:
        context = ChatContext(config, persona, store, platform=False, memory=None)
        context.configure_tools(build_tools(config, persona, platform=False), [], skills=())
        projected = await context.project(None, [], {"role": "user", "content": "本轮开始时间：2026-10-21T00:00:00+00:00"})
    assert "<角色材料里写明不做的>" not in projected[-1]["content"]
