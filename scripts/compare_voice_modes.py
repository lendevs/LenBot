"""Offline A/B comparison of V1 (single-step tools) vs V3 (two-step draft + action mapping).

    uv run --no-sync python scripts/compare_voice_modes.py --instance .
    uv run --no-sync python scripts/compare_voice_modes.py --instance . --cases examples/replay/social.json --seed 42

Reads only model connection settings from ``--instance`` and structured cases from ``--cases``.
For each case, runs the identical group-chat context through V1 (single call with explicit
``say`` / ``react`` / ``end_turn`` tools) and V3 (step 1 plain-text draft or empty silence,
step 2 action mapping), records output text, latency and token usage, and writes an anonymized,
shuffled A/B blind evaluation JSON file alongside its separate answer key.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from statistics import mean
import time
from typing import Any

from len_bot.eval.cases import MessageStep, ReplayCase, load_cases
from len_bot.next.chat.context import character_material, expression_rule
from len_bot.next.chat.tools import ReactArguments, SayArguments
from len_bot.next.config import load_config, load_host_config
from len_bot.next.models.client import ChatModel, ModelReply, ModelSettings
from len_bot.next.models.tokens import token_record, token_summary
from len_bot.next.persona.profile import Persona, load_persona
from len_bot.next.platform.messages import ChatMessage, render_batch
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.prompt_files import read_prompt
from len_bot.next.tools.discovery import model_schema


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _load_model_settings(instance: Path) -> ModelSettings:
    resolved = instance.resolve()
    raw = json.loads((resolved / "lenbot.config.json").read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "scenes" in raw:
        return load_host_config(resolved).model_settings("mind")
    return load_config(resolved).model_settings("mind")


def _infer_case_target(cases_path: Path) -> tuple[str, str, str]:
    raw = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = raw.get("cases") if isinstance(raw, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{cases_path}: missing cases array")
    set_name = str(cases[0].get("set", "social"))
    for case in cases:
        for step in case.get("steps", []):
            if isinstance(step, dict) and step.get("type") == "message" and isinstance(step.get("event"), dict):
                event = step["event"]
                if "group_id" in event and "self_id" in event:
                    group_id = str(event["group_id"]).removeprefix("onebot:")
                    self_id = str(event["self_id"]).removeprefix("onebot:")
                    return set_name, f"onebot:group:{group_id}", f"onebot:{self_id}"
    return set_name, "onebot:group:80001", "onebot:90002"


def build_voice_tools(persona: Persona) -> list[dict[str, Any]]:
    say_params = SayArguments.model_json_schema()
    say_params["properties"]["content"]["description"] = read_prompt("next_direct.md").strip()
    if not persona.stickers:
        say_params["properties"].pop("sticker", None)
        say_params.pop("$defs", None)
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "say",
                "description": "在当前群里公开发言；群友看到的就是 content 内容。",
                "parameters": model_schema(say_params),
            },
        },
    ]
    if persona.stickers:
        react_params = ReactArguments.model_json_schema()
        tools.append({
            "type": "function",
            "function": {
                "name": "react",
                "description": "在当前群里单独发一张表情包图片，不带文字。",
                "parameters": model_schema(react_params),
            },
        })
    tools.append({
        "type": "function",
        "function": {
            "name": "end_turn",
            "description": "本轮选择沉默，不发言直接结束。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    })
    return tools


def render_case_context(case: ReplayCase, *, timezone_name: str) -> str:
    by_platform_id: dict[str, ChatMessage] = {}
    items: list[tuple[ChatMessage, ChatMessage | None, dict[int, str]]] = []
    for step in case.steps:
        if not isinstance(step, MessageStep):
            continue
        message = parse_message(step.event, own_message_ids=set())
        quote = None if message.reply_to is None else by_platform_id.get(message.reply_to)
        items.append((message, quote, {}))
        if message.platform_message_id is not None:
            by_platform_id[message.platform_message_id] = message
    if not items:
        return ""
    return render_batch(items, timezone=timezone_name)


def _persona_prompt_body(persona: Persona, *, scene: str, bot_id: str) -> str:
    return "\n\n".join([
        f"你是 {persona.name}，正在 {scene} 里和群友聊天。你自己的账号是 {bot_id}。",
        character_material(None, persona).strip(),
        "<response_choice>\n" + expression_rule(persona, "response_choice.md").strip() + "\n</response_choice>",
        "<expression_principles>\n" + expression_rule(persona, "expression_principles.md").strip() + "\n</expression_principles>",
        expression_rule(persona, "chat_examples.md").strip(),
    ])


def _v1_system_prompt(persona: Persona, *, scene: str, bot_id: str) -> str:
    body = _persona_prompt_body(persona, scene=scene, bot_id=bot_id)
    channel = (
        "<turn>\n"
        "- 你写的普通文字不会发到群里。需要说话时调用 say；只发表情包时调用 react；不需要回应时调用 end_turn。\n"
        "- 说话时直接调用 say，不要先在正文里复写一遍要说的话。\n"
        "</turn>"
    )
    return body + "\n\n" + channel


def _v3_draft_system_prompt(persona: Persona, *, scene: str, bot_id: str) -> str:
    body = _persona_prompt_body(persona, scene=scene, bot_id=bot_id)
    channel = (
        "<turn>\n"
        "- 直接输出你要发到群里的原话，像平时顺手打字一样自然，不要加任何说明、动作描写或引号。\n"
        "- 如果当前不需要说话（例如群友在互聊、问题已被答完或对方让你别回），直接返回空内容，什么都不要输出。\n"
        "</turn>"
    )
    return body + "\n\n" + channel


def _v3_map_system_prompt(persona: Persona, *, scene: str, bot_id: str) -> str:
    return (
        f"你是 {persona.name}（账号 {bot_id}）在 {scene} 的发言动作映射器。\n"
        "根据群聊上下文与已起草的回复原文，将其映射为一次工具调用（say、react 或 end_turn）：\n"
        "- 有文本回复时调用 say，必须完整保留草稿的措辞与语气，不要擅自润色或扩写；必要时填写 reply_to 或 sticker。\n"
        "- 若草稿为空或明确表示不发言，调用 end_turn。\n"
        "- 不要输出额外正文，仅调用工具。"
    )


def _format_sticker_selector(selector: object) -> str:
    if isinstance(selector, dict):
        for key in ("file", "query", "emotion", "candidate"):
            if selector.get(key) is not None:
                return f"{key}={selector[key]}"
    return str(selector)


def _extract_action(reply: ModelReply) -> tuple[str, str]:
    spoken: list[str] = []
    sticker_notes: list[str] = []
    for call in reply.tool_calls:
        if call.name == "say":
            content = str(call.arguments.get("content", "")).strip()
            if content:
                spoken.append(content)
            if call.arguments.get("sticker") is not None:
                sticker_notes.append(f"[表情包: {_format_sticker_selector(call.arguments['sticker'])}]")
        elif call.name == "react" and not call.arguments.get("preview"):
            sticker_notes.append(f"[表情包: {_format_sticker_selector(call.arguments)}]")
    if spoken:
        return "say", "\n".join([*spoken, *sticker_notes])
    if sticker_notes:
        return "react", "\n".join(sticker_notes)
    return "silent", ""


def _serialize_tool_calls(reply: ModelReply) -> list[dict[str, Any]]:
    return [{"name": call.name, "arguments": call.arguments} for call in reply.tool_calls]


async def run_v1(
    model: ChatModel,
    *,
    persona: Persona,
    scene: str,
    bot_id: str,
    context_text: str,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": _v1_system_prompt(persona, scene=scene, bot_id=bot_id)},
        {"role": "user", "content": context_text},
    ]
    started = time.perf_counter()
    reply = await model.complete(messages, tools)
    latency = round(time.perf_counter() - started, 3)
    action, output_text = _extract_action(reply)
    usage = token_record(reply.token_usage)
    double_write = bool(reply.text.strip()) and any(call.name == "say" for call in reply.tool_calls)
    return {
        "mode": "v1",
        "action": action,
        "output_text": output_text,
        "raw_text": reply.text,
        "double_write": double_write,
        "tool_calls": _serialize_tool_calls(reply),
        "latency_seconds": latency,
        "requests": 1,
        "tokens": token_summary([usage]),
    }


async def run_v3(
    model: ChatModel,
    *,
    persona: Persona,
    scene: str,
    bot_id: str,
    context_text: str,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    draft_messages = [
        {"role": "system", "content": _v3_draft_system_prompt(persona, scene=scene, bot_id=bot_id)},
        {"role": "user", "content": context_text},
    ]
    t1 = time.perf_counter()
    draft_reply = await model.complete(draft_messages, [])
    step1_latency = round(time.perf_counter() - t1, 3)
    step1_tokens = token_record(draft_reply.token_usage)
    draft_text = draft_reply.text.strip()

    if not draft_text:
        return {
            "mode": "v3",
            "action": "silent",
            "output_text": "",
            "draft_text": "",
            "double_write": False,
            "tool_calls": [{"name": "end_turn", "arguments": {}}],
            "latency_seconds": step1_latency,
            "step_latencies": [step1_latency, 0.0],
            "requests": 1,
            "tokens": token_summary([step1_tokens]),
        }

    map_messages = [
        {"role": "system", "content": _v3_map_system_prompt(persona, scene=scene, bot_id=bot_id)},
        {
            "role": "user",
            "content": f"<群聊上下文>\n{context_text}\n</群聊上下文>\n\n<已起草回复>\n{draft_text}\n</已起草回复>",
        },
    ]
    t2 = time.perf_counter()
    map_reply = await model.complete(map_messages, tools)
    step2_latency = round(time.perf_counter() - t2, 3)
    step2_tokens = token_record(map_reply.token_usage)
    action, output_text = _extract_action(map_reply)
    return {
        "mode": "v3",
        "action": action,
        "output_text": output_text,
        "draft_text": draft_text,
        "double_write": False,
        "tool_calls": _serialize_tool_calls(map_reply),
        "latency_seconds": round(step1_latency + step2_latency, 3),
        "step_latencies": [step1_latency, step2_latency],
        "requests": 2,
        "tokens": token_summary([step1_tokens, step2_tokens]),
    }


def _public_option(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": record["action"],
        "output_text": record["output_text"],
        "latency_seconds": record["latency_seconds"],
        "tokens": {
            "input": record["tokens"]["input"],
            "output": record["tokens"]["output"],
            "cached": record["tokens"]["cached"],
        },
    }


def build_blind_pairs(
    comparisons: list[dict[str, Any]],
    *,
    seed: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Shuffle pair order and randomly assign V1/V3 to anonymous option A/B."""
    rng = random.Random(seed)
    ordered = list(comparisons)
    rng.shuffle(ordered)
    pairs: list[dict[str, Any]] = []
    mapping: dict[str, dict[str, str]] = {}
    for index, item in enumerate(ordered, start=1):
        pair_id = f"pair-{index:02d}"
        v1_first = rng.choice([True, False])
        first = item["v1"] if v1_first else item["v3"]
        second = item["v3"] if v1_first else item["v1"]
        mapping[pair_id] = {
            "case_id": item["case_id"],
            "option_a": "v1" if v1_first else "v3",
            "option_b": "v3" if v1_first else "v1",
        }
        pairs.append({
            "pair_id": pair_id,
            "case_id": item["case_id"],
            "category": item["category"],
            "expect": item["expect"],
            "context": item["context"],
            "option_a": _public_option(first),
            "option_b": _public_option(second),
            "preference": None,
            "notes": "",
        })
    return pairs, mapping


