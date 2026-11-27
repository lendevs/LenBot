"""How members actually reacted to the bot's own recent lines here, as the turn's reference.

Judged reply effects supply picked-up and corrected lines, plus counts of unrelated and negative reactions.
"""

from __future__ import annotations

import re
from string import Template

from ..config import LabConfig
from ..learning.reply_effect_store import ReplyEffectStore
from ..platform.messages import plain_text
from ..prompt_files import read_prompt
from ..storage.store import Store

WINDOW_SECONDS = 3 * 86400
MAX_LINES = 6
LINE_CHARS = 40
REASON_CHARS = 40
TAKEN = {"agree": "附和", "continue": "接着聊"}
SUMMARY_LABELS = {"unrelated": "无人接茬", "negative": "引起反感"}


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def reply_feedback(config: LabConfig, store: Store) -> str | None:
    """The newest judged lines here, picked-up ones first; None when reply effects are off or nothing is judged."""
    if config.learning is None or not config.learning.reply_effects:
        return None
    rows = ReplyEffectStore(store).judged_lines(
        config.scene, [*TAKEN, "correct", *SUMMARY_LABELS], store.now() - WINDOW_SECONDS, MAX_LINES)
    taken, not_taken = [], []
    summaries: dict[str, list[str]] = {reaction: [] for reaction in SUMMARY_LABELS}
    for row in rows:
        reaction = row["reaction"]
        if reaction in summaries:
            summaries[reaction].append(row["reason"] or "")
            continue
        message = store.read_message(config.scene, row["seq"])
        if message is None:
            continue  # Removed by retention since it was judged.
        line = _clip(plain_text(message), LINE_CHARS) or "（只发了表情）"
        label = TAKEN.get(reaction, "被纠正")
        reason = _clip(row["reason"] or "", REASON_CHARS)
        (taken if reaction in TAKEN else not_taken).append(
            f"- 「{line}」{label}" + (f"：{reason}" if reason else ""))
    for reaction, reasons in summaries.items():
        if reasons:
            reason = _clip(reasons[0], REASON_CHARS)
            not_taken.append(f"- 另有 {len(reasons)} 句{SUMMARY_LABELS[reaction]}"
                             + (f"（最近原因：{reason}）" if reason else ""))
    if not taken and not not_taken:
        return None
    return Template(read_prompt("next_reply_feedback.md")).substitute(
        taken="\n".join(taken) or "- 最近没有", not_taken="\n".join(not_taken) or "- 最近没有")
