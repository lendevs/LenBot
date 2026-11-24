"""Deterministic task watchdog, progress attention budget, and worker prompt checks."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import os
import sys
from types import SimpleNamespace

import pytest

from len_bot.next.prompt_files import read_prompt
from len_bot.next.storage.store import Store
from len_bot.next.work import execution as execution_module
from len_bot.next.work.execution import PROGRESS_NOTICE_INTERVAL, TaskExecution, WatchdogStoppedError
from len_bot.next.work.pi_rpc import PiRecord, PiRpc
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


def test_identical_tool_loop_steers_once_never_stops_and_resets():
    assert issubclass(WatchdogStoppedError, RuntimeError)
    watchdog = TaskWatchdog(repeat_stop_threshold=5, error_stop_threshold=8)
    assert watchdog.repeat_steer_threshold == 4
    assert watchdog.error_steer_threshold == 6

    assert watchdog.on_tool_start("c1", "bash", {"cmd": "ls", "dir": "/tmp"}) is None
    assert watchdog.on_tool_start("c2", "bash", {"dir": "/tmp", "cmd": "ls"}) is None
    assert watchdog.on_tool_start("c3", "bash", {"cmd": "ls", "dir": "/tmp"}) is None

    fourth = watchdog.on_tool_start("c4", "bash", {"cmd": "ls", "dir": "/tmp"})
    assert fourth is not None
    assert fourth.action == "steer"
    assert fourth.reason == "identical_tool_loop"
    assert fourth.steer_message and "ask_requester" in fourth.steer_message

    # Already steered once for this repeated signature; never hard-stops even past legacy stop threshold.
    for idx in range(5, 9):
        assert watchdog.on_tool_start(f"c{idx}", "bash", {"cmd": "ls", "dir": "/tmp"}) is None

    # Changing arguments resets the repeat counter and allows a fresh steer cycle.
    for idx in range(9, 12):
        assert watchdog.on_tool_start(f"c{idx}", "bash", {"cmd": "pwd"}) is None
    steered_again = watchdog.on_tool_start("c12", "bash", {"cmd": "pwd"})
    assert steered_again is not None and steered_again.action == "steer"

    # Human intervention clears repeat counters while keeping active tool tracking intact.
    assert watchdog.active_tools is True
    watchdog.reset_intervention()
    assert watchdog.active_tools is True
    for idx in range(13, 16):
        assert watchdog.on_tool_start(f"c{idx}", "bash", {"cmd": "pwd"}) is None
    steered_after_reset = watchdog.on_tool_start("c16", "bash", {"cmd": "pwd"})
    assert steered_after_reset is not None and steered_after_reset.action == "steer"


def test_consecutive_tool_errors_steer_once_never_stop_and_clear_on_success():
    watchdog = TaskWatchdog()

    for idx in range(1, 6):
        watchdog.on_tool_start(f"e{idx}", "bash", {"cmd": f"cmd-{idx}"})
        assert watchdog.on_tool_end(f"e{idx}", "bash", is_error=True) is None

    watchdog.on_tool_start("e6", "bash", {"cmd": "cmd-6"})
    sixth = watchdog.on_tool_end("e6", "bash", is_error=True)
    assert sixth is not None
    assert sixth.action == "steer"
    assert sixth.reason == "consecutive_tool_errors"
    assert sixth.steer_message

    # Subsequent consecutive errors in the same streak never trigger action="stop" or repeat steer.
    for idx in range(7, 11):
        watchdog.on_tool_start(f"e{idx}", "bash", {"cmd": f"cmd-{idx}"})
        assert watchdog.on_tool_end(f"e{idx}", "bash", is_error=True) is None

    # One successful tool call clears the consecutive error counter and steer flag.
    watchdog.on_tool_start("ok", "bash", {"cmd": "ok"})
    assert watchdog.on_tool_end("ok", "bash", is_error=False) is None

    for idx in range(1, 6):
        watchdog.on_tool_start(f"r{idx}", "read", {"path": f"f{idx}"})
        assert watchdog.on_tool_end(f"r{idx}", "read", is_error=True) is None
    watchdog.on_tool_start("r6", "read", {"path": "f6"})
    steered_again = watchdog.on_tool_end("r6", "read", is_error=True)
    assert steered_again is not None and steered_again.action == "steer"


def test_check_idle_steers_once_and_rearms_after_activity():
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

    steered = watchdog.check_idle(180.0, model_busy=False, waiting_input=False)
    assert steered is not None
    assert steered.action == "steer"
    assert steered.reason == "silent_hang"
    assert steered.steer_message and "ask_requester" in steered.steer_message

    # Only steers once per idle period until fresh activity arrives.
    assert watchdog.check_idle(240.0, model_busy=False, waiting_input=False) is None

    watchdog.on_activity()
    steered_again = watchdog.check_idle(180.0, model_busy=False, waiting_input=False)
    assert steered_again is not None
    assert steered_again.action == "steer"
    assert steered_again.reason == "silent_hang"
    assert watchdog.check_idle(240.0, model_busy=False, waiting_input=False) is None

    watchdog.reset_intervention()
    steered_after_reset = watchdog.check_idle(180.0, model_busy=False, waiting_input=False)
    assert steered_after_reset is not None and steered_after_reset.action == "steer"


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
async def test_consume_steers_without_stopping_on_loop_errors_and_silent_hang(tmp_path):
    with _make_execution(tmp_path) as (_store, records, item, task_exec, _, _):
        # 1. Identical tool loop triggers a single steer at 4 and never raises WatchdogStoppedError.
        loop_events = []
        for i in range(1, 7):
            loop_events.append(
                _record({"type": "tool_execution_start", "toolCallId": f"t{i}", "toolName": "bash", "args": {"cmd": "ls"}})
            )
            loop_events.append(
                _record({"type": "tool_execution_end", "toolCallId": f"t{i}", "toolName": "bash", "isError": False})
            )
        loop_events.extend([
            _record({"type": "message_end", "message": {
                "role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "循环已纠偏"}]
            }}),
            _record({"type": "agent_settled"}),
        ])
        pi = _FakePi(loop_events)
        task_exec._session = SimpleNamespace(
            pi=pi,
            proxy=SimpleNamespace(busy=False, recorded=lambda v: v),
            egress=None,
            browser_cli_version=None,
        )
        task_exec.active_limit = 1800.0
        async with asyncio.timeout(30.0) as timer:
            task_exec._timer = timer
            result = await task_exec._consume()

        assert result == "循环已纠偏"
        steer_cmds = [fields for cmd, fields in pi.commands if cmd == "steer"]
        assert len(steer_cmds) == 1
        assert "bash" in steer_cmds[0]["message"]
        saved = records.watchdog_events(SCENE, item.id)
        assert [(e["action"], e["reason"]) for e in saved] == [
            ("steer", "identical_tool_loop"),
        ]
        assert records.pending_notices(SCENE) == []

        # 2. Consecutive tool errors trigger a single steer at 6 and do not kill the task.
        task_exec._watchdog = TaskWatchdog()
        error_events = []
        for i in range(1, 9):
            error_events.append(
                _record({"type": "tool_execution_start", "toolCallId": f"e{i}", "toolName": "bash", "args": {"cmd": f"c{i}"}})
            )
            error_events.append(
                _record({"type": "tool_execution_end", "toolCallId": f"e{i}", "toolName": "bash", "isError": True})
            )
        error_events.extend([
            _record({"type": "message_end", "message": {
                "role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "错误已恢复"}]
            }}),
            _record({"type": "agent_settled"}),
        ])
        err_pi = _FakePi(error_events)
        task_exec._session = SimpleNamespace(
            pi=err_pi,
            proxy=SimpleNamespace(busy=False, recorded=lambda v: v),
            egress=None,
            browser_cli_version=None,
        )
        async with asyncio.timeout(30.0) as timer:
            task_exec._timer = timer
            err_result = await task_exec._consume()

        assert err_result == "错误已恢复"
        err_steers = [fields for cmd, fields in err_pi.commands if cmd == "steer"]
        assert len(err_steers) == 1
        assert records.watchdog_events(SCENE, item.id)[-1]["action"] == "steer"
        assert records.watchdog_events(SCENE, item.id)[-1]["reason"] == "consecutive_tool_errors"

        # 3. Silent idle steers once without stopping, stays quiet until activity resumes, and re-arms on activity.
        task_exec._watchdog = TaskWatchdog(hang_timeout_seconds=1.0)
        task_exec._watchdog.hang_timeout_seconds = 0.06
        hang_pi = _FakePi([
            0.03,
            _record({"type": "tool_execution_update", "toolCallId": "u1", "toolName": "bash", "args": {}}),
            0.18,
            _record({"type": "bash_execution_update", "delta": "resumed"}),
            0.16,
            _record({"type": "message_end", "message": {
                "role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "空闲恢复完成"}]
            }}),
            _record({"type": "agent_settled"}),
        ])
        task_exec._session = SimpleNamespace(
            pi=hang_pi,
            proxy=SimpleNamespace(busy=False, recorded=lambda v: v),
            egress=None,
            browser_cli_version=None,
        )
        async with asyncio.timeout(30.0) as timer:
            task_exec._timer = timer
            hang_result = await task_exec._consume()

        assert hang_result == "空闲恢复完成"
        hang_steers = [fields for cmd, fields in hang_pi.commands if cmd == "steer"]
        assert len(hang_steers) == 2
        saved_after = records.watchdog_events(SCENE, item.id)
        assert [(e["action"], e["reason"]) for e in saved_after[-2:]] == [
            ("steer", "silent_hang"),
            ("steer", "silent_hang"),
        ]

        # 4. Manual steer resets intervention counters (including idle steer) and refreshes _last_event_at.
        task_exec._watchdog.on_tool_start("x1", "bash", {"cmd": "id"})
        task_exec._watchdog.on_tool_start("x2", "bash", {"cmd": "id"})
        task_exec._watchdog.on_tool_start("x3", "bash", {"cmd": "id"})
        task_exec._last_event_at = 0.0
        await task_exec.steer("换个目录查")
        assert task_exec._last_event_at > 0.0
        assert task_exec._watchdog.on_tool_start("x4", "bash", {"cmd": "id"}) is None

        # 5. Recent proxy.last_active_at prevents false silent_hang right after a long model slot wait.
        task_exec._watchdog = TaskWatchdog(hang_timeout_seconds=1.0)
        task_exec._watchdog.hang_timeout_seconds = 0.05
        settle_pi = _FakePi([
            0.01,
            _record({"type": "message_end", "message": {
                "role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "完成"}]
            }}),
            _record({"type": "agent_settled"}),
        ])
        now_loop = asyncio.get_running_loop().time()
        task_exec._session = SimpleNamespace(
            pi=settle_pi,
            proxy=SimpleNamespace(busy=False, last_active_at=now_loop + 10.0, recorded=lambda v: v),
            egress=None,
            browser_cli_version=None,
        )
        async with asyncio.timeout(30.0) as timer:
            task_exec._timer = timer
            result_text = await task_exec._consume()
        assert result_text == "完成"
        assert [cmd for cmd, _ in settle_pi.commands if cmd == "steer"] == []


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


@pytest.mark.asyncio
async def test_consume_does_not_deadlock_on_full_pi_rpc_queue_during_watchdog_steer(tmp_path):
    child_script = (
        "import json, sys\n"
        "def emit(obj):\n"
        "    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\\n')\n"
        "prompt = json.loads(sys.stdin.readline())\n"
        "emit({'type': 'response', 'id': prompt['id'], 'command': 'prompt', 'success': True})\n"
        "for i in range(1, 5):\n"
        "    emit({'type': 'tool_execution_start', 'toolCallId': f't{i}', 'toolName': 'bash', 'args': {'cmd': 'ls'}})\n"
        "    if i < 4:\n"
        "        emit({'type': 'tool_execution_end', 'toolCallId': f't{i}', 'toolName': 'bash', 'isError': False})\n"
        "sys.stdout.flush()\n"
        "steer = json.loads(sys.stdin.readline())\n"
        "for _ in range(300):\n"
        "    emit({'type': 'tool_execution_update', 'toolCallId': 't4', 'toolName': 'bash', 'args': {'cmd': 'ls'}})\n"
        "emit({'type': 'response', 'id': steer['id'], 'command': 'steer', 'success': True})\n"
        "emit({'type': 'tool_execution_end', 'toolCallId': 't4', 'toolName': 'bash', 'isError': False})\n"
        "emit({'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': 'stop', "
        "'content': [{'type': 'text', 'text': '已排空300条事件:' + steer['type']}]}})\n"
        "emit({'type': 'agent_settled'})\n"
        "sys.stdout.flush()\n"
    )
    with _make_execution(tmp_path) as (_store, records, item, task_exec, _, _):
        pi = await PiRpc.spawn(
            [sys.executable, "-u", "-c", child_script],
            cwd=tmp_path,
            env=os.environ,
            stderr_path=tmp_path / "pi.stderr",
        )
        try:
            task_exec._session = SimpleNamespace(
                pi=pi,
                proxy=SimpleNamespace(busy=False, recorded=lambda v: v),
                egress=None,
                browser_cli_version=None,
            )
            task_exec.active_limit = 1800.0
            async with asyncio.timeout(30.0) as timer:
                task_exec._timer = timer
                result = await asyncio.wait_for(task_exec._consume(), timeout=5.0)
            assert result == "已排空300条事件:steer"
            assert pi._pending == {}
            assert task_exec._watchdog_steers == set()
            assert [(e["action"], e["reason"]) for e in records.watchdog_events(SCENE, item.id)] == [
                ("steer", "identical_tool_loop"),
            ]
        finally:
            await pi.close()


@pytest.mark.asyncio
async def test_silent_hang_queue_update_echo_does_not_retrigger_steer(tmp_path):
    class _EchoQueuePi:
        def __init__(self):
            self._queue: asyncio.Queue[PiRecord] = asyncio.Queue()
            self.commands: list[tuple[str, dict]] = []
            self.steer_sent = asyncio.Event()

        async def command(self, name: str, **fields):
            self.commands.append((name, fields))
            if name == "steer":
                await self._queue.put(
                    _record({"type": "queue_update", "steering": [fields["message"]], "followUp": []})
                )
                self.steer_sent.set()
            return PiRecord(body={"type": "response", "command": name, "success": True}, raw=b"{}")

        def push(self, record: PiRecord) -> None:
            self._queue.put_nowait(record)

        async def next_event(self) -> PiRecord:
            return await self._queue.get()

    with _make_execution(tmp_path) as (_store, records, item, task_exec, _, _):
        pi = _EchoQueuePi()
        task_exec._watchdog = TaskWatchdog(hang_timeout_seconds=1.0)
        task_exec._watchdog.hang_timeout_seconds = 0.05
        task_exec._session = SimpleNamespace(
            pi=pi,
            proxy=SimpleNamespace(busy=False, recorded=lambda v: v),
            egress=None,
            browser_cli_version=None,
        )
        task_exec.active_limit = 1800.0

        async def run_consume() -> str:
            async with asyncio.timeout(30.0) as timer:
                task_exec._timer = timer
                return await task_exec._consume()

        consuming = asyncio.create_task(run_consume())
        try:
            await asyncio.wait_for(pi.steer_sent.wait(), timeout=2.0)
            # Stay silent for >3x hang_timeout after Pi echoes queue_update: must NOT re-steer.
            await asyncio.sleep(0.16)
            assert [cmd for cmd, _ in pi.commands if cmd == "steer"] == ["steer"]

            # Real worker activity re-arms silent_hang once, and its queue_update echo again suppresses repeats.
            pi.steer_sent.clear()
            pi.push(_record({"type": "bash_execution_update", "delta": "resumed"}))
            await asyncio.wait_for(pi.steer_sent.wait(), timeout=2.0)
            await asyncio.sleep(0.12)
            assert [cmd for cmd, _ in pi.commands if cmd == "steer"] == ["steer", "steer"]

            pi.push(_record({"type": "message_end", "message": {
                "role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "静默未重复引导"}]
            }}))
            pi.push(_record({"type": "agent_settled"}))
            result = await asyncio.wait_for(consuming, timeout=2.0)
        finally:
            if not consuming.done():
                consuming.cancel()
                await asyncio.gather(consuming, return_exceptions=True)

        assert result == "静默未重复引导"
        assert [cmd for cmd, _ in pi.commands if cmd == "steer"] == ["steer", "steer"]
        assert [(e["action"], e["reason"]) for e in records.watchdog_events(SCENE, item.id)] == [
            ("steer", "silent_hang"),
            ("steer", "silent_hang"),
        ]