def summarize_comparisons(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mode in ("v1", "v3"):
        records = [item[mode] for item in comparisons if item.get(mode) is not None]
        latencies = [record["latency_seconds"] for record in records]
        result[mode] = {
            "cases": len(records),
            "spoke": sum(record["action"] != "silent" for record in records),
            "double_write_calls": sum(bool(record.get("double_write")) for record in records),
            "requests": sum(record["requests"] for record in records),
            "mean_latency_seconds": round(mean(latencies), 3) if latencies else None,
            "total_latency_seconds": round(sum(latencies), 3),
            "tokens": {
                "input": sum(record["tokens"]["input"] for record in records),
                "output": sum(record["tokens"]["output"] for record in records),
                "cached": sum(record["tokens"]["cached"] for record in records),
            },
        }
    return result


async def run_comparison(
    settings: ModelSettings,
    persona: Persona,
    cases: list[ReplayCase],
    *,
    scene: str,
    bot_id: str,
    timezone_name: str,
) -> list[dict[str, Any]]:
    tools = build_voice_tools(persona)
    comparisons: list[dict[str, Any]] = []
    async with ChatModel(settings) as model:
        for case in cases:
            context_text = render_case_context(case, timezone_name=timezone_name)
            v1_result = await run_v1(
                model, persona=persona, scene=scene, bot_id=bot_id, context_text=context_text, tools=tools,
            )
            v3_result = await run_v3(
                model, persona=persona, scene=scene, bot_id=bot_id, context_text=context_text, tools=tools,
            )
            comparisons.append({
                "case_id": case.id,
                "category": None if case.social is None else case.social.category,
                "expected_speak": None if case.social is None else case.social.speak,
                "expect": case.expect,
                "context": context_text,
                "v1": v1_result,
                "v3": v3_result,
            })
    return comparisons


def main() -> None:
    checkout = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True, help="读取模型连接配置的实例目录")
    parser.add_argument(
        "--cases",
        type=Path,
        default=checkout / "examples/replay/social.json",
        help="结构化社交回放用例文件（默认 examples/replay/social.json）",
    )
    parser.add_argument(
        "--persona",
        type=Path,
        default=checkout / "examples/personas/companion",
        help="用于拼装提示词的角色目录（默认 examples/personas/companion）",
    )
    parser.add_argument("--set", dest="set_name", help="用例所属集合名（默认从用例文件推断）")
    parser.add_argument("--scene", help="用例场景标识（默认从用例事件推断）")
    parser.add_argument("--bot-id", help="用例 Bot 账号（默认从用例事件推断）")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="渲染消息时间使用的时区")
    parser.add_argument("--case-ids", nargs="*", help="仅运行指定 case id 列表")
    parser.add_argument("--limit", type=int, help="仅运行前 N 条用例")
    parser.add_argument("--seed", type=int, help="A/B 盲评打乱随机种子")
    parser.add_argument("--output", type=Path, help="输出匿名 A/B 盲评 JSON 文件路径")
    parser.add_argument("--key-output", type=Path, help="输出对照答案与原始指标 JSON 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="仅检查配置与上下文，不发起模型请求")
    options = parser.parse_args()

    cases_path = options.cases.resolve()
    inferred_set, inferred_scene, inferred_bot = _infer_case_target(cases_path)
    set_name = options.set_name or inferred_set
    scene = options.scene or inferred_scene
    bot_id = options.bot_id or inferred_bot

    settings = _load_model_settings(options.instance)
    persona = load_persona(options.persona.resolve())
    loaded = load_cases(cases_path, set_name=set_name, scene=scene, bot_id=bot_id)
    selected = list(loaded.cases)
    if options.case_ids:
        wanted = set(options.case_ids)
        selected = [case for case in selected if case.id in wanted]
        if missing := sorted(wanted - {case.id for case in selected}):
            parser.error(f"未找到指定用例：{missing}")
    if options.limit is not None:
        if options.limit <= 0:
            parser.error("--limit 必须为正整数")
        selected = selected[:options.limit]
    if not selected:
        parser.error("没有可运行的用例")

    if options.dry_run:
        preview = {
            "cases": len(selected),
            "case_ids": [case.id for case in selected],
            "persona": persona.id,
            "scene": scene,
            "bot_id": bot_id,
            "model": {"api": settings.api, "base_url": settings.base_url, "model": settings.model},
            "sample_context": render_case_context(selected[0], timezone_name=options.timezone),
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return

    comparisons = asyncio.run(run_comparison(
        settings, persona, selected, scene=scene, bot_id=bot_id, timezone_name=options.timezone,
    ))
    seed = options.seed if options.seed is not None else random.SystemRandom().randrange(1, 2**31)
    pairs, mapping = build_blind_pairs(comparisons, seed=seed)
    summary = summarize_comparisons(comparisons)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        options.output.resolve()
        if options.output is not None
        else checkout / "state/experiments" / f"voice-modes-{stamp}" / "blind_pairs.json"
    )
    key_path = (
        options.key_output.resolve()
        if options.key_output is not None
        else output_path.with_name(output_path.stem + ".key.json")
    )

    blind_document = {
        "format": "voice-mode-blind-ab-v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases_file": str(cases_path),
        "persona": persona.id,
        "model": {"api": settings.api, "model": settings.model},
        "instructions": "对比 option_a 与 option_b 在对应群聊上下文中的自然度、口语感与分寸感；在 preference 填写 A / B / tie。",
        "pairs": pairs,
    }
    key_document = {
        "format": "voice-mode-blind-ab-key-v1",
        "created_at": blind_document["created_at"],
        "seed": seed,
        "blind_file": str(output_path),
        "summary": summary,
        "mapping": mapping,
        "raw_cases": comparisons,
    }
    _write_json(output_path, blind_document)
    _write_json(key_path, key_document)
    print(json.dumps({
        "blind_pairs": str(output_path),
        "key_file": str(key_path),
        "summary": summary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
