"""How members of one group usually write, measured from their recent messages.

The result is reference material for the mind: the length, sentence count, picture-only share and
consecutive sends of the people it talks with. It describes the group, it does not tell the persona
how to talk; what the persona material says about its own voice comes first.
"""

from __future__ import annotations

from collections.abc import Sequence
import math
import re
from string import Template

from ..config import LabConfig
from ..platform.messages import ChatMessage, plain_text
from ..prompt_files import read_prompt
from ..storage.store import Store

# Messages read back from the scene, the members' share of them is measured.
SAMPLE_MESSAGES = 300
# Fewer member messages than this say little about how the group writes.
MIN_MESSAGES = 30
# A member's next message within this many seconds continues the same send.
BURST_GAP_SECONDS = 60
SENTENCE_BREAK = re.compile(r"[。！？!?；;…~～\n]+|\s{1,}")
WORDLIKE = re.compile(r"[\w\u4e00-\u9fff]")


def _quantile(values: Sequence[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * share) - 1)]


def _sentences(text: str) -> int:
    return sum(1 for piece in SENTENCE_BREAK.split(text) if WORDLIKE.search(piece))


def measure(messages: Sequence[ChatMessage], *, excluded: Sequence[str]) -> dict | None:
    """Shape figures for the members' messages among ``messages`` (oldest first), or None when too few.

    ``excluded`` are accounts whose messages are not members' (this bot and other bots). Messages
    from them still end a member's consecutive send.
    """
    members, runs = [], []
    previous: ChatMessage | None = None
    for message in messages:
        member = (not message.is_self and message.send_status == "received"
                  and message.sender.uid not in excluded)
        if member:
            members.append(message)
            if (previous is not None and previous.sender.uid == message.sender.uid
                    and message.time - previous.time <= BURST_GAP_SECONDS):
                runs[-1] += 1
            else:
                runs.append(1)
        previous = message if member else None
    if len(members) < MIN_MESSAGES:
        return None
    texts = [text for text in (plain_text(message).strip() for message in members) if text]
    pictures = sum(1 for message in members if not plain_text(message).strip()
                   and any(segment.type == "image" for segment in message.segments))
    lengths = [len(re.sub(r"\s", "", text)) for text in texts]
    sentences = [_sentences(text) for text in texts]
    return {
        "messages": len(members),
        "text_messages": len(texts),
        "length_median": _quantile(lengths, 0.5) if texts else None,
        "length_p90": _quantile(lengths, 0.9) if texts else None,
        "single_sentence_share": round(sum(count <= 1 for count in sentences) / len(texts), 2) if texts else None,
        "sentences_p90": _quantile(sentences, 0.9) if texts else None,
        "picture_only_share": round(pictures / len(members), 2),
        "burst_share": round(sum(1 for run in runs if run > 1) / len(runs), 2),
        "burst_p90": _quantile(runs, 0.9),
    }


def measure_scene(store: Store, config: LabConfig) -> dict | None:
    """Measure the scene's latest messages; a read-only store call."""
    return measure(store.recent(config.scene, SAMPLE_MESSAGES),
                   excluded=(config.bot_id, *config.attention.other_bot_ids))


def describe(figures: dict) -> str:
    """The figures as the turn's reference text."""
    parts = []
    if figures["length_median"] is not None:
        parts.append(f"文字消息一般 {figures['length_median']} 个字左右，九成不超过 {figures['length_p90']} 个字")
        parts.append(f"{round(figures['single_sentence_share'] * 100)}% 的消息只有一句，"
                     f"九成不超过 {figures['sentences_p90']} 句")
    parts.append(f"只发图片的占 {round(figures['picture_only_share'] * 100)}%")
    if figures["burst_share"]:
        parts.append(f"{round(figures['burst_share'] * 100)}% 的时候会一个人连着发几条，"
                     f"九成不超过 {figures['burst_p90']} 条")
    else:
        parts.append("很少有人连着发几条")
    return Template(read_prompt("next_group_voice.md")).substitute(
        count=figures["messages"], figures="；".join(parts))
