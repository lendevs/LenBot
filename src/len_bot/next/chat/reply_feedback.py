"""How members actually reacted to the bot's own recent lines here, as the turn's reference.

Only facts from judged reply effects: the line, the judged reaction and the judge's one-line reason. Whether the
next line should change is left to the model and the persona.
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
NOT_TAKEN = {"unrelated": "没人接这句", "negative": "被嫌弃", "correct": "被纠正"}


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def reply_feedback(config: LabConfig, store: Store) -> str | None:
    """The newest judged lines here, picked-up ones first; None when reply effects are off or nothing is judged."""
    if config.learning is None or not config.learning.reply_effects:
        return None
    rows = ReplyEffectStore(store).judged_lines(
        config.scene, [*TAKEN, *NOT_TAKEN], store.now() - WINDOW_SECONDS, MAX_LINES)
    groups: dict[str, list[str]] = {"taken": [], "not_taken": []}
    for row in rows:
        message = store.read_message(config.scene, row["seq"])
        if message is None:
            continue  # Removed by retention since it was judged.
        line = _clip(plain_text(message), LINE_CHARS) or "（只发了表情）"
        label = TAKEN.get(row["reaction"]) or NOT_TAKEN[row["reaction"]]
        reason = _clip(row["reason"] or "", REASON_CHARS)
        groups["taken" if row["reaction"] in TAKEN else "not_taken"].append(
            f"- 「{line}」{label}" + (f"：{reason}" if reason else ""))
    if not groups["taken"] and not groups["not_taken"]:
        return None
    return Template(read_prompt("next_reply_feedback.md")).substitute(
        taken="\n".join(groups["taken"]) or "- 最近没有", not_taken="\n".join(groups["not_taken"]) or "- 最近没有")
