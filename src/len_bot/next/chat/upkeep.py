"""Session upkeep: memory writes and learning taken from the mind's own session.

One request chain per scene continues the chat request's exact system, tools and history, so the
provider's prefix cache covers them; only the upkeep instruction and the messages missing from that
history are new input. Results land in the existing memory job and learning tables, and the calls
are recorded once, as ``upkeep`` model calls of the scene.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from string import Template
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..config import LabConfig, SceneSettings
from ..learning.expression_match import overlap
from ..learning.jargon_store import JargonStore
from ..learning.reply_effect_store import REACTIONS, ReplyEffectStore
from ..learning.store import LearningStore
from ..models.client import ChatModel, ModelReply
from ..models.request import request_model
from ..models.slots import ModelSlots
from ..platform.messages import ChatMessage, plain_text, render_text
from ..prompt_files import read_prompt
from ..work.materials import finish_file_operation
from ..runtime.logs import log_context
from ..storage.store import Store, encode

if TYPE_CHECKING:
    from ..config import SharedConfig
    from ..learning.expression_selection import ExpressionService
    from ..memory.service import MemoryService


LOG = logging.getLogger(__name__)
WAKE_INTERVAL_SECONDS = 30
# A failed or interrupted pass runs again by itself this many times in a row, this long after failing.
AUTO_RETRIES = 3
RETRY_DELAY_SECONDS = 60
# After an unexpected worker error the scene waits this long before trying again.
ERROR_BACKOFF_SECONDS = 60
EFFECT_BATCH = 10
MEANING_BATCH = 5
MAX_ITEMS = 20
PARTS = ("memory", "expressions", "jargon", "effects")
# A new expression this close to an adopted one with the same wording joins it instead.
SAME_SITUATION = 0.6
SAME_SITUATION_VECTOR = 0.9

Fork = Callable[[str], Awaitable[tuple[list[dict], list[dict]] | None]]


def _error_text(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


@dataclass
class Plan:
    rows: list[tuple[int, ChatMessage, float, str | None]] = field(default_factory=list)
    memory_after: int | None = None
    expressions_after: int | None = None
    jargon_after: int | None = None
    meanings: list[dict] = field(default_factory=list)
    effects: list[int] = field(default_factory=list)
    effect_retry: int | None = None

    @property
    def through(self) -> int | None:
        return self.rows[-1][0] if self.rows else None


@dataclass
class Begun:
    """Records opened for one pass; each is completed or failed together."""
    memory_job: dict | None = None
    batch: int | None = None
    discovery: int | None = None
    effect_call: int | None = None
    request: dict = field(default_factory=dict)


class SessionUpkeep:
    """One worker per scene with any upkeep part enabled; a failed pass waits for an explicit retry."""

    def __init__(self, config: SharedConfig, store: Store, mind: ChatModel, *,
                 memory: MemoryService | None = None, expression_service: ExpressionService | None = None,
                 slots: ModelSlots | None = None):
        self.config = config
        self.store = store
        self.mind = mind
        self.memory = memory
        self.expression_service = expression_service
        self.slots = slots
        # Set by the network runtime.
        self.fork: Fork | None = None
        self.connected_since: Callable[[], float | None] = lambda: None
        self.on_update: Callable[[], None] | None = None
        self.learning = LearningStore(store)
        self.jargon = JargonStore(store)
        self.effects = ReplyEffectStore(store)
        self.parts: dict[str, set[str]] = {part: set() for part in PARTS}
        self._wake: dict[str, asyncio.Event] = {}
        self._force: set[str] = set()
        self._retry: set[str] = set()
        self._effect_retry: dict[str, int] = {}
        self._failures: dict[str, int] = {}
        self._failed_at: dict[str, float] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self.started = False
        self.errors: dict[str, BaseException] = {}
        for scene, settings in self.scenes.items():
            if self.memory_enabled and settings.memory_plugin is not None:
                self.memory.jobs.release(scene, f"记忆改由插件 {settings.memory_plugin} 处理")
            elif self.memory_enabled:
                self.enable(scene, "memory")
            learning = settings.learning
            for part, flag in (("expressions", "extract"), ("jargon", "jargon_extract"), ("effects", "reply_effects")):
                if learning is not None and getattr(learning, flag):
                    self.enable(scene, part)

    @property
    def scenes(self) -> dict[str, SceneSettings]:
        """Live scene settings; a single-scene lab config is its own scene."""
        if isinstance(self.config, LabConfig):
            return {self.config.scene: self.config}
        return self.config.scenes

    @property
    def memory_enabled(self) -> bool:
        return self.memory is not None and self.config.memory is not None and self.config.memory.ingest is not None

    # Lifecycle

    def enable(self, scene: str, part: str) -> None:
        if part == "memory":
            self.memory.jobs.initialize(scene, self.store.max_message_seq(scene))
        elif part == "expressions":
            self.learning.initialize(scene, self.store.max_message_seq(scene))
            self.learning.recover(scene)
        elif part == "jargon":
            self.jargon.initialize(scene, self.store.max_message_seq(scene))
            self.jargon.recover(scene)
        else:
            self.effects.recover(scene)
        self.parts[part].add(scene)
        if scene not in self._wake:
            self._wake[scene] = asyncio.Event()
            if self.started:
                self._start_scene(scene)
        else:
            self._wake[scene].set()

    async def disable(self, scene: str, part: str) -> None:
        self.parts[part].discard(scene)
        if any(scene in scenes for scenes in self.parts.values()):
            return
        worker = self._workers.pop(scene, None)
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        self._wake.pop(scene, None)
        self.errors.pop(scene, None)
        self._force.discard(scene)
        self._retry.discard(scene)
        self._effect_retry.pop(scene, None)
        self._failures.pop(scene, None)
        self._failed_at.pop(scene, None)

    def _start_scene(self, scene: str) -> None:
        with log_context(scene=scene, job="session_upkeep"):
            self._workers[scene] = asyncio.create_task(self._worker(scene), name=f"session-upkeep:{scene}")

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        for scene in self._wake:
            self._start_scene(scene)

    async def close(self) -> None:
        self.started = False
        for worker in self._workers.values():
            worker.cancel()
        if self._workers:
            results = await asyncio.gather(*self._workers.values(), return_exceptions=True)
            for scene, result in zip(self._workers, results, strict=True):
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    self.errors[scene] = result
        self._workers.clear()

    def running(self, scene: str) -> bool:
        worker = self._workers.get(scene)
        return worker is not None and not worker.done()

    def _check(self, scene: str, part: str) -> None:
        if scene not in self.parts[part]:
            raise ValueError(f"{part} upkeep is not configured for scene {scene!r}")

    def wake(self, scene: str) -> None:
        if scene in self._wake:
            self._wake[scene].set()

    def request(self, scene: str, part: str) -> None:
        """Run the current range now, below the usual thresholds; a failed range needs retry."""
        self._check(scene, part)
        if self._blocked(scene):
            raise ValueError(f"上次整理失败（{scene}），请先重试")
        self._force.add(scene)
        self._wake[scene].set()

    def retry(self, scene: str, part: str, effect_call: int | None = None) -> None:
        self._check(scene, part)
        if effect_call is not None:
            self.effects.retryable(scene, effect_call)
            self._effect_retry[scene] = effect_call
        elif not self._blocked(scene):
            raise ValueError(f"{scene} 没有失败或中断的整理")
        self._retry.add(scene)
        self._wake[scene].set()

    def compacted(self, scene: str) -> None:
        """Older history just left the session: take its range now, below the usual thresholds."""
        if scene in self._wake and not self._blocked(scene):
            self._force.add(scene)
            self._wake[scene].set()

    # Planning

    def _exclude_uids(self, scene: str) -> tuple[str, ...]:
        return (self.config.bot_id, *self.scenes[scene].attention.other_bot_ids)

    def _blocked(self, scene: str) -> bool:
        if scene in self.parts["memory"]:
            latest = self.memory.jobs.latest(scene)
            if latest is not None and latest["status"] in {"failed", "interrupted", "running", "queued"}:
                return True
        if scene in self.parts["expressions"]:
            latest = self.learning.latest(scene)
            if latest is not None and latest["status"] in {"failed", "interrupted", "running"}:
                return True
        if scene in self.parts["jargon"]:
            latest = self.jargon.latest(scene)
            if latest is not None and latest["status"] in {"failed", "interrupted", "running"}:
                term = None if latest["purpose"] != "meaning" else self.jargon.item(scene, latest["term_id"])
                if latest["purpose"] == "discovery" or (term is not None and term["status"] != "rejected"):
                    return True
        if scene in self.parts["effects"]:
            latest = self.effects.latest_call(scene)
            if latest is not None and latest["status"] in {"failed", "interrupted", "running"}:
                return True
        return False

    def _plan(self, scene: str) -> Plan | None:
        retrying = scene in self._retry
        if self._blocked(scene) and not retrying:
            return None
        force = scene in self._force or retrying
        plan = Plan()
        now = self.store.now()
        afters = {}
        if scene in self.parts["memory"]:
            afters["memory"] = self.memory.jobs.after(scene)
        if scene in self.parts["expressions"]:
            afters["expressions"] = self.learning.state(scene)["after_seq"]
        if scene in self.parts["jargon"]:
            afters["jargon"] = self.jargon.state(scene)["after_seq"]
        if afters:
            start = min(afters.values())
            excluded = (self.memory.jobs.excluded_records(scene, after=start)
                        if scene in self.parts["memory"] else [])
            # Memory and learning keep their own thresholds; either one being due runs the pass.
            thresholds = []
            if "memory" in afters:
                thresholds.append(self.config.memory.ingest)
            if "expressions" in afters or "jargon" in afters:
                thresholds.append(self.scenes[scene].learning)
            batch = max(settings.batch_size for settings in thresholds)
            rows = self.store.memory_messages(scene, start, limit=batch, exclude_records=excluded)
            if rows:
                last = self.store.last_memory_input_at(scene, start, exclude_records=excluded) or rows[-1][2]
                due = force or any(
                    now - rows[0][2] >= settings.max_age_seconds
                    or (len(rows) >= settings.min_messages and now - last >= settings.idle_seconds)
                    for settings in thresholds)
                if due:
                    plan.rows = rows
                    plan.memory_after = afters.get("memory")
                    plan.expressions_after = afters.get("expressions")
                    plan.jargon_after = afters.get("jargon")
        if scene in self.parts["jargon"]:
            plan.meanings = self.jargon.pending(scene)[:MEANING_BATCH]
        if scene in self.parts["effects"]:
            retry_of = self._effect_retry.get(scene)
            if retry_of is not None:
                plan.effects, plan.effect_retry = self.effects.retryable(scene, retry_of), retry_of
            else:
                waiting = self.effects.waiting(scene)
                learning = self.scenes[scene].learning
                if waiting and (force or plan.rows or len(waiting) >= EFFECT_BATCH
                                or now - waiting[0]["closed_at"] >= learning.max_age_seconds):
                    plan.effects = [item["id"] for item in waiting[:EFFECT_BATCH]]
        if not (plan.rows or plan.meanings or plan.effects):
            self._force.discard(scene)
            self._retry.discard(scene)
            return None
        return plan

    def _close_windows(self, scene: str) -> float:
        """Freeze complete follow-up windows; return the wait until the next known deadline."""
        now = self.store.now()
        delay = float(WAKE_INTERVAL_SECONDS)
        closed = False
        for effect in self.effects.open_effects(scene):
            observed = self.effects.followups(scene, effect["first_sent_at"], effect["deadline"],
                                              exclude_uids=self._exclude_uids(scene))
            if len(observed) >= 5 or now >= effect["deadline"]:
                since = self.connected_since()
                self.effects.close(effect["id"], observed,
                                   input_gap=since is None or since > effect["first_sent_at"])
                closed = True
            else:
                delay = min(delay, max(0.0, effect["deadline"] - now))
        if closed and self.on_update is not None:
            self.on_update()
        return delay

    # Worker

    async def _worker(self, scene: str) -> None:
        """Runs until cancelled; an unexpected error is shown in the panel and retried after a pause."""
        while True:
            wake = self._wake[scene]
            wake.clear()
            try:
                delay = self._close_windows(scene) if scene in self.parts["effects"] else WAKE_INTERVAL_SECONDS
                progressed = await self._step(scene)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.errors[scene] = error
                LOG.exception("session upkeep step failed for %s", scene)
                if self.on_update is not None:
                    self.on_update()
                progressed, delay = False, ERROR_BACKOFF_SECONDS
            else:
                if self.errors.pop(scene, None) is not None and self.on_update is not None:
                    self.on_update()
            if progressed:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(wake.wait(), timeout=delay)
            except TimeoutError:
                pass

    def _auto_retry(self, scene: str) -> bool:
        """Queue a failed or interrupted pass again, a few times in a row and after a pause."""
        if (self._failures.get(scene, 0) >= AUTO_RETRIES
                or self.store.now() - self._failed_at.get(scene, 0.0) < RETRY_DELAY_SECONDS):
            return False
        if scene in self.parts["effects"]:
            latest = self.effects.latest_call(scene)
            if latest is not None and latest["status"] in {"failed", "interrupted"}:
                self._effect_retry[scene] = latest["id"]
        self._retry.add(scene)
        return True

    async def _step(self, scene: str) -> bool:
        plan = self._plan(scene)
        if plan is None and scene not in self._retry and self._blocked(scene) and self._auto_retry(scene):
            plan = self._plan(scene)
        if plan is None or self.fork is None:
            return False
        fork = await self.fork(scene)
        if fork is None:
            # The scene is in a turn; its end wakes this worker again.
            return False
        self._force.discard(scene)
        self._retry.discard(scene)
        self._effect_retry.pop(scene, None)
        await self._run(scene, plan, *fork)
        return True

    # One pass

    def _key(self, message: ChatMessage, seq: int) -> str:
        return message.platform_message_id if message.platform_message_id is not None else f"r{seq}"

    def _line(self, scene: str, seq: int, message: ChatMessage) -> dict:
        timezone = ZoneInfo(self.config.scene_timezone(scene))
        quote = None if message.reply_to is None else self.store.find_message(scene, message.reply_to)
        return {"id": self._key(message, seq), "qq": message.sender.uid,
                "name": "我" if message.is_self else message.sender.card or message.sender.nickname,
                "time": datetime.fromtimestamp(message.time, timezone).isoformat(timespec="seconds"),
                "text": render_text(message, reply=quote)}

    def _effect_sample(self, scene: str, effect: dict) -> dict:
        def lines(seqs):
            result = []
            for seq in seqs:
                message = self.store.read_message(scene, seq)
                if message is None:
                    raise ValueError(f"Reply effect {effect['id']} message {seq} is missing in {scene}")
                result.append(self._line(scene, seq, message))
            return result
        return {"entry_seq": effect["entry_seq"], "partial": effect["partial"],
                "你说的话": lines(effect["message_seqs"]),
                "之前": [self._line(scene, seq, message)
                       for seq, message in self.effects.before(scene, min(effect["message_seqs"]))],
                "之后": lines(effect["observed_seqs"])}

    def _meaning_item(self, scene: str, term: dict) -> dict:
        examples = {}
        for seq in term["sample_seqs"][-5:]:
            for row_seq, message, _ in self.jargon.context(scene, seq, self._exclude_uids(scene)):
                examples[row_seq] = self._line(scene, row_seq, message)
        return {"term": term["term"], "出现次数": term["count"], "例句": [examples[seq] for seq in sorted(examples)]}

    async def _instruction(self, scene: str, plan: Plan, history: list[dict], tools: list[dict]
                           ) -> tuple[str, dict[str, int], set[str], bool]:
        """Returns the instruction, message keys, human message keys and whether memory is in it."""
        tasks, formats = [], {}
        memory = plan.memory_after is not None and plan.rows and any(
            tool["function"]["name"] == "memory" for tool in tools)
        keys: dict[str, int] = {}
        humans: set[str] = set()
        excluded = set(self._exclude_uids(scene))
        for seq, message, _, _ in plan.rows:
            key = self._key(message, seq)
            keys[key] = seq
            if (not message.is_self and message.send_status == "received" and message.sender.uid not in excluded
                    and plain_text(message).strip()):
                humans.add(key)
        if memory:
            tree = await self.memory.backend.tree(scene)
            tasks.append(Template(read_prompt("next_upkeep_memory.md")).substitute(files=encode(tree)))
        if plan.expressions_after is not None and plan.rows:
            tasks.append(read_prompt("next_upkeep_expressions.md").strip())
            formats["expressions"] = [{"situation": "情境", "style": "说法", "sources": ["消息id"]}]
        if plan.jargon_after is not None and plan.rows:
            tasks.append(read_prompt("next_upkeep_jargon.md").strip())
            formats["terms"] = [{"term": "原话中的词", "sources": ["消息id"]}]
        if plan.meanings:
            tasks.append(Template(read_prompt("next_upkeep_meanings.md")).substitute(
                terms=encode([self._meaning_item(scene, term) for term in plan.meanings])).strip())
            formats["meanings"] = [{"term": "词", "meaning": "在这个群里的用法",
                                    "ordinary_meaning": "通常含义", "same_meaning": False, "confidence": 0.5}]
        if plan.effects:
            samples = [self._effect_sample(scene, item) for item in self.effects.effects(scene, plan.effects)]
            tasks.append(Template(read_prompt("next_upkeep_effects.md")).substitute(samples=encode(samples)).strip())
            formats["effects"] = [{"entry_seq": 1, "reaction": "agree", "reason": "一句依据"}]
        if plan.rows:
            text = "\n".join(message["content"] if isinstance(message["content"], str)
                             else "\n".join(block.get("text", "") for block in message["content"])
                             for message in history if message.get("content"))
            present = [key for key, seq in keys.items()
                       if not key.startswith("r") and f"id={json.dumps(key, ensure_ascii=False)}" in text]
            missing = [self._line(scene, seq, message) for seq, message, _, _ in plan.rows
                       if self._key(message, seq) not in present]
            parts = []
            if present:
                parts.append("整理范围包括上面对话里 id 为 " + "、".join(present) + " 的消息。")
            if missing:
                parts.append("下面这些消息也在整理范围里，它们不在上面的对话中：\n" + encode(missing))
            messages = "\n".join(parts)
        else:
            messages = ""
        timezone = ZoneInfo(self.config.scene_timezone(scene))
        instruction = Template(read_prompt("next_upkeep.md")).substitute(
            now=datetime.fromtimestamp(self.store.now(), timezone).isoformat(timespec="minutes"), scene=scene,
            tasks="\n\n".join(tasks), messages=messages, format=encode(formats))
        return instruction, keys, humans, memory

    def _begin(self, scene: str, plan: Plan, request: dict, memory: bool) -> Begun:
        begun = Begun(request=request)
        through = plan.through
        if memory:
            job = self.memory.jobs.create(scene, self.memory.settings.backend, plan.rows[0][0], through)
            job["details"].update(message_count=len(plan.rows), upkeep=True,
                                  source_personas=[{"record": seq, "message_id": message.id, "persona_id": persona}
                                                   for seq, message, _, persona in plan.rows])
            self.memory.jobs.status(job, "running")
            begun.memory_job = job
        if plan.expressions_after is not None and through is not None and through > plan.expressions_after:
            begun.batch = self.learning.begin(scene, plan.expressions_after, through, request)
        if plan.jargon_after is not None and through is not None and through > plan.jargon_after:
            begun.discovery = self.jargon.begin_discovery(scene, plan.jargon_after, through, request)
        if plan.effects:
            begun.effect_call = self.effects.begin_call(scene, plan.effects, request, retry_of=plan.effect_retry)
        return begun

    def _fail(self, begun: Begun, status: str, error: str) -> None:
        if begun.memory_job is not None and begun.memory_job["status"] == "running":
            self.memory.jobs.status(begun.memory_job, status, error)
        if begun.batch is not None:
            self.learning.fail(begun.batch, status, error)
        if begun.discovery is not None:
            self.jargon.fail(begun.discovery, status, error)
        if begun.effect_call is not None:
            self.effects.fail(begun.effect_call, status, error)

    async def _run(self, scene: str, plan: Plan, history: list[dict], tools: list[dict]) -> None:
        instruction, keys, humans, memory = await self._instruction(scene, plan, history, tools)
        if plan.memory_after is not None and plan.rows and not memory:
            raise ValueError(f"{scene} 的角色没有开放 memory 工具，整理不能写记忆；开放后重启或在面板关闭记忆整理")
        conversation = [*history, {"role": "user", "content": instruction}]
        summary = {"upkeep": True, "messages": [{"role": "user", "content": instruction}],
                   "history_messages": len(history), "tools": [tool["function"]["name"] for tool in tools]}
        begun = self._begin(scene, plan, summary, memory)
        if self.on_update is not None:
            self.on_update()
        steps = self.config.memory.ingest.max_steps if memory else 2
        texts = {key: plain_text(message) for seq, message, _, _ in plan.rows
                 if (key := self._key(message, seq)) in humans}
        entries = {item["entry_seq"] for item in self.effects.effects(scene, plan.effects)} if plan.effects else set()
        written: list[str] = []
        failed_tools = 0
        # One reminder each when the tool rounds run out and when the final JSON cannot be read.
        out_of_steps = corrected = False
        try:
            async with asyncio.timeout(self.config.memory.ingest.timeout_seconds if memory else None):
                rounds = 0
                while True:
                    reply = await request_model(self.config, self.store, self.mind, conversation, tools, scene=scene,
                                                role="upkeep", slots=self.slots, quick=True, notify=self.on_update)
                    conversation.append(reply.message)
                    if reply.tool_calls:
                        rounds += 1
                        if rounds >= steps and out_of_steps:
                            raise RuntimeError(f"upkeep kept calling tools after {steps} rounds")
                        for call in reply.tool_calls:
                            if rounds >= steps:
                                content = "整理的工具次数用完了，这次没有执行。"
                            else:
                                content, failed = await self._tool(scene, call.name, call.arguments, memory,
                                                                   begun, written)
                                failed_tools += failed
                            conversation.append({"role": "tool", "tool_call_id": call.id, "content": content})
                        if rounds >= steps:
                            out_of_steps = True
                            conversation.append({"role": "user", "content": "工具次数用完了，现在只输出整理结果的 JSON 对象。"})
                        continue
                    try:
                        results, dropped = parse_results(reply, humans, texts, entries)
                        break
                    except ValueError as error:
                        if corrected:
                            raise
                        corrected = True
                        conversation.append({"role": "user", "content": f"上一条回复没法解析：{error}\n只输出整理结果的 JSON 对象。"})
            if dropped:
                LOG.warning("session upkeep dropped %d result item(s) for %s: %s", len(dropped), scene, dropped)
            await self._complete(scene, plan, begun, results, dropped, keys, reply, written, failed_tools)
        except asyncio.CancelledError as error:
            self._fail(begun, "interrupted", _error_text(error))
            self._failed(scene)
            if self.on_update is not None:
                self.on_update()
            raise
        except Exception as error:
            self._fail(begun, "failed", _error_text(error))
            self._failed(scene)
            LOG.exception("session upkeep failed for %s", scene)
        else:
            self._failures.pop(scene, None)
        if self.on_update is not None:
            self.on_update()

    def _failed(self, scene: str) -> None:
        self._failures[scene] = self._failures.get(scene, 0) + 1
        self._failed_at[scene] = self.store.now()

    async def _tool(self, scene: str, name: str, arguments: dict, memory: bool, begun: Begun,
                    written: list[str]) -> tuple[str, int]:
        job = begun.memory_job
        if name != "memory" or not memory:
            return f"整理时只能用 memory 工具，{name} 没有执行。", 0
        try:
            content = await self.memory.execute(scene, arguments)
        except Exception as error:
            content = f"memory 失败：{_error_text(error)}"
            job["details"]["tools"].append({"name": name, "arguments": arguments, "result": content,
                                            "error": _error_text(error)})
            self.memory.jobs.details(job)
            return content, 1
        job["details"]["tools"].append({"name": name, "arguments": arguments, "result": content[:2000], "error": None})
        if arguments.get("action") == "write":
            result = json.loads(content)
            written.append(result["path"])
            job["details"]["writes"].append({
                "path": result["path"], "action": result["action"], "changed_at": result["changed_at"],
                "reason": arguments.get("reason"),
                "before_chars": None if result.get("before") is None else len(result["before"]),
                "after_chars": None if result.get("after") is None else len(result["after"])})
        self.memory.jobs.details(job)
        return content, 0

    def _same_expression(self, scene: str, situation: str, style: str) -> str:
        """An adopted or pending expression with the same wording and a close situation absorbs the new one."""
        for item in self.learning.expressions(scene, status=None, limit=500, offset=0)["items"]:
            if item["style"] == style and item["status"] != "rejected" and overlap(item["situation"], situation) >= SAME_SITUATION:
                return item["situation"]
        return situation

    async def _complete(self, scene: str, plan: Plan, begun: Begun, results: dict, dropped: list[str],
                        keys: dict[str, int], reply: ModelReply, written: list[str], failed_tools: int) -> None:
        response = {"message": reply.message, "finish_reason": reply.finish_reason, "dropped": dropped}
        job = begun.memory_job
        if job is not None:
            # Failed memory calls went back to the model as results; the pass still completes.
            job["details"]["result"] = {"summary": reply.text[:2000], "write_count": len(written),
                                        "failed_tools": failed_tools}
            self.memory.jobs.status(job, "complete")
        if begun.batch is not None:
            self.learning.response(begun.batch, response, None, None)
            settings = self.scenes[scene].learning
            candidates = []
            vectors = self.expression_service is not None and scene in self.expression_service.clients
            for item in results["expressions"]:
                seqs = [keys[key] for key in item["sources"]]
                situation = item["situation"] if vectors else self._same_expression(scene, item["situation"], item["style"])
                candidates.append((situation, item["style"], seqs))
            if self.expression_service is None:
                self.learning.complete(begun.batch, candidates, auto_adopt=settings.auto_adopt)
            else:
                await self.expression_service.complete(scene, begun.batch, candidates, auto_adopt=settings.auto_adopt,
                                                       same_situation=SAME_SITUATION_VECTOR)
        if begun.discovery is not None:
            self.jargon.response(begun.discovery, response, None, None)
            proposals = [(item["term"], keys[key]) for item in results["terms"] for key in item["sources"]]
            excluded = self._exclude_uids(scene)
            call_id = begun.discovery

            def discover():
                with Store(self.config.database, now=self.store.now) as store:
                    JargonStore(store).complete_discovery(call_id, proposals, exclude_uids=excluded)
            await finish_file_operation(discover)
        # A term the reply leaves out stays pending for the next pass.
        meanings = {item["term"]: item for item in results["meanings"]}
        for term in plan.meanings:
            if term["term"] in meanings:
                call_id = self.jargon.begin_meaning(scene, term["id"], term["count"], begun.request)
                self.jargon.response(call_id, response, None, None)
                item = meanings[term["term"]]
                self.jargon.complete_meaning(call_id, item["meaning"], item["confidence"],
                                             ordinary_meaning=item["ordinary_meaning"] if item["same_meaning"] else None)
        if begun.effect_call is not None:
            self.effects.response(begun.effect_call, response, None, None)
            # Samples the reply left out stay unjudged on this call.
            self.effects.complete(begun.effect_call, results["effects"])
        if written and self.memory.summarizer is not None:
            async with self.memory.write_lock(scene):
                job["details"]["summaries"] = await self.memory.summarizer.refresh_after_writes(scene, written)
            self.memory.jobs.details(job)


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def parse_results(reply: ModelReply, humans: set[str], texts: dict[str, str],
                  entries: set[int]) -> tuple[dict, list[str]]:
    """The final upkeep reply and the reasons for each item dropped from it.

    Only a reply that is not a JSON object raises; an item failing a check is dropped and the rest kept.
    Sources must be group members' messages of this pass; ``entries`` are the reply samples asked for.
    """
    text = reply.text.strip()
    fenced = _FENCE.match(text)
    try:
        value = json.loads(fenced.group(1) if fenced else text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"Invalid upkeep result: {error}; response fragment: {reply.text[:500]!r}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Invalid upkeep result: expected a JSON object; response fragment: {reply.text[:500]!r}")
    dropped: list[str] = []
    checks = {"expressions": lambda item: _expression(item, humans),
              "terms": lambda item: _term(item, humans, texts),
              "meanings": _meaning,
              "effects": lambda item: _effect(item, entries)}
    results: dict = {}
    for name, check in checks.items():
        items = value.get(name, [])
        if not isinstance(items, list):
            dropped.append(f"{name}: not an array")
            items = []
        if len(items) > MAX_ITEMS:
            dropped.append(f"{name}: kept the first {MAX_ITEMS} of {len(items)}")
            items = items[:MAX_ITEMS]
        kept = []
        for index, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    raise ValueError("not an object")
                kept.append(check(item))
            except ValueError as error:
                dropped.append(f"{name}[{index}]: {error}")
        results[name] = kept
    effects: dict[int, tuple[str, str]] = {}
    for entry, reaction, reason in results["effects"]:
        if entry in effects:
            dropped.append(f"effects: entry_seq {entry} given twice, kept the first")
        else:
            effects[entry] = (reaction, reason)
    results["effects"] = effects
    return results, dropped


def _sources(item: dict, allowed: set[str]) -> list[str]:
    sources = item.get("sources")
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    keys = [key for key in dict.fromkeys(map(str, sources)) if key in allowed]
    if not keys:
        raise ValueError(f"no source is a group member's message of this pass: {sources!r}")
    return keys


def _expression(item: dict, humans: set[str]) -> dict:
    for name in ("situation", "style"):
        if not isinstance(item.get(name), str) or not item[name].strip():
            raise ValueError(f"{name} must be nonblank text")
    return {"situation": item["situation"], "style": item["style"], "sources": _sources(item, humans)}


def _term(item: dict, humans: set[str], texts: dict[str, str]) -> dict:
    term = item.get("term")
    if not isinstance(term, str) or not term.strip():
        raise ValueError("term must be nonblank text")
    term = term.strip()
    return {"term": term, "sources": _sources(item, {key for key in humans if term in texts[key]})}


def _meaning(item: dict) -> dict:
    confidence = item.get("confidence")
    if (not isinstance(item.get("term"), str) or not item['term'].strip()
            or any(not isinstance(item.get(key), str) or not item[key].strip()
                   for key in ('meaning', 'ordinary_meaning'))
            or type(item.get('same_meaning')) is not bool
            or type(confidence) not in {int, float} or not 0 <= confidence <= 1):
        raise ValueError("needs term, meaning, ordinary_meaning, boolean same_meaning and confidence in 0..1")
    return item


def _effect(item: dict, entries: set[int]) -> tuple[int, str, str]:
    entry, reaction, reason = item.get("entry_seq"), item.get("reaction"), item.get("reason")
    if type(entry) is not int or entry not in entries:
        raise ValueError(f"entry_seq is not a sample of this pass: {entry!r}")
    if reaction not in REACTIONS:
        raise ValueError(f"reaction is not one of {list(REACTIONS)}: {reaction!r}")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be nonblank text")
    return entry, reaction, reason


def runner_fork(runner, store: Store) -> Fork:
    """Snapshots of one runner's chat request, taken only while no turn is open."""
    async def fork(scene: str) -> tuple[list[dict], list[dict]] | None:
        if runner.execution.locked():
            return None
        async with runner.execution:
            if await store.call(store.has_open_turn, scene):
                return None
            return await runner.chat.upkeep_fork()
    return fork


