"""Tests for WorkTasks._finish structured summary fields (files, can_continue, watchdog)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from len_bot.next.config import HostConfig
from len_bot.next.storage.store import Store
from len_bot.next.work.service import WorkTasks
from len_bot.next.work.watchdog import WatchdogDecision

SCENE = "onebot:group:80001"
BOT = "onebot:90001"
OWNER = "onebot:70001"
MEMBER = "onebot:70004"


def _make_config(root: Path) -> HostConfig:
    tasks = {"enabled": True, "max_running": 2, "max_daily_tasks": 20}
    return HostConfig.model_validate({
        "compaction": {"input_tokens": 2000},
        "mode": "isolated-multi",
        "bot_id": BOT,
        "timezone": "UTC",
        "owners": [OWNER],
        "database": root / "host.sqlite3",
        "delivery": "simulated",
        "onebot": None,
        "models": {
            "providers": {
                "fixture": {
                    "api": "openai-chat",
                    "base_url": "http://127.0.0.1:9/v1",
                    "api_key": "synthetic-key",
                }
            },
            "roles": {
                "mind": {
                    "provider": "fixture",
                    "model": "synthetic-model",
                    "context_window_tokens": 65536,
                }
            },
        },
        "worker": {
            "docker_binary": root / "docker",
            "docker_host": "unix:///var/run/docker.sock",
            "image": "lenbot-worker:local",
            "uid": 1000,
            "gid": 1000,
            "model_reasoning": False,
            "workspace_root": root / "workspaces",
            "runtime_root": root / "runtime",
            "delivery_root": root / "deliveries",
            "max_scene_containers": 4,
            "command_timeout_seconds": 10.0,
            "egress": {"mode": "off"},
        },
        "scenes": {SCENE: {"persona": root / "unused-role", "tasks": tasks}},
    })


def _make_tasks(root: Path, store: Store) -> WorkTasks:
    config = _make_config(root)
    return WorkTasks(
        config,
        store,
        None,
        lambda scene: None,
        skills={SCENE: ()},
        memory=None,
        data_tools={SCENE: []},
        skill_permissions={SCENE: []},
        tool_permissions={SCENE: []},
    )


def _latest_finished(tasks: WorkTasks, task_id: int) -> dict:
    page = tasks.records.event_page(SCENE, task_id, offset=0, snapshot=None)
    return next(event for event in page["events"] if event["kind"] == "finished")


@pytest.mark.asyncio
async def test_finish_done_includes_files_can_continue_and_none_watchdog(tmp_path):
    with Store(tmp_path / "host.sqlite3") as store:
        tasks = _make_tasks(tmp_path, store)
        item = tasks.records.create(SCENE, MEMBER, "生成季度报告", "report.csv", "", "生成报告")
        item = tasks.records.start(SCENE, item.id)
        delivered = tasks.records.add_file(
            SCENE, item.id, name="report.csv", path=str(tmp_path / "report.csv"), size=256, note="季度汇总"
        )

        tasks._finish(item, "done", "已生成季度报告", None)

        event = _latest_finished(tasks, item.id)
        body = event["body"]
        assert body["status"] == "done"
        assert body["summary"] == "已生成季度报告"
        assert body["error"] is None
        assert body["can_continue"] is True
        assert body["watchdog"] is None
        assert body["started"] is not None and body["ended"] is not None
        assert "tokens" in body
        assert len(body["files"]) == 1
        assert body["files"][0]["id"] == delivered.id
        assert body["files"][0]["name"] == "report.csv"
        assert body["files"][0]["size"] == 256
        assert body["files"][0]["note"] == "季度汇总"

        lines = event["notice"].splitlines()
        assert lines[0] == f"[任务执行结束] #{item.id}；请求人 {MEMBER}；生成季度报告"
        assert json.loads(lines[1]) == body


@pytest.mark.asyncio
async def test_finish_watchdog_stop_includes_last_watchdog_summary(tmp_path):
    with Store(tmp_path / "host.sqlite3") as store:
        tasks = _make_tasks(tmp_path, store)
        item = tasks.records.create(SCENE, MEMBER, "抓取对账数据", "summary.json", "", "抓取数据")
        item = tasks.records.start(SCENE, item.id)
        tasks.records.add_watchdog_event(
            SCENE,
            item.id,
            WatchdogDecision(action="steer", reason="identical_tool_loop", detail="重复调用同一命令 3 次"),
        )
        tasks.records.add_watchdog_event(
            SCENE,
            item.id,
            WatchdogDecision(action="stop", reason="silent_hang", detail="任务沙箱连续 300 秒无事件输出"),
        )

        tasks._finish(item, "failed", None, "任务因长时间无响应被中止")

        event = _latest_finished(tasks, item.id)
        body = event["body"]
        assert body["status"] == "failed"
        assert body["summary"] is None
        assert body["error"] == "任务因长时间无响应被中止"
        assert body["files"] == []
        assert body["can_continue"] is True
        assert body["watchdog"] == {
            "action": "stop",
            "reason": "silent_hang",
            "detail": "任务沙箱连续 300 秒无事件输出",
        }

        lines = event["notice"].splitlines()
        assert lines[0] == f"[任务执行结束] #{item.id}；请求人 {MEMBER}；抓取对账数据"
        assert json.loads(lines[1]) == body
        assert "最近过程编号" in event["notice"]


@pytest.mark.asyncio
async def test_finish_workspace_discarded_sets_can_continue_false(tmp_path):
    with Store(tmp_path / "host.sqlite3") as store:
        tasks = _make_tasks(tmp_path, store)
        item = tasks.records.create(SCENE, MEMBER, "导出明细表", "detail.xlsx", "", "导出表格")
        item = tasks.records.start(SCENE, item.id)
        tasks.records.add_file(
            SCENE, item.id, name="detail.xlsx", path=str(tmp_path / "detail.xlsx"), size=512, note="导出成果"
        )
        tasks.records.add_event(
            SCENE, item.id, "workspace_discard", {"requester": OWNER, "reason": "回收工作区"}
        )

        tasks._finish(item, "done", "已完成导出", None)

        event = _latest_finished(tasks, item.id)
        body = event["body"]
        assert body["status"] == "done"
        assert body["can_continue"] is False
        assert body["watchdog"] is None
        assert [f["name"] for f in body["files"]] == ["detail.xlsx"]

        lines = event["notice"].splitlines()
        assert lines[0] == f"[任务执行结束] #{item.id}；请求人 {MEMBER}；导出明细表"
        assert json.loads(lines[1]) == body
