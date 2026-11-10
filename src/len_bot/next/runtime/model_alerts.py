"""Telling the owners once when chat turns keep failing at the model provider, and once when they recover.

The host does not switch models or retry for the owner; it only says that the bot is away and why.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

from ...plugin import Text
from ..platform.messages import ChatMessage, Segment, Sender
from .logs import log_event

if TYPE_CHECKING:
    from .network import NetworkRuntime

logger = logging.getLogger(__name__)

# The sender name of the host's own lines in an owner's private chat.
ALERT_SOURCE = "模型提醒"


@dataclass
class FailureRun:
    """Consecutive failed chat turns on one mind binding, across every scene."""
    binding: tuple[str, str]
    first_at: float
    turns: int
    kind: str
    error: str
    scenes: set[str]
    alerted: bool = False


class ModelAlerts:
    def __init__(self, runtime: NetworkRuntime):
        self.runtime = runtime
        self.run: FailureRun | None = None
        self.background: set[asyncio.Task] = set()

    def binding(self) -> tuple[str, str]:
        mind = self.runtime.config.models.roles.mind
        return mind.provider, mind.model

    def observe(self, scene: str, result: dict) -> bool:
        """One finished chat turn: a provider failure extends the run, a turn the model answered ends it.

        Returns whether this turn ended a run of failures.
        """
        failure, replies = result.get("model_failure"), result.get("model_replies", 0)
        binding = self.binding()
        if failure is not None:
            run = self.run
            if run is None or (run.binding != binding and not run.alerted):
                run = self.run = FailureRun(binding, failure["at"], 0, failure["kind"], failure["error"], set())
            run.turns += 1
            run.kind, run.error = failure["kind"], failure["error"]
            run.scenes.add(scene)
            if not run.alerted and run.turns >= self.runtime.config.model_alert_failed_turns and run.binding == binding:
                run.alerted = True
                self._deliver("failed", self.failure_text(run))
        elif replies and self.run is not None:
            run, self.run = self.run, None
            if run.alerted:
                self._deliver("recovered", self.recovery_text(run))
            return True
        return False

    def _time(self, at: float) -> str:
        return datetime.fromtimestamp(at, ZoneInfo(self.runtime.config.timezone)).isoformat(timespec="seconds")

    def failure_text(self, run: FailureRun) -> str:
        provider, model = run.binding
        return (f"[宿主模型提醒] 聊天模型 {provider}/{model} 已连续 {run.turns} 个回合失败，"
                f"错误类别：{run.kind}，最早失败时间：{self._time(run.first_at)}，涉及 {len(run.scenes)} 个场景。"
                f"最近一次错误：{run.error[:300]}\n"
                "这段时间 Bot 不在场；宿主不会自动切换模型，恢复后会再提醒一次。")

    def recovery_text(self, run: FailureRun) -> str:
        provider, model = run.binding
        return (f"[宿主模型提醒] 聊天模型 {provider}/{model} 已恢复（{self._time(self.runtime.store.now())}）。"
                f"自 {self._time(run.first_at)} 起共 {run.turns} 个回合失败，错误类别：{run.kind}。"
                "恢复后只接最近的群聊，不逐条补回旧消息。")

    def targets(self) -> list[str]:
        """Each owner's private chat on a configured platform."""
        platforms = set(self.runtime.config.platform_names)
        return [f"{owner.split(':', 1)[0]}:private:{owner.split(':', 1)[1]}" for owner in self.runtime.config.owners
                if owner.split(":", 1)[0] in platforms]

    def _deliver(self, kind: str, text: str) -> None:
        targets = self.targets()
        if self.runtime.config.delivery != "live" or not targets:
            log_event(logger, "model_alert", level=logging.WARNING, kind=kind, status="not_sent",
                      reason="未开启真实发送或没有可私聊的主人", text=text)
            return
        for scene in targets:
            task = asyncio.create_task(self._send(kind, scene, text))
            self.background.add(task)
            task.add_done_callback(self.background.discard)

    async def _send(self, kind: str, scene: str, text: str) -> None:
        try:
            async with asyncio.timeout(30):
                chat = self.runtime.chats.get(scene)
                if chat is not None:
                    # An owner's private chat already open here records the line like a host notice.
                    sent = await chat.expression.send_plugin_content(ALERT_SOURCE, [Text(text)], reply_to=None,
                                                                    report_to_mind=False)
                    status, error = sent.status, None if sent.status in {"sent", "simulated"} else sent.report
                else:
                    result = await self.runtime.send_message(self.message(scene, text))
                    status, error = result.status, result.error
        except Exception as failure:
            status, error = "failed", f"{type(failure).__name__}: {failure}"
        log_event(logger, "model_alert", level=logging.WARNING if error else logging.INFO,
                  kind=kind, scene=scene, status=status, error=error)

    def message(self, scene: str, text: str) -> ChatMessage:
        bot = self.runtime.config.bot_for(scene)
        return ChatMessage(id=str(uuid4()), platform=scene.split(":", 1)[0], bot_id=bot, scene=scene,
                           platform_message_id=None, sender=Sender(bot, None, None, None),
                           time=self.runtime.store.now(), segments=[Segment("text", {"text": text})],
                           reply_to=None, mentions_bot=False, is_self=True, send_status="simulated")

