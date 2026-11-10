"""How fresh the talk is that an unprompted wake would join, stated as facts for the mind.

An ambient or attention wake can open on a batch that started minutes ago, after the group moved
on. The host does not judge topics; it states when the message that woke the turn was sent, how
much was said after it, how much of that shares words with it, and how long the chat paused, so
the model can leave an old topic alone unless it judges it worth returning to.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import re
from string import Template
from zoneinfo import ZoneInfo

from ..platform.messages import ChatMessage, plain_text
from ..prompt_files import read_prompt

# A pause at least this long between member messages is reported.
PAUSE_SECONDS = 300
HAN_RUN = re.compile(r"[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-z0-9]{2,}")


def _words(text: str) -> set[str]:
    text = text.casefold()
    words = set(WORD.findall(text))
    for run in HAN_RUN.findall(text):
        words.update(run[start:start + 2] for start in range(len(run) - 1))
    return words


def _age(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"{round(seconds)} 秒"
    if seconds < 5400:
        return f"{round(seconds / 60)} 分钟"
    return f"{seconds / 3600:.1f} 小时"


def topic_freshness(pending: Sequence[tuple[int, ChatMessage, float]], *, woke_at: float, now: float,
                    timezone: str, excluded: Sequence[str]) -> str | None:
    """Facts about the batch around the message received at ``woke_at``; None without member messages."""
    members = [(message, at) for _, message, at in pending
               if not message.is_self and message.sender.uid not in excluded]
    if not members:
        return None
    index = next((number for number, (_, at) in enumerate(members) if at >= woke_at), 0)
    trigger = members[index][0]
    after = [message for message, _ in members[index + 1:]]
    clock = datetime.fromtimestamp(trigger.time, ZoneInfo(timezone)).strftime("%H:%M:%S")
    facts = [f"叫醒你的是 {clock} 那条（{_age(now - trigger.time)}前）"]
    if after:
        shared = _words(plain_text(trigger))
        related = sum(1 for message in after if shared & _words(plain_text(message)))
        people = len({message.sender.uid for message in after})
        facts.append(f"之后又有 {len(after)} 条、{people} 个人在说，"
                     + (f"其中 {related} 条和它用到相同的字词" if related else "都没有和它相同的字词"))
        facts.append(f"最后一条在 {_age(now - after[-1].time)}前")
    else:
        facts.append("之后没有新消息")
    times = [trigger.time, *(message.time for message in after)]
    pauses = [later - earlier for earlier, later in zip(times, times[1:]) if later - earlier >= PAUSE_SECONDS]
    if pauses:
        facts.append(f"中间停过 {len(pauses)} 次，最长停了 {_age(max(pauses))}")
    return Template(read_prompt("next_topic_freshness.md")).substitute(facts="；".join(facts))
