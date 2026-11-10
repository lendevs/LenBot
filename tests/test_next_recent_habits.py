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


def test_pictures_with_text_and_mixed_endings_are_left_to_the_persona():
    endings = ["！", "~", "。", "", "？", "…", "！！", "~"]
    lines = [line + ending for line, ending in zip(VARIED, endings, strict=True)]
    assert recent_habits(_history(*(_say(line, f"{index}.webp") for index, line in enumerate(lines)))) is None


# Fictional lines, each sharing one sentence shape in half of the last eight and varied otherwise.
SHAPES = {
    "ending": (["今天吃面=v=", "那我先走了=v=", "被发现了=v=", "也不是不行=v="], "4 条结尾都是「=v=」"),
    "opening": (["好家伙这么快", "好家伙你也在", "好家伙又是你", "好家伙原来如此"], "4 条开头都是「好家伙」"),
    "closing": (["下雨了，记得带伞", "要出门吗，记得锁门", "今天好冷，记得穿厚点", "考完了，记得对答案"],
                "4 条最后一句都用「记得」起头"),
    "template": (["我一边吃面一边看你们吵", "一边听歌一边写作业", "他一边跑一边喊", "就一边追剧一边叠衣服"],
                 "4 条用了「一边……一边」这样的句式"),
    "association": (["突然想起来这雨像泼水一样", "突然想起来他跑得像风一样", "突然想起来这面硬得像砖一样",
                     "突然想起来你说话像念经一样"], "4 条开头都是「突然想起来」，4 条用了「像……一样」这样的句式"),
}
PLAIN = ["好的", "收到", "明天见", "那家店关门了"]


@pytest.mark.parametrize("name", SHAPES)
def test_a_shape_in_half_of_the_lines_is_named(name):
    lines, expected = SHAPES[name]
    text = recent_habits(_history(*(_say(line) for line in [*lines, *PLAIN])))
    assert text is not None and expected in text


@pytest.mark.parametrize("name", SHAPES)
def test_a_shape_in_fewer_than_half_is_not(name):
    lines, _ = SHAPES[name]
    assert recent_habits(_history(*(_say(line) for line in [*lines[:3], *PLAIN, "随便吧"]))) is None


def test_a_fixed_phrase_is_not_split_into_a_template():
    lines = ["快去吃饭", "快去吃饭吧", "那就快去吃饭", "饿了就快去吃饭", "你们聊", "我看看", "那个呢", "明天"]
    assert recent_habits(_history(*(_say(line) for line in lines))) is None


def test_template_words_others_are_using_belong_to_the_topic():
    lines, _ = SHAPES["template"]
    history = _history(*(_say(line) for line in [*lines, *PLAIN]))
    assert recent_habits(history, ["我一边上课一边摸鱼"]) is None


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
