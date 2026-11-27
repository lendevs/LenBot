"""The reminder naming phrasing the mind keeps repeating in its own latest expressions."""

import json

import pytest

from len_bot.next.chat.context import ChatContext, recent_habits
from len_bot.next.chat.tools import build_tools
from len_bot.next.persona.profile import load_persona
from len_bot.next.prompt_files import bundled
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
    for part in ("8 条用了「草」", "同一张图用了 8 次", "8 次附带了表情包"):
        assert part in text
    assert "感叹号" not in text and "结尾都是「！」" not in text


def test_varied_short_lines_need_no_reminder():
    assert recent_habits(_history(*(_say(line) for line in VARIED))) is None


def test_undelivered_say_drafts_do_not_count_as_recent_expressions():
    messages = [_say(line) for line in VARIED[:6]]
    for index, result in enumerate(("say 未发：已结束", "say 失败：工具异常", "say 中断：收到新消息")):
        call_id = f"draft-{index}"
        draft = _say("等等我也要看看", "draft.webp")
        draft["tool_calls"][0]["id"] = call_id
        messages.extend([draft, {"role": "tool", "tool_call_id": call_id, "content": result}])

    text = recent_habits(_history(*messages), has_stickers=True)
    assert "最近 6 次发言里" in text
    assert "连续 6 次都是纯文字" in text


def test_common_sentence_particles_are_not_habits():
    lines = ["今天去不去吧", "那就这样吧呢", "你说呢啊", "好呀晚点吧", "真的假的啦", "也行嘛哦", "走啊", "来吧"]
    assert recent_habits(_history(*(_say(line) for line in lines))) is None
    text = recent_habits(_history(*(_say(line + "喵") for line in lines)))
    assert "8 条用了「喵」" in text and "「吧」" not in text


@pytest.mark.parametrize("punct", ["。", "！", "？", "!", "?"])
def test_ordinary_single_sentence_punctuation_is_not_named_as_ending_habit(punct):
    lines = [line + punct for line in VARIED]
    assert recent_habits(_history(*(_say(line) for line in lines))) is None


def test_repeated_multi_char_punctuation_is_still_named():
    lines = [line + "！！" for line in VARIED[:4]] + VARIED[4:]
    text = recent_habits(_history(*(_say(line) for line in lines)))
    assert text is not None and "4 条结尾都是「！！」" in text


def test_frequent_stickers_across_recent_expressions_get_a_gentle_reminder():
    endings = ["！", "~", "。", "", "？", "…", "！！", "~"]
    lines = [line + ending for line, ending in zip(VARIED, endings, strict=True)]
    # Five out of eight with distinct stickers stays quiet.
    five = [_say(line, f"{index}.webp" if index < 5 else None) for index, line in enumerate(lines)]
    assert recent_habits(_history(*five)) is None
    # Six or more out of eight triggers a gentle reminder even when files differ.
    six = [_say(line, f"{index}.webp" if index < 6 else None) for index, line in enumerate(lines)]
    text = recent_habits(_history(*six))
    assert text is not None and "6 次附带了表情包" in text
    # Sticker preview calls do not count as sent stickers.
    with_previews = [_call("react", {"preview": True}) for _ in range(3)] + five
    assert recent_habits(_history(*with_previews)) is None
    # Six or more plain-text turns when stickers are available gently break the pure-text rut.
    plain_rut = [_say(line) for line in lines]
    assert recent_habits(_history(*plain_rut), has_stickers=False) is None
    rut_text = recent_habits(_history(*plain_rut), has_stickers=True)
    assert rut_text is not None and "连续 8 次都是纯文字、没发表情包" in rut_text
    # Having even one sticker in the window keeps it quiet.
    one_sticker = [_say(lines[0], "1.webp"), *(_say(line) for line in lines[1:])]
    assert recent_habits(_history(*one_sticker), has_stickers=True) is None


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


def test_short_question_openings_are_counted_across_different_words():
    lines = ["老婆？你出去", "  妈妈？别乱喊", "人机? 才不是", "宝宝？谁小了", "海螺？咬不动"]
    text = recent_habits(_history(*(_say(line) for line in [*lines, *VARIED[:3]])))
    assert text is not None and "5 条用「短词+问号」复读起头" in text

    text = recent_habits(_history(*(_say(line) for line in [*lines[:3], *VARIED[:5]])))
    assert "复读起头" not in (text or "")


def test_rhetorical_tails_are_counted_across_different_endings():
    lines = ["这就走了吗？", "轮到我了是吧！", "今天你值班对吧", "窗户还开着吗  ", "又忘带伞了是吧~"]
    text = recent_habits(_history(*(_say(line) for line in [*lines, *VARIED[:3]])))
    assert text is not None and "5 条都在句末反问" in text

    text = recent_habits(_history(*(_say(line) for line in [*lines[:3], *VARIED[:5]])))
    assert "都在句末反问" not in (text or "")

    declarative = ["窗户还是开着呀", "他们排练还是周五啊", "外头风还是好大呀", "今天人还是这么多啊", "这猫还是爱睡沙发呀"]
    text = recent_habits(_history(*(_say(line) for line in [*declarative, *VARIED[:3]])))
    assert "都在句末反问" not in (text or "")


@pytest.mark.parametrize("ending", ["", "。"])
def test_space_separated_clauses_are_named_when_frequent(ending):
    lines = [
        "这杯咖啡好苦 可能豆子烘深了 先加点牛奶吧",
        "确实有点晃\t大概腿没拧紧\t把扳手递给我",
        "听着像下雨了　外套还在阳台　我先去收一下",
        "那边门锁坏了 可能锁舌卡住 等师傅来看看",
        "今天队排好长 估计前面在拍照 咱先去旁边坐会",
        "这个饼真硬 估计在火上烤久了 下回点软一点的",
    ]
    lines = [line + ending for line in lines]
    text = recent_habits(_history(*(_say(line) for line in [*lines, *VARIED[:2]])))
    assert text is not None and "6 条都是空格切分的三四段式长句" in text

    text = recent_habits(_history(*(_say(line) for line in [*lines[:4], *VARIED[:4]])))
    assert "空格切分的三四段式长句" not in (text or "")


def test_anti_bagu_prompt_keeps_its_tag_and_chat_boundaries():
    prompt = bundled("next_anti_bagu.md").strip()
    assert prompt.startswith("<去鱼八股与口语表达要求>")
    assert prompt.endswith("</去鱼八股与口语表达要求>")
    assert "旁听闭嘴" in prompt and "不调 say 也不调 react" in prompt
    assert "严禁先截取对方 1 到 6 个字加问号复读起手" in prompt
