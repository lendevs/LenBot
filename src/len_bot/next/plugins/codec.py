"""JSON shapes shared by the plugin host and an out-of-process plugin worker."""

import base64
from dataclasses import asdict

from ...plugin import Content, Image, Mention, RecallBlock, RecallRequest, Sent, Text
from ..platform.messages import ChatMessage, Notice, Segment, Sender

# Exceptions keep their type across the process boundary; anything else arrives as RuntimeError.
ERRORS = {cls.__name__: cls for cls in (PermissionError, ValueError, TypeError, RuntimeError, TimeoutError,
                                        KeyError, LookupError, NotImplementedError, FileNotFoundError)}


def error_value(error: BaseException) -> dict:
    return {"type": type(error).__name__, "message": str(error)}


def raise_error(value: dict) -> None:
    cls = ERRORS.get(value["type"])
    if cls is None:
        raise RuntimeError(f"{value['type']}: {value['message']}")
    raise cls(value["message"])


def message_value(message: ChatMessage | None) -> dict | None:
    return None if message is None else asdict(message)


def message_from(value: dict | None) -> ChatMessage | None:
    if value is None:
        return None
    return ChatMessage(**{**value, "sender": Sender(**value["sender"]),
                          "segments": [Segment(**item) for item in value["segments"]]})


def recall_value(request: RecallRequest) -> dict:
    return asdict(request)


def recall_from(value: dict) -> RecallRequest:
    return RecallRequest(**{**value, "messages": tuple(message_from(item) for item in value["messages"]),
                            "tasks": tuple(value["tasks"])})


def blocks_value(blocks: object) -> list[dict]:
    if not isinstance(blocks, (list, tuple)) or not all(isinstance(block, RecallBlock) for block in blocks):
        raise TypeError("@recall 必须返回 RecallBlock 序列")
    return [{"title": block.title, "text": block.text} for block in blocks]


def blocks_from(value: list[dict]) -> list[RecallBlock]:
    return [RecallBlock(item["title"], item["text"]) for item in value]


def notice_value(notice: Notice) -> dict:
    return {**asdict(notice), "raw": dict(notice.raw)}


def notice_from(value: dict) -> Notice:
    return Notice(**value)


def sent_value(sent: Sent) -> dict:
    return {"status": sent.status, "report": sent.report, "message_ids": list(sent.message_ids)}


def sent_from(value: dict) -> Sent:
    return Sent(value["status"], value["report"], tuple(value["message_ids"]))


def part_value(part: Content) -> dict:
    if isinstance(part, Text):
        return {"text": part.text}
    if isinstance(part, Mention):
        return {"mention": part.user}
    if isinstance(part, Image):
        return {"image": base64.b64encode(part.data).decode(), "description": part.description}
    raise TypeError(f"不支持的消息片段 {type(part).__name__}")


def part_from(value: dict) -> Content:
    if "text" in value:
        return Text(value["text"])
    if "mention" in value:
        return Mention(value["mention"])
    return Image(base64.b64decode(value["image"]), value["description"])
