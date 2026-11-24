"""Deterministic supervision of isolated task workers: loop, error-thrash and silent-hang guards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class WatchdogDecision:
    action: Literal["steer", "stop"]
    reason: Literal["identical_tool_loop", "consecutive_tool_errors", "silent_hang"]
    detail: str
    steer_message: str | None = None


class TaskWatchdog:
    """Track one worker execution's tool trajectory and idle gaps without extra model calls.

    ``silent_hang`` triggers only when ``not model_busy and not waiting_input and not active_tools``.
    Idle duration is measured from the latest Pi RPC record of any kind (including streaming updates).
    """

    def __init__(self, *, hang_timeout_seconds: float = 300.0):
        self.hang_timeout_seconds = max(1.0, hang_timeout_seconds)
        self._active_tools: set[str] = set()

    @property
    def active_tools(self) -> bool:
        return bool(self._active_tools)

    def reset_intervention(self) -> None:
        """Reset loop/error counters after human steering or an answered question."""

    def on_tool_start(self, tool_call_id: str, tool_name: str, args: dict) -> WatchdogDecision | None:
        self._active_tools.add(tool_call_id)
        return None

    def on_tool_end(self, tool_call_id: str, tool_name: str, *, is_error: bool) -> WatchdogDecision | None:
        self._active_tools.discard(tool_call_id)
        return None

    def check_idle(self, idle_seconds: float, *, model_busy: bool, waiting_input: bool) -> WatchdogDecision | None:
        if model_busy or waiting_input or self._active_tools or idle_seconds < self.hang_timeout_seconds:
            return None
        return WatchdogDecision(
            action="stop",
            reason="silent_hang",
            detail=f"任务沙箱连续 {idle_seconds:.0f} 秒无事件输出且无在途模型请求或工具执行",
        )
