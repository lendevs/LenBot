"""Deterministic task watchdog, progress attention budget, and worker prompt checks."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from len_bot.next.prompt_files import read_prompt
from len_bot.next.storage.store import Store
from len_bot.next.work import execution as execution_module
from len_bot.next.work.execution import PROGRESS_NOTICE_INTERVAL, TaskExecution, WatchdogStoppedError
from len_bot.next.work.pi_rpc import PiRecord
from len_bot.next.work.store import TaskStore
from len_bot.next.work.watchdog import TaskWatchdog, WatchdogDecision


SCENE = "onebot:group:80001"
REQUESTER = "onebot:70003"


@contextmanager
def _make_execution(tmp_path):
    with Store(tmp_path / "host.sqlite3") as store:
        records = TaskStore(store)
        item = records.create(
            SCENE,
            REQUESTER,
            "整理周报",
            "out/report.md",
            "补充说明",
            "原始任务输入",
        )
        records.start(SCENE, item.id)
        item = records.get(SCENE, item.id)

        settings = SimpleNamespace(
            command_timeout_seconds=10.0,
            max_calls=40,
            egress=SimpleNamespace(mode="off", allowed_hosts=[]),
            available_programs=lambda: set(),
        )
        config = SimpleNamespace(worker=settings)
        egress = SimpleNamespace(status=lambda *args: {"up": 0, "down": 0})
        notified: list[str] = []
        updated: list[str] = []
        live_notified: list[int] = []

        task_exec = TaskExecution(
            item,
            config,
            store,
            sandbox=None,
            files=None,
            egress=egress,
            slots=None,
            memory_call=None,
            data_call=None,
            audio=None,
            mcp=None,
            skills={SCENE: ()},
            skill_permissions={SCENE: "all"},
            tool_permissions={SCENE: "all"},
            data_tools={SCENE: []},
            active_timeout=lambda _: 1800.0,
            limits=lambda _: None,
            wait_for_slot=lambda _: asyncio.sleep(0),
            finish=lambda *args: None,
            release=lambda _: None,
            notify=notified.append,
            on_update=updated.append,
            notify_live=live_notified.append,
        )
        yield store, records, item, task_exec, notified, updated


class _FakePi:
    def __init__(self, events: list[PiRecord | float]):
        self._events = list(events)
        self.commands: list[tuple[str, dict]] = []

    async def command(self, name: str, **fields):
        self.commands.append((name, fields))
        return PiRecord(body={"type": "response", "command": name, "success": True}, raw=b"{}")

    async def next_event(self) -> PiRecord:
        if not self._events:
            await asyncio.sleep(3600)
        nxt = self._events.pop(0)
        if isinstance(nxt, (int, float)):
            await asyncio.sleep(nxt)
            return await self.next_event()
        return nxt


def _record(body: dict) -> PiRecord:
    return PiRecord(body=body, raw=b"{}")


def test_identical_tool_loop_steers_on_third_stops_on_fifth_and_resets():
    watchdog = TaskWatchdog()

    assert watchdog.on_tool_start("c1", "bash", {"cmd": "ls", "dir": "/tmp"}) is None
    assert watchdog.on_tool_start("c2", "bash", {"dir": "/tmp", "cmd": "ls"}) is None

    third = watchdog.on_tool_start("c3", "bash", {"cmd": "ls", "dir": "/tmp"})
    assert third is not None
    assert third.action == "steer"
    assert third.reason == "identical_tool_loop"
    assert third.steer_message and "ask_requester" in third.steer_message

    # Already steered once for this repeated signature.
    assert watchdog.on_tool_start("c4", "bash", {"cmd": "ls", "dir": "/tmp"}) is None

    fifth = watchdog.on_tool_start("c5", "bash", {"cmd": "ls", "dir": "/tmp"})
    assert fifth is not None
    assert fifth.action == "stop"
    assert fifth.reason == "identical_tool_loop"

    # Changing arguments resets the repeat counter and allows a fresh cycle.
    assert watchdog.on_tool_start("c6", "bash", {"cmd": "pwd"}) is None
    assert watchdog.on_tool_start("c7", "bash", {"cmd": "pwd"}) is None
    steered_again = watchdog.on_tool_start("c8", "bash", {"cmd": "pwd"})
    assert steered_again is not None and steered_again.action == "steer"

    # Human intervention clears repeat counters while keeping active tool tracking intact.
    assert watchdog.active_tools is True
    watchdog.reset_intervention()
    assert watchdog.active_tools is True
    assert watchdog.on_tool_start("c9", "bash", {"cmd": "pwd"}) is None
    assert watchdog.on_tool_start("c10", "bash", {"cmd": "pwd"}) is None
    steered_after_reset = watchdog.on_tool_start("c11", "bash", {"cmd": "pwd"})
    assert steered_after_reset is not None and steered_after_reset.action == "steer"


def test_consecutive_tool_errors_steer_on_fifth_stop_on_eighth_and_clear_on_success():
    watchdog = TaskWatchdog()

    for idx in range(1, 5):
        watchdog.on_tool_start(f"e{idx}", "bash", {"cmd": f"cmd-{idx}"})
        assert watchdog.on_tool_end(f"e{idx}", "bash", is_error=True) is None

    watchdog.on_tool_start("e5", "bash", {"cmd": "cmd-5"})
    fifth = watchdog.on_tool_end("e5", "bash", is_error=True)
    assert fifth is not None
    assert fifth.action == "steer"
    assert fifth.reason == "consecutive_tool_errors"
    assert fifth.steer_message

    for idx in (6, 7):
        watchdog.on_tool_start(f"e{idx}", "bash", {"cmd": f"cmd-{idx}"})
        assert watchdog.on_tool_end(f"e{idx}", "bash", is_error=True) is None

    watchdog.on_tool_start("e8", "bash", {"cmd": "cmd-8"})
    eighth = watchdog.on_tool_end("e8", "bash", is_error=True)
    assert eighth is not None
    assert eighth.action == "stop"
    assert eighth.reason == "consecutive_tool_errors"

    # One successful tool call clears the consecutive error counter and steer flag.
    watchdog.on_tool_start("ok", "bash", {"cmd": "ok"})
    assert watchdog.on_tool_end("ok", "bash", is_error=False) is None

    for idx in range(1, 5):
        watchdog.on_tool_start(f"r{idx}", "read", {"path": f"f{idx}"})
        assert watchdog.on_tool_end(f"r{idx}", "read", is_error=True) is None
    watchdog.on_tool_start("r5", "read", {"path": "f5"})
    steered_again = watchdog.on_tool_end("r5", "read", is_error=True)
    assert steered_again is not None and steered_again.action == "steer"


def test_check_idle_guards_against_false_silent_hang():
    watchdog = TaskWatchdog(hang_timeout_seconds=180.0)

    assert watchdog.check_idle(179.9, model_busy=False, waiting_input=False) is None
    assert watchdog.check_idle(600.0, model_busy=True, waiting_input=False) is None
    assert watchdog.check_idle(600.0, model_busy=False, waiting_input=True) is None

    # A running tool prevents silent_hang even if no events arrive for a long time.
    watchdog.on_tool_start("long-build", "bash", {"cmd": "make"})
    assert watchdog.active_tools is True
    assert watchdog.check_idle(600.0, model_busy=False, waiting_input=False) is None

    watchdog.on_tool_end("long-build", "bash", is_error=False)
    assert watchdog.active_tools is False

    stopped = watchdog.check_idle(180.0, model_busy=False, waiting_input=False)
    assert stopped is not None
    assert stopped.action == "stop"
    assert stopped.reason == "silent_hang"


def test_progress_dedup_notice_budget_and_watchdog_store_roundtrip(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(execution_module.time, "monotonic", lambda: clock[0])

    with _make_execution(tmp_path) as (store, records, item, task_exec, notified, updated):
        # First progress report emits notice immediately.
        task_exec._progress("已完成数据抓取")
        assert len(notified) == 1
        assert len(updated) == 0

        # Duplicate text (even with surrounding whitespace) is ignored completely.
        task_exec._progress("  已完成数据抓取 \n")
        assert len(notified) == 1
        assert len(updated) == 0

        # A distinct report within PROGRESS_NOTICE_INTERVAL writes progress with notice=None.
        clock[0] += PROGRESS_NOTICE_INTERVAL - 10.0
        task_exec._progress("正在清洗字段")
        assert len(notified) == 1
        assert len(updated) == 1

        # Once the interval elapses, the next distinct report carries a notice again.
        clock[0] += 10.0
        task_exec._progress("已生成初稿")
        assert len(notified) == 2
        assert len(updated) == 1

        rows = store.db.execute(
            "SELECT body, notice FROM task_events WHERE scene=? AND task_id=? AND kind='progress' ORDER BY id",
            (SCENE, item.id),
        ).fetchall()
        assert len(rows) == 3
        assert rows[0]["notice"] == f"[任务进度] #{item.id}；{item.goal}\n已完成数据抓取"
        assert rows[1]["notice"] is None
        assert rows[2]["notice"] == f"[任务进度] #{item.id}；{item.goal}\n已生成初稿"
        assert len(records.pending_notices(SCENE)) == 2

        # add_watchdog_event records notice=None and round-trips through watchdog_events.
        decision = WatchdogDecision(
            action="steer",
            reason="identical_tool_loop",
            detail="工具 bash 已连续 3 次使用相同参数调用",
            steer_message="请换一种排查方式",
        )
        event_id = records.add_watchdog_event(SCENE, item.id, decision)
        assert len(records.pending_notices(SCENE)) == 2
        events = records.watchdog_events(SCENE, item.id)
        assert len(events) == 1
        assert events[0]["id"] == event_id
        assert events[0]["action"] == "steer"
        assert events[0]["reason"] == "identical_tool_loop"
        assert events[0]["detail"] == decision.detail


@pytest.mark.asyncio
async def test_consume_triggers_watchdog_steer_stop_and_silent_hang(tmp_path):
    with _make_execution(tmp_path) as (_store, records, item, task_exec, _, _):
        # 1. Identical tool loop triggers steer at 3 and WatchdogStoppedError at 5.
        pi = _FakePi([
            _record({"type": "tool_execution_start", "toolCallId": f"t{i}", "toolName": "bash", "args": {"cmd": "ls"}})
            for i in range(1, 6)
        ])
        task_exec._session = SimpleNamespace(
            pi=pi,
            proxy=SimpleNamespace(busy=False, recorded=lambda v: v),
            egress=None,
            browser_cli_version=None,
        )
        task_exec.active_limit = 1800.0
        async with asyncio.timeout(30.0) as timer:
            task_exec._timer = timer
            with pytest.raises(WatchdogStoppedError, match="identical_tool_loop"):
                await task_exec._consume()

        steer_cmds = [fields for cmd, fields in pi.commands if cmd == "steer"]
        assert len(steer_cmds) == 1
        assert "bash" in steer_cmds[0]["message"]
        saved = records.watchdog_events(SCENE, item.id)
        assert [(e["action"], e["reason"]) for e in saved] == [
            ("steer", "identical_tool_loop"),
            ("stop", "identical_tool_loop"),
        ]
        assert records.pending_notices(SCENE) == []

        # 2. Streaming updates refresh _last_event_at before continue; silent hang stops when idle.
        task_exec._watchdog = TaskWatchdog(hang_timeout_seconds=1.0)
        task_exec._watchdog.hang_timeout_seconds = 0.08
        hang_pi = _FakePi([
            0.04,
            _record({"type": "tool_execution_update", "toolCallId": "u1", "toolName": "bash", "args": {}}),
            0.04,
            _record({"type": "bash_execution_update", "delta": "working"}),
        ])
        task_exec._session = SimpleNamespace(
            pi=hang_pi,
            proxy=SimpleNamespace(busy=False, recorded=lambda v: v),
            egress=None,
            browser_cli_version=None,
        )
        async with asyncio.timeout(30.0) as timer:
            task_exec._timer = timer
            with pytest.raises(WatchdogStoppedError, match="silent_hang"):
                await task_exec._consume()

        saved_after = records.watchdog_events(SCENE, item.id)
        assert saved_after[-1]["action"] == "stop"
        assert saved_after[-1]["reason"] == "silent_hang"

        # 3. Manual steer resets intervention counters and refreshes _last_event_at.
        task_exec._watchdog.on_tool_start("x1", "bash", {"cmd": "id"})
        task_exec._watchdog.on_tool_start("x2", "bash", {"cmd": "id"})
        task_exec._last_event_at = 0.0
        await task_exec.steer("换个目录查")
        assert task_exec._last_event_at > 0.0
        assert task_exec._watchdog.on_tool_start("x3", "bash", {"cmd": "id"}) is None


def test_worker_prompts_keep_placeholders_and_self_check_rules():
    worker_prompt = read_prompt("next_worker.md")
    for placeholder in ("${scene}", "${requester}", "${created_at}", "${timezone}",
                        "${goal}", "${deliverable}", "${context}"):
        assert placeholder in worker_prompt
    assert "deliver_file" in worker_prompt
    assert "ask_requester" in worker_prompt

    continuation_prompt = read_prompt("next_worker_continuation.md")
    assert "${facts}" in continuation_prompt
    assert "deliver_file" in continuation_prompt
    assert "ask_requester" in continuation_prompt
