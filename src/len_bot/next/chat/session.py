"""Persistent scene-serial model loop, composing context, tools and expression."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from dataclasses import dataclass
from string import Template
from typing import Literal
from zoneinfo import ZoneInfo

from ..media.audio import AudioService
from ..media.audio_store import AudioStore
from .context import ChatContext, turn_state
from .expression import ChatExpression, MessageSender
from .tools import SceneTools
from ..config import LabConfig
from .recap import (CompactionPlan, ContextBudgetError, estimate_content, estimate_text_request, plan_compaction,
                    recap_source)
from ..learning.expression_match import select_by_words
from ..learning.expression_selection import ExpressionService
from ..learning.store import LearningStore
from ..tools.external_tools import ExternalTool
from ..tools.skills import Skill
from ..models.limits import LimitReached, ModelBudget, SpeechLimitReached, check_speech

# Turn channels that may use the direct reserve besides direct wakes themselves.
RESERVE_CHANNELS = frozenset({"schedule", "task"})
# Calls that speak, wait or close a turn; any other call means the turn looked something up.
QUIET_TOOLS = frozenset({"say", "react", "wait", "end_turn", "attention", "message_reaction"})
FINAL_STEP_TOOLS = frozenset({"say", "react"})
PARALLEL_TOOLS = frozenset({"web_search", "web_read", "recall_chat", "look", "persona_knowledge", "member_info"})
from ..memory.service import MemoryService
from ..platform.messages import UploadResult
from ..models.client import ChatModel, ModelReply
from ..models.request import request_estimate, request_model
from ..models.slots import ModelSlots
from ..persona.profile import Persona, select_style
from ..platform.platform_tools import PlatformCall
from ..storage.store import Store, encode
from ..work.service import WorkTasks
from ..runtime.logs import add_context, log_event
from ..prompt_files import read_prompt
from ...media.images import image_block

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedContext:
    messages: list[dict]
    input_tokens: int
    estimate_method: str


def with_images(messages: list[dict], looked: list[tuple[str, bytes]]) -> list[dict]:
    """Attach the images the mind looked at in this turn to the per-request state message."""
    state = messages[-1]
    parts = [{"type": "text", "text": state["content"]}]
    for label, jpeg in looked:
        parts += [{"type": "text", "text": f"<{label}>"}, image_block(jpeg)]
    return [*messages[:-1], {**state, "content": parts}]


def final_step(messages: list[dict], tools: list[dict]) -> tuple[list[dict], list[dict]]:
    """The last step of a turn that looked something up and has not spoken: only say and react."""
    state = messages[-1]
    return ([*messages[:-1], {**state, "content": state["content"] + "\n" + read_prompt("next_last_step.md")}],
            [tool for tool in tools if tool["function"]["name"] in FINAL_STEP_TOOLS])


class Chat:
    def __init__(self, config: LabConfig, persona: Persona, store: Store,
                 mind: ChatModel, *,
                 vision: ChatModel | None = None,
                 memory: MemoryService | None = None,
                 tasks: WorkTasks | None = None,
                 expression_service: ExpressionService | None = None,
                 slots: ModelSlots | None = None,
                 send_message: MessageSender | None = None,
                 upload_file: Callable[[str, str, str], Awaitable[UploadResult]] | None = None,
                 platform_call: PlatformCall | None = None,
                 external_tools: list[ExternalTool] = (),
                 audio_service: AudioService | None = None,
                 on_update: Callable[[], None] | None = None,
                 on_compaction: Callable[[], None] | None = None,
                 on_reply_sample: Callable[[], None] | None = None,
                 now: Callable[[], float] = time.time,
                 on_trace: Callable[[dict], None] | None = None):
        self.config, self.persona, self.store = config, persona, store
        self.now = now
        self.on_trace = on_trace
        self.trace_step: int | None = None
        self.mind, self.vision = mind, vision
        self.audio = audio_service
        self.expression_service = expression_service
        self.expression_ids: list[int] | None = None
        if (config.memory is None) != (memory is None):
            raise ValueError("memory 服务必须与根配置的记忆后端一起提供")
        self.memory = memory
        if (config.worker is None) != (tasks is None):
            raise ValueError("任务服务必须与根配置的 worker 一起提供")
        self.tasks = tasks
        self.slots = slots
        self.direct_request = False
        self.turn_channel: str | None = None
        # Set when non-direct input joins a turn after it already spoke: that follow-up
        # traffic answers at the normal hourly limit, not from the direct reserve.
        self.reserve_revoked = False
        # Set when a reminder or task result joins a running turn: it may answer from the reserve
        # like one that opened its own turn.
        self.reserve_request = False
        self.turn_expressions = 0
        # Delivered messages since the latest direct input; reactions do not count as an answer.
        self.turn_messages = 0
        # Actual wake channels seen by the current turn, snapshotted per expression.
        self.turn_channels: set[str] = set()
        self.on_update = on_update
        self.on_compaction = on_compaction
        if (config.models.roles.vision is None) != (vision is None):
            raise ValueError("vision 客户端必须与根配置的视觉模型绑定一起提供")
        self.skills = () if tasks is None else tasks.skills[config.scene]
        self.context = ChatContext(config, persona, store, platform=send_message is not None, memory=memory)
        self.expression = ChatExpression(
            config, persona, store, context=self.context,
            send_message=send_message,
            on_sent=on_trace,
            notify=self.notify, on_reply_sample=on_reply_sample, now=now,
            exclude_from_memory=None if memory is None else lambda seq: memory.jobs.exclude_records(config.scene, [seq]))
        self.expression.reserve = lambda: self.speech_reserve
        self.toolset = SceneTools(
            config, persona, store, expression=self.expression, request=self.request, vision=vision,
            memory=memory, tasks=tasks, audio=audio_service, upload_file=upload_file,
            platform_call=platform_call, notify=self.notify, now=now)
        self.set_external_tools(external_tools)

    def set_external_tools(self, external_tools: list[ExternalTool]) -> None:
        """Refresh both the available schemas and their system-prompt descriptions."""
        allowed = self.toolset.set_external_tools(external_tools)
        self.context.configure_tools(allowed, [tool.definition for tool in self.toolset.external.values()],
                                     skills=self.skills, external_info=[
                                         {"discovery": tool.discovery, "instructions": tool.instructions}
                                         for tool in self.toolset.external.values()])

    def notify(self) -> None:
        if self.on_update is not None:
            self.on_update()

    def trace(self, type: str, turn_id: str, **fields) -> None:
        if self.on_trace is not None:
            self.on_trace({'type': type, 'turn_id': turn_id, 'step': self.trace_step, **fields})

    def restore(self) -> bool:
        previous = self.store.last_mind_request(self.config.scene)
        resume = self.store.recover(self.config.scene)
        if set(self.store.load_discovered_tools(self.config.scene)) != self.toolset.discovered_tools:
            self.store.save_discovered_tools(self.config.scene, sorted(self.toolset.discovered_tools))
        notices = []
        if previous is not None and previous["messages"][0]["content"] != self.context.system:
            notices.append("本次启动已更新角色、表达模式或工具能力，当前系统设定生效。")
        history = self.store.recent(self.config.scene, 1)
        if history:
            last = datetime.fromtimestamp(history[-1].time, ZoneInfo(self.config.timezone)).isoformat()
            notices.append(f"群会话已恢复，上次保存聊天时间：{last}。离线期间的消息尚未取得。")
        self.context.host_state = "\n".join(notices) or None
        return resume

    async def request(self, turn_id: str, role: Literal["mind", "recap", "vision"],
                      messages: list[dict], tools: list[dict], *,
                      recap_target: CompactionPlan | None = None,
                      expression_ids: list[int] | None = None,
                      input_estimate: tuple[int, str] | None = None,
                      recall_items: list[dict] | None = None, quick: bool = False) -> ModelReply:
        model_role = "mind" if role == "recap" else role
        model = getattr(self, model_role)
        def validate(reply: ModelReply) -> None:
            if role == "vision" and (reply.tool_calls or not reply.text.strip()):
                label = "视觉模型未返回完整描述"
                raise ValueError(f"{label}：{encode(reply.message)}")
            if recap_target is not None:
                if reply.tool_calls or not reply.text.strip():
                    raise ValueError(f"压缩模型未返回完整回想：{encode(reply.message)}")
                content_tokens = estimate_content(reply.text)
                if content_tokens > recap_target.summary_budget_tokens:
                    raise ContextBudgetError(
                        f"新回想正文估算 {content_tokens} token，超过本步回想预算 "
                        f"{recap_target.summary_budget_tokens}；未切换起点")

        return await request_model(
            self.config, self.store, model, messages, tools, scene=self.config.scene, role=role,
            turn_id=turn_id, slots=self.slots, direct=self.direct_request,
            output_tokens=self.config.compaction.max_output_tokens if role == "recap" else None,
            validate=validate, append_to_scene=role == "mind",
            recap_for=None if recap_target is None else (self.config.scene, recap_target.through),
            expression_ids=self.expression_ids if role == "mind" else expression_ids,
            input_estimate=input_estimate, notify=self.notify, recall_items=recall_items, quick=quick,
            trace=None if self.on_trace is None else lambda event: self.trace('turn.step', turn_id, **event))

    async def compact_now(self) -> dict:
        """One explicit operator-requested compaction; caller owns the scene lock."""
        turn_id = self.store.start_turn(self.config.scene)
        try:
            async with asyncio.timeout(self.config.turn_timeout_seconds):
                recap, entries = self.store.active_history(self.config.scene)
                binding = self.config.models.roles.mind
                state = turn_state(self.config, self.store, now=self.now())
                projection = await self.context.project(recap, entries, state)
                estimated, method = request_estimate(
                    self.config, self.store, self.mind, scene=self.config.scene, role="mind",
                    messages=projection, tools=self.toolset.tools, output_tokens=0)
                scale = (estimated / estimate_text_request(projection, self.toolset.tools, 0)
                         if method == "usage_assisted" else 1.0)
                plan = plan_compaction(
                    self.context.project_entries(entries), system=projection[0], state=projection[-1],
                    tools=self.toolset.core_tools, output_tokens=binding.max_output_tokens,
                    trigger_tokens=self.config.compaction.input_tokens,
                    keep_recent_tokens=self.config.compaction.keep_recent_tokens,
                    summary_output_tokens=self.config.compaction.max_output_tokens, recap=recap,
                    summary_template=read_prompt("next_recap.md"),
                    window_tokens=binding.context_window_tokens,
                    source_entries=self.context.conversation_entries(entries), token_scale=scale,
                )
                reply = await self.request(turn_id, "recap", plan.request_messages, [], recap_target=plan)
        except BaseException as error:
            self.store.end_turn(turn_id, "error", f"{type(error).__name__}: {error}")
            self.notify()
            raise
        self.store.end_turn(turn_id, "manual_compaction")
        if self.on_compaction is not None:
            self.on_compaction()
        self.notify()
        return {"turn_id": turn_id, "compact_through": plan.through, "recap": reply.text}

    async def hand_over(self, previous: str, current: str) -> str:
        """Fold the whole active session into a third-person handover; caller owns the scene lock.

        The next role starts from this recap instead of reading the previous role's lines as its own.
        """
        scene = self.config.scene
        if self.store.db.execute("SELECT 1 FROM turns WHERE scene=? AND ended IS NULL LIMIT 1", (scene,)).fetchone():
            raise ValueError("场景还有未结束或等待恢复的轮次，没有写交接")
        recap, entries = self.store.active_history(scene)
        if recap is None and not entries:
            return "skipped"
        template = Template(read_prompt("next_persona_handover.md")).safe_substitute(previous=previous, current=current)
        binding = self.config.models.roles.mind
        turn_id = self.store.start_turn(scene)
        try:
            async with asyncio.timeout(self.config.turn_timeout_seconds):
                if entries:
                    state = turn_state(self.config, self.store, now=self.now())
                    projection = await self.context.project(recap, entries, state)
                    plan = plan_compaction(
                        self.context.project_entries(entries), system=projection[0], state=projection[-1],
                        tools=self.toolset.core_tools, output_tokens=binding.max_output_tokens,
                        trigger_tokens=self.config.compaction.input_tokens, keep_recent_tokens=0,
                        summary_output_tokens=self.config.compaction.max_output_tokens, recap=recap,
                        summary_template=template, window_tokens=binding.context_window_tokens,
                        source_entries=self.context.conversation_entries(entries), include_latest=True,
                    )
                else:
                    # Only an earlier recap is active; rewrite it in place.
                    through = self.store.db.execute("SELECT compact_through FROM mind_sessions WHERE scene=?",
                                                    (scene,)).fetchone()[0]
                    budget = self.config.compaction.max_output_tokens
                    plan = CompactionPlan(through, budget, [
                        {"role": "system", "content": Template(template).substitute(summary_budget_tokens=budget)},
                        {"role": "user", "content": recap_source(recap, [])}])
                await self.request(turn_id, "recap", plan.request_messages, [], recap_target=plan)
        except BaseException as error:
            self.store.end_turn(turn_id, "error", f"{type(error).__name__}: {error}")
            self.notify()
            raise
        self.store.end_turn(turn_id, "persona_handover")
        if self.on_compaction is not None:
            self.on_compaction()
        self.notify()
        return "done"

    def adopt_persona(self, persona: Persona, skills: tuple[Skill, ...], external_tools: list[ExternalTool]) -> None:
        """Run the next turn as ``persona``; caller owns the scene lock and has updated ``config``.

        A role whose tools cannot be assembled leaves the previous role in place.
        """
        previous = self.persona, self.skills
        self.persona = self.context.persona = self.expression.persona = self.toolset.persona = persona
        self.skills = skills
        try:
            self.set_external_tools(external_tools)
        except Exception:
            self.persona = self.context.persona = self.expression.persona = self.toolset.persona = previous[0]
            self.skills = previous[1]
            self.set_external_tools(external_tools)
            raise

    async def prepare_context(self, turn_id: str, *, observed_at: float, expression_style: str | None = None,
                              recalled: str | None = None) -> PreparedContext:
        binding = self.config.models.roles.mind
        trigger = self.config.compaction.input_tokens
        token_scale = 1.0
        compacted = False
        while True:
            await self.store.call(AudioStore(self.store).append_late, self.config.scene)
            recap, entries = await self.store.read(self.store.active_history, self.config.scene)
            # Refresh only between model requests, never midway through a tool group.
            self.toolset.discovered_tools = set(await self.store.call(self.store.load_discovered_tools,
                                                                      self.config.scene))
            state = await self.store.call(turn_state, self.config, self.store, now=observed_at,
                                          expression_style=expression_style, recalled=recalled)
            messages = await self.context.project(recap, entries, state)
            estimated, method = await self.store.call(
                request_estimate, self.config, self.store, self.mind, scene=self.config.scene,
                role='mind', messages=messages, tools=self.toolset.tools, output_tokens=0)
            if method == "usage_assisted":
                token_scale = estimated / estimate_text_request(messages, self.toolset.tools, 0)
            elif compacted:
                estimated = round(estimated * token_scale)
                method = "usage_scaled_after_recap" if token_scale != 1.0 else method
            if estimated <= trigger:
                return PreparedContext(messages, estimated, method)
            scale = token_scale
            plan = plan_compaction(
                self.context.project_entries(entries), system=messages[0], state=messages[-1], tools=self.toolset.core_tools,
                output_tokens=binding.max_output_tokens, trigger_tokens=trigger,
                keep_recent_tokens=self.config.compaction.keep_recent_tokens,
                summary_output_tokens=self.config.compaction.max_output_tokens,
                recap=recap, summary_template=read_prompt("next_recap.md"),
                window_tokens=binding.context_window_tokens,
                source_entries=self.context.conversation_entries(entries), token_scale=scale,
            )
            await self.request(turn_id, "recap", plan.request_messages, [], recap_target=plan)
            compacted = True
            if self.on_compaction is not None:
                self.on_compaction()

    @property
    def speech_reserve(self) -> bool:
        """Direct wakes (@, replies to the bot, private chat), reminders and task results may
        still speak after the normal hourly limit. Audio transcripts and plugin events follow
        the normal limit like any other wake."""
        if self.reserve_revoked:
            return False
        return self.direct_request or self.reserve_request or self.turn_channel in RESERVE_CHANNELS

    def followup_arrived(self, talking: set[str]) -> bool:
        """A new message from someone this turn answers, or one that addresses the bot."""
        private = self.config.scene.split(":", 2)[1] == "private"
        return any(not message.is_self and (private or message.mentions_bot or message.sender.uid in talking)
                   for _, message, _ in self.store.pending_messages(self.config.scene))

    def check_limits(self, *, model: bool = False, direct: bool | None = None, max_age: float = 0.0) -> None:
        """``max_age`` lets a polling caller reuse token totals a few seconds old."""
        check_speech(self.store, self.config, direct=self.speech_reserve if direct is None else direct)
        if model and self.slots is not None and self.slots.admit is not None:
            budget = getattr(self.slots.admit, '__self__', None)
            if max_age > 0 and isinstance(budget, ModelBudget):
                budget.check(self.config.scene, max_age=max_age)
            else:
                self.slots.admit(self.config.scene)

    async def run_turn(self, *, batch: tuple[int, list[str]] | None,
                       append_new: Callable[[bool, str], Awaitable[bool]],
                       wait_for_messages: Callable[[float], Awaitable[str]],
                       attention_state: dict, scheduled: list[tuple[int, str]] | None = None,
                       task_notices: list[tuple[int, str]] | None = None,
                       plugin_events: list[tuple[int, str]] | None = None,
                       direct: bool = False, wake_received_at: float | None = None,
                       channels: set[str] | None = None,
                       proactive: tuple[str, str, float] | None = None, channel: str | None = None) -> dict:
        self.direct_request = direct
        self.turn_channel = channel
        self.reserve_revoked = False
        self.reserve_request = False
        self.turn_expressions = 0
        self.turn_messages = 0
        observed_at = self.now()
        self.turn_channels = set() if channels is None else set(channels)
        scene = self.config.scene
        talking = set() if batch is None else {
            message.sender.uid for seq, message, _ in self.store.pending_messages(scene)
            if seq <= batch[0] and not message.is_self}
        # Synchronous: a cancellation between this write and the try below would leave the turn open.
        turn_id = self.store.start_turn(scene, batch=batch, attention_state=attention_state,
                                       scheduled=scheduled, task_notices=task_notices,
                                       plugin_events=plugin_events,
                                       wake_received_at=wake_received_at, proactive=proactive,
                                       wake_channel=channel or 'resume')
        self.trace_step = None
        self.trace('turn.started', turn_id, channel=channel or 'resume', channels=sorted(self.turn_channels), direct=direct)
        add_context(turn_id=turn_id)
        # The link from waking input to this turn: message seqs, schedules, task notices and plugin events.
        log_event(logger, 'turn_start', channel=channel, channels=sorted(self.turn_channels), direct=direct,
                  batch=None if batch is None else {'through_seq': batch[0], 'entries': len(batch[1])},
                  schedules=[item[0] for item in scheduled or []], task_notices=[item[0] for item in task_notices or []],
                  plugin_events=[item[0] for item in plugin_events or []], proactive=proactive is not None)
        self.notify()
        expressions: list[str] = []
        extensions = 0
        failed_tools = 0
        status, error_text = "step_limit", None
        limit_until = limit_kind = None
        phase = None
        try:
            async with asyncio.timeout(self.config.turn_timeout_seconds):
                recalled = None
                self.trace('turn.step', turn_id, kind='recall', phase='start')
                recall_items = []
                recall_error = None
                try:
                    if self.memory is not None and self.memory.settings.auto_recall:
                        phase = '记忆自动召回'
                        recall = await self.memory.recall(
                            scene, await self.store.call(self.store.recent_context_messages, scene, limit=8))
                        if recall["items"]:
                            recalled = encode({"backend": recall["backend"], "items": recall["items"]})
                        recall_items = recall['items']
                except BaseException as error:
                    recall_error = f'{type(error).__name__}: {error}'
                    raise
                finally:
                    self.trace('turn.step', turn_id, kind='recall', phase='end', error=recall_error, items=[
                        {'scope': item['scope'], 'path': item['path'], 'characters': len(item['content'])}
                        for item in recall_items])
                phase = None
                self.expression_ids = None
                learned = None
                vectors = self.expression_service is not None and scene in self.expression_service.scenes
                if vectors or self.config.learning is not None:
                    recent = await self.store.call(self.store.recent_context_messages, scene, limit=8)
                    others = [message for message in recent
                              if not message.is_self and message.sender.uid not in self.config.attention.other_bot_ids]
                    exclude = (self.config.bot_id, *self.config.attention.other_bot_ids)
                    selected = []
                    if vectors:
                        query = "\n".join(self.context.render(message) for message in others)
                        if query:
                            phase = '群内说法向量检索'
                            selected = await self.expression_service.select(
                                scene, query, turn_id=turn_id, direct=direct, exclude_uids=exclude)
                    else:
                        # Without embeddings, rank by the words the recent chat shares with each situation.
                        query = "\n".join(self.context.render_text(message) for message in others)
                        if query.strip():
                            phase = '群内说法检索'
                            selected = select_by_words(await self.store.call(
                                LearningStore(self.store).adopted, scene, exclude_uids=exclude), query)
                    if selected:
                        self.expression_ids = [item["id"] for item in selected]
                        learned = Template(read_prompt("next_learned_expressions.md")).substitute(
                            expressions=encode([{ "情境": item["situation"], "说法": item["style"] } for item in selected]))
                phase = None
                style = select_style(self.persona)
                expression_style = None
                if style is not None:
                    expression_style = Template(read_prompt("next_style.md")).substitute(
                        name=style.name, note="" if style.note is None else style.note,
                    )
                if learned is not None:
                    expression_style = learned if expression_style is None else expression_style + "\n" + learned
                looked_up = stepped_lookup = False
                self.toolset.looked = []
                for step in range(self.config.max_steps):
                    self.trace_step = step + 1
                    self.check_limits()
                    prepared = await self.prepare_context(turn_id, observed_at=observed_at,
                                                          expression_style=expression_style, recalled=recalled)
                    messages, tools = prepared.messages, self.toolset.tools
                    if step + 1 == self.config.max_steps and looked_up and not expressions:
                        messages, tools = final_step(messages, tools)
                    if self.toolset.looked:
                        messages = with_images(messages, self.toolset.looked)
                    # Answering new messages thinks briefly; reading tool results uses the full effort.
                    reply = await self.request(turn_id, "mind", messages, tools,
                                               input_estimate=(prepared.input_tokens, prepared.estimate_method),
                                               recall_items=recall_items, quick=not stepped_lookup)
                    stepped_lookup = any(call.name not in QUIET_TOOLS for call in reply.tool_calls)
                    looked_up = looked_up or stepped_lookup
                    end_turn, group_failed = False, False
                    # Several read-only calls in one reply run together; results are stored in call order.
                    parallel = [call for call in reply.tool_calls if call.name in PARALLEL_TOOLS]
                    prefetched = {call.id: asyncio.create_task(self.toolset.execute(
                        turn_id, call, wait_for_messages, expression_style=expression_style, direct=self.direct_request))
                        for call in parallel} if len(parallel) > 1 else {}
                    try:
                        for call in reply.tool_calls:
                            self.trace('turn.step', turn_id, kind='tool', phase='start', call_id=call.id,
                                       name=call.name, arguments_summary=encode(call.arguments)[:500])
                            tool_status, tool_summary = 'complete', ''
                            try:
                                if call.name == "memory":
                                    # A tool may have edited or removed the recalled file, even if
                                    # a later index update failed. Do not reattach an old excerpt.
                                    recalled = None
                                    recall_items = []
                                try:
                                    started = prefetched.pop(call.id, None)
                                    content, expression, discovered = await (started if started is not None else self.toolset.execute(
                                        turn_id, call, wait_for_messages, expression_style=expression_style, direct=self.direct_request,
                                    ))
                                except Exception as error:
                                    tool_status = 'error'
                                    tool_summary = f'{type(error).__name__}: {error}'
                                    group_failed = True
                                    failed_tools += 1
                                    await self.store.call(self.store.complete_tool, scene, call.id,
                                                          f"{call.name} 失败：{type(error).__name__}: {error}")
                                    if isinstance(error, LimitReached):
                                        raise
                                else:
                                    if expression is None:
                                        reaction = call.name == 'message_reaction'
                                        await self.store.call(self.store.complete_tool, scene, call.id, content,
                                                              discovered_tools=discovered,
                                                              response_turn_id=turn_id if reaction else None)
                                        if reaction:
                                            expressions.append(content)
                                            self.turn_expressions += 1
                                            end_turn = end_turn or call.arguments.get('end_turn', True)
                                            self.trace('turn.step', turn_id, kind='expression', phase='end',
                                                       call_id=call.id, status='complete', summary=content[:500])
                                        elif call.name == 'attention':
                                            end_turn = end_turn or call.arguments.get('end_turn', False)
                                        elif call.name == 'end_turn':
                                            end_turn = True
                                    else:
                                        content, delivery_status = await self.expression.deliver_expression(
                                            call.id, expression, turn_id=turn_id, channels=self.turn_channels,
                                        )
                                        expressions.append(content)
                                        self.turn_expressions += 1
                                        if delivery_status in {"sent", "simulated", "unconfirmed", "partial"}:
                                            self.turn_messages += 1
                                        if delivery_status in {"sent", "simulated"}:
                                            end_turn = end_turn or expression.end_turn
                                        else:
                                            group_failed = True
                                            tool_status = 'error'
                                            failed_tools += 1
                                        self.trace('turn.step', turn_id, kind='expression', phase='end',
                                                   call_id=call.id, status=delivery_status, summary=content[:500])
                                    tool_summary = content
                            except BaseException as error:
                                tool_status = 'cancelled' if isinstance(error, asyncio.CancelledError) else 'error'
                                tool_summary = f'{type(error).__name__}: {error}'
                                raise
                            finally:
                                self.trace('turn.step', turn_id, kind='tool', phase='end', call_id=call.id,
                                           name=call.name, status=tool_status, summary=tool_summary[:500])
                            self.notify()
                    finally:
                        for started in prefetched.values():
                            started.cancel()
                    if not reply.tool_calls or (end_turn and not group_failed):
                        # Someone in this conversation kept talking while the step ran: they reach the
                        # model as new input instead of waiting for the next turn.
                        if (step + 1 < self.config.max_steps and extensions < self.config.attention.max_extensions
                                and self.followup_arrived(talking) and await append_new(True, turn_id)):
                            extensions += 1
                            continue
                        status = "settled"
                        break
                    if step + 1 < self.config.max_steps and extensions < self.config.attention.max_extensions:
                        if await append_new(bool(reply.tool_calls), turn_id):
                            extensions += 1
                            continue
        except asyncio.CancelledError:
            self.store.finish_pending_tools(scene, "当前轮被取消")
            self.store.end_turn(turn_id, "cancelled", "CancelledError")
            self.trace('turn.ended', turn_id, status='cancelled', error='CancelledError')
            raise
        except Exception as error:
            status = "limited" if isinstance(error, LimitReached) else "timeout" if isinstance(error, TimeoutError) else "error"
            limit_until = error.until if isinstance(error, LimitReached) else None
            limit_kind = ("speech" if isinstance(error, SpeechLimitReached) else "tokens"
                          if isinstance(error, LimitReached) else None)
            error_text = f"{type(error).__name__}: {error}"
            if phase is not None:
                error_text = f'{phase}失败：{error_text}'
        self.store.finish_pending_tools(scene, error_text or status)
        self.trace('turn.ended', turn_id, status=status, error=error_text,
                   expressions=len(expressions), steps=self.trace_step or 0)
        return {"turn_id": turn_id, "status": status, "error": error_text,
                "delivery": "simulated" if self.expression.send_message is None else "onebot",
                "expressions": expressions, "extensions": extensions,
                "failed_tools": failed_tools, "limit_until": limit_until, "limit_kind": limit_kind}
