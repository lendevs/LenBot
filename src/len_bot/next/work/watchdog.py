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
    """Track one worker execution's tool trajectory and idle gaps without extra model calls."""

    def __init__(self, *, hang_timeout_seconds: float = 300.0):
        self.hang_timeout_seconds = max(1.0, hang_timeout_seconds)

    def reset_intervention(self) -> None:
        """Reset loop/error counters after human steering or an answered question."""

    def on_tool_start(self, tool_name: str, args: dict) -> WatchdogDecision | None:
        return None

    def on_tool_end(self, tool_name: str, *, is_error: bool) -> WatchdogDecision | None:
        return None

    def check_idle(self, idle_seconds: float, *, model_busy: bool, waiting_input: bool) -> WatchdogDecision | None:
        if model_busy or waiting_input or idle_seconds < self.hang_timeout_seconds:
            return None
        return WatchdogDecision(
            action="stop",
            reason="silent_hang",
            detail=f"任务沙箱连续 {idle_seconds:.0f} 秒无事件输出且无在途模型请求",
        )
