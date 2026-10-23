"""Lossless expression splitting and the actual per-part delivery report."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from uuid import uuid4

import regex

from .messages import ChatMessage, Segment, render_body
from ..persona.stickers import PersonaSticker
from ..learning.sticker_assets import CollectedSticker


@dataclass(frozen=True)
class Expression:
    message: ChatMessage
    sticker: PersonaSticker | CollectedSticker | None = None
    end_turn: bool = False


def split_expression(expression: ChatMessage, max_chars: int) -> list[ChatMessage]:
    text = "".join(segment.data["text"] for segment in expression.segments if segment.type == "text")
    clusters = regex.findall(r"\X", text)
    prefix = [segment for segment in expression.segments if segment.type != "text"]
    parts = []
    start = 0
    while start < len(clusters):
        end = min(start + max_chars, len(clusters))
        if end < len(clusters):
            latter_half = range(end - 1, start + (max_chars - 1) // 2 - 1, -1)
            newline = next((i + 1 for i in latter_half if "\n" in clusters[i]), None)
            sentence = next((i + 1 for i in latter_half if clusters[i][0] in ".。！？!?；;"), None)
            if newline is not None:
                end = newline
            elif sentence is not None:
                end = sentence
        parts.append(replace(
            expression, id=expression.id if not parts else str(uuid4()),
            segments=(prefix if not parts else []) + [Segment("text", {"text": "".join(clusters[start:end])})],
            reply_to=expression.reply_to if not parts else None,
        ))
        start = end
    return parts


def report_parts(parts: list[ChatMessage], errors: list[str | None],
                 render: Callable[[ChatMessage], str]) -> str:
    lines = [render(part) + ("" if error is None else "\n" + error)
             for part, error in zip(parts, errors)]
    if len(errors) < len(parts):
        remaining = "\n".join(
            ("" if part.reply_to is None else f"（回复平台消息 {part.reply_to}）") + render_body(part.segments)
            for part in parts[len(errors):])
        lines.append("本次剩余待发送内容：\n" + remaining)
    if any(part.send_status == "unconfirmed" for part in parts[:len(errors)]):
        lines.append("平台没有返回回执，消息可能已经发出。")
    return "\n".join(lines)


def part_length(part: ChatMessage) -> int:
    return sum(len(regex.findall(r"\X", segment.data["text"]))
               for segment in part.segments if segment.type == "text")