@asynccontextmanager
async def open_session_upkeep(config: SharedConfig, store: Store, mind: ChatModel, *,
                              memory: MemoryService | None = None,
                              expression_service: ExpressionService | None = None,
                              slots: ModelSlots | None = None) -> AsyncIterator[SessionUpkeep]:
    upkeep = SessionUpkeep(config, store, mind, memory=memory, expression_service=expression_service, slots=slots)
    try:
        yield upkeep
    finally:
        await upkeep.close()


def upkeep_parts(upkeep: SessionUpkeep) -> dict[str, UpkeepPart | None]:
    """The runtime's ingestor, learning, jargon and reply_effects views of one upkeep."""
    return {"ingestor": UpkeepPart(upkeep, "memory") if upkeep.memory_enabled else None,
            "learning": UpkeepPart(upkeep, "expressions"), "jargon": UpkeepPart(upkeep, "jargon"),
            "reply_effects": UpkeepPart(upkeep, "effects")}


class UpkeepPart:
    """The per-part view the panel and runtime use: scenes, state, request and retry."""

    def __init__(self, upkeep: SessionUpkeep, part: str):
        self.upkeep = upkeep
        self.part = part

    @property
    def scenes(self) -> tuple[str, ...]:
        return tuple(sorted(self.upkeep.parts[self.part]))

    @property
    def errors(self) -> dict[str, BaseException]:
        return self.upkeep.errors

    @property
    def jobs(self):
        return self.upkeep.memory.jobs

    @property
    def on_update(self) -> Callable[[], None] | None:
        return self.upkeep.on_update

    @on_update.setter
    def on_update(self, value: Callable[[], None] | None) -> None:
        self.upkeep.on_update = value

    @property
    def connected_since(self) -> Callable[[], float | None]:
        return self.upkeep.connected_since

    @connected_since.setter
    def connected_since(self, value: Callable[[], float | None]) -> None:
        self.upkeep.connected_since = value

    def add_scene(self, scene: str) -> None:
        self.upkeep.enable(scene, self.part)

    async def remove_scene(self, scene: str) -> None:
        await self.upkeep.disable(scene, self.part)

    def start(self) -> None:
        self.upkeep.start()

    async def close(self) -> None:
        await self.upkeep.close()

    def wake(self, scene: str) -> None:
        self.upkeep.wake(scene)

    def request(self, scene: str) -> None:
        self.upkeep.request(scene, self.part)

    def retry(self, scene: str, call_id: int | None = None):
        self.upkeep.retry(scene, self.part, call_id)
        if self.part == "memory":
            return self.upkeep.memory.jobs.latest(scene)
        return None

    def state(self, scene: str) -> dict:
        upkeep = self.upkeep
        if scene not in upkeep.parts[self.part]:
            raise ValueError(f"{self.part} upkeep is not configured for scene {scene!r}")
        error = upkeep.errors.get(scene)
        common = {"scene": scene, "running": upkeep.running(scene),
                  "worker_error": None if error is None else _error_text(error)}
        if self.part == "expressions":
            return {**common, "after_seq": upkeep.learning.state(scene)["after_seq"],
                    "latest": upkeep.learning.latest(scene)}
        if self.part == "jargon":
            cursor = upkeep.jargon.state(scene)
            return {**common, "start_seq": cursor["start_seq"], "after_seq": cursor["after_seq"],
                    "latest": upkeep.jargon.latest(scene)}
        if self.part == "effects":
            return {**common, "open": len(upkeep.effects.open_effects(scene)),
                    "waiting": len(upkeep.effects.waiting(scene)), "latest": upkeep.effects.latest_call(scene),
                    "requested_retry": upkeep._effect_retry.get(scene)}
        return {**common, **upkeep.memory.jobs.view(scene)}
