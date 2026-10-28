"""The reminder naming phrasing the mind keeps repeating in its own latest expressions."""

import json

import pytest

from len_bot.next.chat.context import ChatContext, recent_habits
from len_bot.next.chat.tools import build_tools
from len_bot.next.persona.profile import load_persona
from len_bot.next.storage.store import Store


def _call(name: str, arguments: dict) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": f"{name}-1", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}


def _say(content: str, sticker: str | None = None) -> dict:
    arguments = {"content": content, "end_turn": True}
    if sticker is not None:
        arguments["sticker"] = {"file": sticker}
    return _call("say", arguments)


def _history(*messages: dict) -> list[tuple[int, dict]]:
    return list(enumerate(messages, start=1))


LOCKED = ["草，这也能抽歪是吧！", "直接全选C是吧草！", "草，什么冠军粉是吧！", "又抽到群友了草！",
          "八十抽才出是吧草！", "草，原来是同名装不上！", "这都能拿错是吧草！", "草，偏科偏到外太空了！"]
VARIED = ["好香", "什么歌", "我也去听听", "被你发现了", "那就待着呗", "窗边那个影子好好看", "拆了告诉我好不好吃",
          "这概率确实离谱"]


def test_repeated_words_and_sticker_are_named():
    text = recent_habits(_history(*(_say(line, "laugh.webp") for line in LOCKED)))
    assert "最近 8 次发言里" in text
    for part in ("8 条用了「草」", "同一张图用了 8 次"):
        assert part in text
    assert "感叹号" not in text and "配了表情图" not in text


def test_varied_short_lines_need_no_reminder():
    assert recent_habits(_history(*(_say(line) for line in VARIED))) is None


def test_common_sentence_particles_are_not_habits():
    lines = ["今天去不去吧", "那就这样吧呢", "你说呢啊", "好呀晚点吧", "真的假的啦", "也行嘛哦", "走啊", "来吧"]
    assert recent_habits(_history(*(_say(line) for line in lines))) is None
    text = recent_habits(_history(*(_say(line + "喵") for line in lines)))
    assert "8 条用了「喵」" in text and "「吧」" not in text


def test_punctuation_and_pictures_with_text_are_left_to_the_persona():
    lines = [line + "！~" for line in VARIED]
    assert recent_habits(_history(*(_say(line, f"{index}.webp") for index, line in enumerate(lines)))) is None


def test_only_the_latest_expressions_count():
    history = [_say(line, "laugh.webp") for line in LOCKED] + [_say(line) for line in VARIED]
    assert recent_habits(_history(*history)) is None
    assert recent_habits(_history(*[_say(line, "laugh.webp") for line in LOCKED[:4]])) is None


def test_words_others_are_using_belong_to_the_topic():
    lines = ["火锅底料选哪家", "火锅还是要牛油的", "火锅配冰粉最好", "那家火锅排队好久", "火锅吃完想喝奶茶"]
    history = _history(*(_say(line) for line in lines))
    assert "5 条用了「火锅」" in recent_habits(history)
    assert recent_habits(history, ["今晚吃火锅吗"]) is None


def test_the_same_picture_counts_across_say_and_react():
    history = _history(*(_call("react", {"file": "smirk.webp", "end_turn": True}) for _ in range(3)),
                       _say("好家伙", "smirk.webp"), _say("这也行"), _say("我也想要"))
    text = recent_habits(history)
    assert "最近 6 次发言里" in text and "同一张图用了 4 次" in text


@pytest.mark.asyncio
async def test_project_appends_the_reminder_to_the_turn_state(tmp_path):
    from test_next_persona_permissions import _config, _package
    package = _package(tmp_path, "plain", tools=["say"], documents={})
    config = _config(tmp_path / "instance", package)
    persona = load_persona(package)
    with Store(config.database) as store:
        context = ChatContext(config, persona, store, platform=False, memory=None)
        context.configure_tools(build_tools(config, persona, platform=False), [], skills=())
        state = {"role": "user", "content": "本轮开始时间：2026-10-21T00:00:00+00:00"}
        locked = await context.project(None, _history(*(_say(line) for line in LOCKED)), state)
        varied = await context.project(None, _history(*(_say(line) for line in VARIED)), state)
    assert "<最近的说法>" in locked[-1]["content"] and "8 条用了「草」" in locked[-1]["content"]
    assert "<最近的说法>" not in varied[-1]["content"]
