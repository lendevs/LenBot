"""Deterministic steer-only supervision of isolated task workers: loop, error-thrash and idle nudges."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal


@dataclass(frozen=True, slots=True)
class WatchdogDecision:
    action: Literal["steer", "stop"]
    reason: Literal["identical_tool_loop", "consecutive_tool_errors", "silent_hang"]
    detail: str
    steer_message: str | None = None


class TaskWatchdog:
    """Track one worker execution's tool trajectory and idle gaps without extra model calls.

    All interventions are steer-only guidance; termination is left to real budgets,
    active timeouts, and sandbox/bridge failures.
    ``silent_hang`` triggers only when ``not model_busy and not waiting_input and not active_tools``.
    Idle duration is measured from the latest Pi RPC record of any kind (including streaming updates).
    """

    def __init__(
        self,
        *,
        hang_timeout_seconds: float = 300.0,
        repeat_steer_threshold: int = 4,
        repeat_stop_threshold: int | None = None,
        error_steer_threshold: int = 6,
        error_stop_threshold: int | None = None,
    ):
        self.hang_timeout_seconds = max(1.0, hang_timeout_seconds)
        self.repeat_steer_threshold = repeat_steer_threshold
        self.repeat_stop_threshold = repeat_stop_threshold
        self.error_steer_threshold = error_steer_threshold
        self.error_stop_threshold = error_stop_threshold
        self._active_tools: set[str] = set()
        self._last_tool_signature: tuple[str, str] | None = None
        self._repeat_count = 0
        self._repeat_steered = False
        self._consecutive_errors = 0
        self._error_steered = False
        self._idle_steered = False

    @property
    def active_tools(self) -> bool:
        return bool(self._active_tools)

    def on_activity(self) -> None:
        """Clear idle-steer suppression once fresh worker activity arrives."""
        self._idle_steered = False

    def reset_intervention(self) -> None:
        """Reset loop/error/idle intervention state after human steering or an answered question."""
        self._last_tool_signature = None
        self._repeat_count = 0
        self._repeat_steered = False
        self._consecutive_errors = 0
        self._error_steered = False
        self._idle_steered = False

    def on_tool_start(self, tool_call_id: str, tool_name: str, args: dict) -> WatchdogDecision | None:
        self._idle_steered = False
        self._active_tools.add(tool_call_id)
        canonical_args = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        signature = (tool_name, canonical_args)
        if signature == self._last_tool_signature:
            self._repeat_count += 1
        else:
            self._last_tool_signature = signature
            self._repeat_count = 1
            self._repeat_steered = False
        if self._repeat_count >= self.repeat_steer_threshold and not self._repeat_steered:
            self._repeat_steered = True
            return WatchdogDecision(
                action="steer",
                reason="identical_tool_loop",
                detail=f"工具 {tool_name} 已连续 {self._repeat_count} 次使用相同参数调用",
                steer_message=(
                    f"已连续 {self._repeat_count} 次以完全相同的参数调用工具 `{tool_name}`。"
                    "请停止重复相同调用，先分析之前返回的结果或错误原因并改换排查路径；"
                    "若缺少关键信息且无法从现有资料推出，请使用 ask_requester 向请求人一次问清。"
                ),
            )
        return None

    def on_tool_end(self, tool_call_id: str, tool_name: str, *, is_error: bool) -> WatchdogDecision | None:
        self._idle_steered = False
        self._active_tools.discard(tool_call_id)
        if not is_error:
            self._consecutive_errors = 0
            self._error_steered = False
            return None
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.error_steer_threshold and not self._error_steered:
            self._error_steered = True
            return WatchdogDecision(
                action="steer",
                reason="consecutive_tool_errors",
                detail=f"工具调用已连续失败 {self._consecutive_errors} 次（最近工具：{tool_name}）",
                steer_message=(
                    f"工具调用已连续失败 {self._consecutive_errors} 次（最近工具：`{tool_name}`）。"
                    "请先分析错误原因并调整方案，不要原样重复尝试；"
                    "若存在无法自行补足的缺失信息或环境限制，请使用 ask_requester 明确说明。"
                ),
            )
        return None

    def check_idle(self, idle_seconds: float, *, model_busy: bool, waiting_input: bool) -> WatchdogDecision | None:
        if (
            model_busy
            or waiting_input
            or self._active_tools
            or idle_seconds < self.hang_timeout_seconds
            or self._idle_steered
        ):
            return None
        self._idle_steered = True
        return WatchdogDecision(
            action="steer",
            reason="silent_hang",
            detail=f"任务沙箱连续 {idle_seconds:.0f} 秒无事件输出且无在途模型请求或工具执行，已发送恢复引导",
            steer_message=(
                f"任务已连续 {idle_seconds:.0f} 秒无新进展或事件输出。"
                "请确认当前状态：若工作已完成，请直接总结交付收尾；"
                "若仍在推进，请继续下一步；若缺少关键信息或遇到阻塞，请调用 ask_requester 向请求人说明。"
            ),
        )
