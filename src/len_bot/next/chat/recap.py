"""Text-context estimates and complete native tool-group compaction boundaries."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import json
from math import ceil
import re
from string import Template

from ..storage.store import encode
from ..prompt_files import read_prompt


Entry = tuple[int, dict]
_TASK_NOTICE = re.compile(r"^\[任务(执行结束|提问|操作确认)\]\s*#(\d+)(?:；请求人\s+([^；\n]+))?(?:；(.*))?$")
_DELIVERY_PART_HEADER = re.compile(r"^(\d{2}:\d{2}:\d{2}) (.*)$", re.MULTILINE)
_DELIVERY_MESSAGE_ID = re.compile(r'(?: \[|，)id=("(?:\\.|[^"\\])*")')
_DELIVERY_INCOMPLETE_STATUS = re.compile(r'(?: \[|，)状态=(?:failed|unconfirmed)(?:，|\])')
_DELIVERY_HELD_SUMMARY = re.compile(r"(?:^|\n)共 \d+ 段，第 1\.\.\d+ 段已发出；余段因收到新消息未发：\n")


class ContextBudgetError(ValueError):
    pass


def estimate_request(messages: list[dict], tools: list[dict], output_tokens: int) -> int:
    # Estimates tokens as UTF-8 bytes divided by 3.
    payload = encode({"messages": messages, "tools": tools})
    return ceil(len(payload.encode("utf-8")) / 3) + output_tokens


def estimate_content(content: str) -> int:
    """Extra JSON content bytes, excluding the empty string's two quotes."""
    return ceil((len(encode(content).encode("utf-8")) - 2) / 3)


def estimate_text_request(messages: list[dict], tools: list[dict], output_tokens: int) -> int:
    """Estimate text only; image token cost remains unknown, not base64 text length."""
    text_messages = [
        {**message, "content": [block for block in message["content"] if block["type"] != "image_url"]}
        if isinstance(message["content"], list) else message
        for message in messages
    ]
    return estimate_request(text_messages, tools, output_tokens)


def project_history(recap: str | None, entries: list[Entry]) -> list[dict]:
    messages = [] if recap is None else [{"role": "user", "content": Template(
        read_prompt("next_recap_context.md")
    ).substitute(recap=recap)}]
    return messages + [message for _, message in entries]


def expression_not_sent(name: str, content: object) -> bool:
    return isinstance(content, str) and content.startswith(
        (f"{name} 失败：", f"{name} 中断：", f"{name} 未发："))


def compact_say_receipts(entries: Iterable[Entry]) -> Iterator[Entry]:
    """Keep delivery metadata for complete say results; the tool call already contains the words."""
    pending: set[str] = set()
    for seq, message in entries:
        if message["role"] == "assistant":
            pending.update(call["id"] for call in message.get("tool_calls") or ()
                           if call["function"]["name"] == "say")
        elif message["role"] == "tool" and message["tool_call_id"] in pending:
            pending.remove(message["tool_call_id"])
            content = message["content"]
            if (isinstance(content, str) and not expression_not_sent("say", content)
                    and (headers := _DELIVERY_PART_HEADER.findall(content))
                    and not any(_DELIVERY_INCOMPLETE_STATUS.search(header) for _, header in headers)
                    and "\n本次剩余待发送内容：\n" not in content
                    and not _DELIVERY_HELD_SUMMARY.search(content)):
                message_ids = [json.loads(match[1]) for _, header in headers
                               if (match := _DELIVERY_MESSAGE_ID.search(header)) is not None]
                message = {**message, "content": encode({
                    "status": "simulated" if content.startswith("模拟表达：") else "sent",
                    "parts": len(headers),
                    "message_ids": message_ids,
                    "times": [time for time, _ in headers],
                })}
        yield seq, message


def complete_boundaries(entries: list[Entry]) -> list[int]:
    """Return cut indexes that never separate a native call from its results."""
    pending: set[str] = set()
    boundaries = []
    for index, (_, message) in enumerate(entries, 1):
        if message["role"] == "assistant":
            calls = message.get("tool_calls")
            if calls is not None:
                pending.update(call["id"] for call in calls)
        elif message["role"] == "tool":
            pending.remove(message["tool_call_id"])
        if not pending:
            boundaries.append(index)
    if pending:
        raise ContextBudgetError("当前会话存在尚未取得结果的工具组，不能压缩")
    return boundaries


