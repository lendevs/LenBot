"""The persona material's own negated sentences are repeated at the end of each turn's reference."""

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


# Descriptions that start with 不 or 别, quoted speech and conditions, mixed with real prohibitions.
DESCRIPTIONS = """不高兴的时候她就闷头打游戏。
不但会画画，还会剪视频。
别人夸她，她会回「不要这样说啦」。
不知不觉就聊到半夜。
不同意就直说。
不得不承认她很会接梗。
不太爱发长语音。
别扭的时候爱说反话。
不一会儿又换了个话题。
她最常说『不愧是我』。
不舒服起来会少说话。
不管谁问，她都先说自己不清楚。
有人吵架时，她先听完，不急着站队，也不劝和。
讲到家里人，她避免说具体城市。
回消息禁止用全角省略号。
别在别人伤心时开玩笑。
被逗了会回「不要啦！别闹」然后笑。
被问到年龄会反问“你猜？不告诉你”。
被夸了会说「不要啦」然后偷笑。
不高兴就直接说。
她不服气就直接回嘴，不在背后嘀咕。
不聊时事，也不拿别人的成就开玩笑。
颜文字不要反复用同一种。
不叮嘱人早点睡。
不想说话时就发个表情。
她不在群友难过时开玩笑。
不会的就说不会。
她不会主动打听别人的隐私。
回群友消息，不用敬语。
"""


def _described(tmp_path):
    package = _package(tmp_path, "described", tools=["say"], documents={})
    (package / "voice.md").write_text(DESCRIPTIONS, encoding="utf-8")
    return load_persona(package)


def test_quotes_descriptions_and_conditions_are_not_taken(tmp_path):
    assert avoidances(_described(tmp_path)) == [
        "有人吵架时，她先听完，不急着站队，也不劝和。",
        "讲到家里人，她避免说具体城市。",
        "回消息禁止用全角省略号。",
        "别在别人伤心时开玩笑。",
        "她不服气就直接回嘴，不在背后嘀咕。",
        "不聊时事，也不拿别人的成就开玩笑。",
        "颜文字不要反复用同一种。",
        "不叮嘱人早点睡。",
        "她不在群友难过时开玩笑。",
        "她不会主动打听别人的隐私。",
        "回群友消息，不用敬语。",
    ]


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
    assert content.index("<最近的说法>") < content.index("<角色材料里带否定的原句>")
    assert content.rstrip().endswith("</角色材料里带否定的原句>")
    block = content.split("<角色材料里带否定的原句>")[1]
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
    assert "<角色材料里带否定的原句>" not in projected[-1]["content"]