@dataclass(frozen=True)
class CompactionPlan:
    """``request_messages`` is the standalone recap request; the boundary messages let a recap
    continue the chat request instead, so the provider's prefix cache covers the history."""
    through: int
    summary_budget_tokens: int
    request_messages: list[dict]
    folded_last: dict | None = None
    kept_first: dict | None = None


def plan_compaction(entries: list[Entry], *, system: dict, state: dict,
                    tools: list[dict], output_tokens: int, trigger_tokens: int,
                    keep_recent_tokens: int, summary_output_tokens: int,
                    recap: str | None, summary_template: str, window_tokens: int,
                    source_entries: list[Entry] | None = None,
                    token_scale: float = 1.0, include_latest: bool = False,
                    reasoning_reserve_tokens: int = 0,
                    allow_oversized_source: bool = False,
                    protect_from_seq: int | None = None) -> CompactionPlan:
    """``include_latest`` may fold every entry into the recap, as a role handover does."""
    summary_text_tokens = summary_output_tokens - reasoning_reserve_tokens
    if summary_text_tokens <= 0:
        raise ContextBudgetError("回想输出额度需要大于思考预留，请调大回想最大长度或调小思考额度")
    boundaries = [
        cut for cut in complete_boundaries(entries)
        if (cut < len(entries) or include_latest)
        and (protect_from_seq is None or entries[cut - 1][0] < protect_from_seq)
    ]
    if not boundaries:
        required = estimate_request([system] + project_history(recap, entries) + [state], tools, 0)
        raise ContextBudgetError(
            f"没有可压缩的旧完整对话段；当前请求输入估算 {required} token，"
            f"超过压缩阈值 {trigger_tokens}，请调大压缩阈值")
    # Start from the newest complete units, not an arbitrary message count.
    sizes = [ceil(token_scale * len(encode(message).encode('utf-8')) / 3) for _, message in entries]
    recent = 0
    preferred = len(entries)
    for index in range(len(entries) - 1, -1, -1):
        recent += sizes[index]
        if recent > keep_recent_tokens:
            break
        preferred = index
    start = min((cut for cut in boundaries if cut >= preferred), default=boundaries[-1])
    for cut in boundaries:
        if cut < start:
            continue
        kept = entries[cut:]
        without_recap = [system] + project_history("", kept) + [state]
        available = min(trigger_tokens, window_tokens - output_tokens) - ceil(
            token_scale * estimate_request(without_recap, tools, 0))
        if available >= summary_text_tokens:
            break
    else:
        raise ContextBudgetError(
            f"system、tools、参考与最新完整单位估算 {min(trigger_tokens, window_tokens - output_tokens) - available} "
            f"token，加回想正文 {summary_text_tokens} 超过压缩阈值 {trigger_tokens}，"
            "请调大压缩阈值或调小回想最大长度")

    budget = summary_text_tokens
    prompt = Template(summary_template).substitute(summary_budget_tokens=budget)

    def build_request_for(boundary: int) -> list[dict]:
        source = entries[:boundary] if source_entries is None else [
            entry for entry in source_entries if entry[0] <= entries[boundary - 1][0]]
        return [{"role": "system", "content": prompt},
                {"role": "user", "content": recap_source(recap, source)}]

    request = build_request_for(cut)
    required = estimate_request(request, [], summary_output_tokens)
    if required > window_tokens:
        for earlier in reversed([b for b in boundaries if b < cut]):
            earlier_request = build_request_for(earlier)
            if estimate_request(earlier_request, [], summary_output_tokens) <= window_tokens:
                cut, request = earlier, earlier_request
                break
        else:
            if not allow_oversized_source:
                raise ContextBudgetError(
                    f"待压缩段的回想请求估算 {required} token，超过配置窗口 {window_tokens}，"
                    "请调大窗口或调小回想最大长度")
    return CompactionPlan(entries[cut - 1][0], budget, request, entries[cut - 1][1],
                          entries[cut][1] if cut < len(entries) else None)


def continuation_request(history: list[dict], plan: CompactionPlan) -> list[dict]:
    """The chat request's system and history, then the recap rules naming the cut by its two sides."""
    instruction = Template(read_prompt("next_recap_continue.md")).substitute(
        last=_excerpt(plan.folded_last, tail=True), first=_excerpt(plan.kept_first, tail=False),
        rules=plan.request_messages[0]["content"])
    return history + [{"role": "user", "content": instruction}]


EXCERPT_CHARS = 240


def _excerpt(message: dict, *, tail: bool) -> str:
    content = message["content"]
    if isinstance(content, list):
        content = "".join(block["text"] for block in content if block["type"] == "text")
    calls = message.get("tool_calls")
    text = content or ("" if not calls else encode(
        [{"name": call["function"]["name"], "arguments": call["function"]["arguments"]} for call in calls]))
    if len(text) > EXCERPT_CHARS:
        text = "…" + text[-EXCERPT_CHARS:] if tail else text[:EXCERPT_CHARS] + "…"
    return f"[{message['role']}] {text}"


def extract_ticket_anchors(entries: list[Entry]) -> list[dict]:
    """Extract task IDs, registered delivery file IDs/names, and pending question IDs from task notices."""
    anchors: dict[int, dict] = {}
    for _, message in entries:
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            continue
        first, _, rest = message["content"].partition("\n")
        match = _TASK_NOTICE.match(first.strip())
        if match is None:
            continue
        kind, raw_id, requester, goal = match.groups()
        task_id = int(raw_id)
        payload = None
        goal_extra: list[str] = []
        for raw_line in rest.splitlines():
            candidate = raw_line.strip()
            if not candidate:
                continue
            if candidate.startswith("{"):
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        payload = parsed
                        break
                except ValueError:
                    pass
            if payload is None:
                goal_extra.append(candidate)
        anchor = anchors.setdefault(task_id, {"task_id": task_id})
        if requester:
            anchor["requester"] = requester.strip()
        if goal:
            full_goal = " ".join([goal.strip(), *goal_extra]).strip()
            anchor["goal"] = full_goal
        if kind == "执行结束":
            anchor.pop("question_id", None)
            anchor.pop("question_title", None)
            if payload is not None:
                if payload.get("status") is not None:
                    anchor["status"] = payload["status"]
                if isinstance(payload.get("can_continue"), bool):
                    anchor["can_continue"] = payload["can_continue"]
                files_raw = payload.get("files")
                if isinstance(files_raw, list):
                    existing = list(anchor.get("files") or [])
                    seen = {(item["id"], item["name"]) for item in existing}
                    for item in files_raw:
                        if isinstance(item, dict) and "id" in item and isinstance(item.get("name"), str):
                            key = (item["id"], item["name"])
                            if key not in seen:
                                seen.add(key)
                                existing.append({"id": item["id"], "name": item["name"]})
                    if existing:
                        anchor["files"] = existing
        else:
            if payload is not None:
                if isinstance(payload.get("id"), str) and payload["id"]:
                    anchor["question_id"] = payload["id"]
                if isinstance(payload.get("title"), str) and payload["title"]:
                    anchor["question_title"] = payload["title"]
    return list(anchors.values())


def recap_source(recap: str | None, entries: list[Entry]) -> str:
    """Project readable facts; opaque provider continuation fields are not facts."""
    transcript = []
    for _, message in compact_say_receipts(entries):
        item = {"role": message["role"], "content": message["content"]}
        if message["role"] == "assistant" and message.get("tool_calls") is not None:
            item["tool_calls"] = [
                {"id": call["id"], "name": call["function"]["name"],
                 "arguments": call["function"]["arguments"]}
                for call in message["tool_calls"]
            ]
        elif message["role"] == "tool":
            item["tool_call_id"] = message["tool_call_id"]
        transcript.append(item)
    payload: dict[str, object] = {"已有回想": recap, "新增旧会话": transcript}
    anchors = extract_ticket_anchors(entries)
    if anchors:
        payload["涉及工单与交付标识"] = anchors
    return encode(payload)
