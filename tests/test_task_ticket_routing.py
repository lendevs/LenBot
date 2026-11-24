"""Waiting-input wakeup penetration and turn_state router ticket rendering."""

from __future__ import annotations

import json
import re
from pathlib import Path

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.context import turn_state
from len_bot.next.chat.session import Chat
from len_bot.next.configuration.tasks import WorkerSettings
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store
from len_bot.next.work.store import TaskStore
from test_attention_protocol import START, message
from test_native_tool_calls import SCENE, _instance


def _worker_settings(root: Path) -> WorkerSettings:
    return WorkerSettings(
        sandbox="bwrap",
        bwrap_binary=root / "bwrap",
        task_runtime=root / "runtime",
        workspace_root=root / "workspaces",
        runtime_root=root / "run",
        delivery_root=root / "deliveries",
        model_reasoning=False,
    )


def _raw_event(user: int, ident: int, segments: list[dict], *, at: float = START) -> dict:
    return {
        "post_type": "message",
        "message_type": "group",
        "self_id": 90001,
        "group_id": 80001,
        "user_id": user,
        "message_id": ident,
        "time": int(at),
        "sender": {"nickname": "群成员", "role": "member"},
        "message": segments,
    }


def _extract_tag(content: str, tag: str) -> list[dict]:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", content, re.DOTALL)
    assert match is not None, f"missing <{tag}> in:\n{content}"
    return json.loads(match.group(1))


def test_waiting_input_wakes_requester_after_focus_expiry_and_ignores_noise_or_bystanders(tmp_path):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 90
    config.attention.explore_probability = 0
    config.attention.other_bot_ids = ["onebot:70009"]
    now = [START]

    with Store(config.database, now=lambda: now[0]) as store:
        tasks = TaskStore(store)
        item = tasks.create(SCENE, "onebot:70001", "整理报价表", "CSV 文件", "群内讨论", "导出所有条目")
        tasks.start(SCENE, item.id)
        tasks.set_question(SCENE, item.id, {"id": "q1", "kind": "info", "text": "需要包含已下架商品吗？"})

        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda _: None)
        live.state.followups["onebot:70001"] = START

        # Advance 600s (> focus_seconds=90) so the normal focus follow-up window is expired.
        now[0] = START + 600

        # Pure sticker, [表情], face, and trivial fillers from the requester must not wake.
        noise_cases = [
            (70001, 10, [{"type": "image", "data": {"file": "sticker.gif", "sub_type": 1}}]),
            (70001, 11, [{"type": "text", "data": {"text": "[表情]"}}]),
            (70001, 12, [{"type": "face", "data": {"id": "178"}}]),
            (70001, 13, [{"type": "text", "data": {"text": "嗯"}}]),
            (70001, 14, [{"type": "text", "data": {"text": "6"}}]),
        ]
        for user, ident, segments in noise_cases:
            now[0] += 1
            verdict = live.receive(_raw_event(user, ident, segments, at=now[0]))["wake_verdict"]
            assert not verdict["woke"] and verdict["channel"] is None
            assert live.state.pending is None

        # Unrelated bystander filler, bystander chat addressed to others, blacklisted user, and other bot must not trigger waiting_input focus.
        now[0] += 1
        assert not live.receive(message(70002, 15, "哈哈"))["wake_verdict"]["woke"]
        now[0] += 1
        bystander = live.receive(message(70002, 16, "你吃晚饭了吗", reply=999))["wake_verdict"]
        assert not bystander["woke"]
        now[0] += 1
        other_bot = live.receive(message(70009, 17, "不用包含已下架商品"))["wake_verdict"]
        assert not other_bot["woke"] and other_bot["reason"] == "来自其他 Bot"
        now[0] += 1
        # Requester explicitly addressing another member must not trigger waiting_input focus.
        to_other = live.receive(message(70001, 18, "你先去看下接口", reply=999))["wake_verdict"]
        assert not to_other["woke"] and to_other["reason"] == "发给别人的消息"

        # Bystander general chat never triggers waiting_input focus (at most ambient, never focus).
        now[0] += 1
        bystander_chat = live.receive(message(70002, 19, "明天是不是要降温了？"))["wake_verdict"]
        assert bystander_chat["channel"] != "focus"
        assert bystander_chat["reason"] != "回答等待中的任务提问"

        # Requester's meaningful reply penetrates expired focus_seconds and upgrades pending wake to focus.
        now[0] += 1
        answer = live.receive(message(70001, 20, "不用包含已下架商品，按价格排序"))["wake_verdict"]
        assert answer["woke"]
        assert answer["channel"] == "focus"
        assert answer["reason"] == "回答等待中的任务提问"
        assert live.state.pending is not None
        assert live.state.pending.channel == "focus"
        assert "onebot:70001" in live.state.pending.people


def test_waiting_input_respects_only_direct_and_keeps_reply_to_own(tmp_path):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 90
    config.attention.only_direct = True
    now = [START]

    with Store(config.database, now=lambda: now[0]) as store:
        tasks = TaskStore(store)
        item = tasks.create(SCENE, "onebot:70001", "生成周报", "Markdown", "群聊请求", "汇总本周进度")
        tasks.start(SCENE, item.id)
        tasks.set_question(SCENE, item.id, {"id": "q2", "kind": "confirm", "text": "是否包含测试环境记录？"})

        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda _: None)
        live.own_ids.add("88001")

        # Under only_direct=True, plain message from requester respects only_direct.
        now[0] = START + 600
        plain = live.receive(message(70001, 30, "包含测试环境记录"))["wake_verdict"]
        assert not plain["woke"] and plain["reason"] == "只回应直接联系"

        # Quoting the bot's own message via receive stays direct (not downgraded to focus).
        now[0] += 1
        quoted = live.receive(message(70002, 31, "包含测试环境记录", reply=88001))["wake_verdict"]
        assert quoted["woke"] and quoted["channel"] == "direct"

        # Direct offer_message call with reply_to in own_ids (without mentions_bot set) still triggers focus wakeup.
        live.state.pending = None
        raw = message(70002, 32, "是的，包含测试环境", reply=88001)
        parsed = parse_message(raw, own_message_ids=set())
        assert not parsed.mentions_bot
        verdict = live.offer_message(live.state, parsed, now[0] + 1)
        assert verdict.woke and verdict.channel == "focus"
        assert verdict.reason == "回答等待中的任务提问"
        assert live.state.pending is not None and live.state.pending.people == ["onebot:70002"]


def test_turn_state_renders_active_and_recent_tickets_with_window_and_worker_gate(tmp_path):
    config, _ = _instance(tmp_path)
    config.worker = _worker_settings(tmp_path)
    now = [START]

    with Store(config.database, now=lambda: now[0]) as store:
        tasks = TaskStore(store)

        # 1) Old completed task (> 6 hours ago): must be excluded from <近期结束工作>.
        old_task = tasks.create(SCENE, "onebot:70001", "旧报表", "PDF", "ctx", "做旧报表")
        tasks.start(SCENE, old_task.id)
        now[0] = START + 100
        tasks.finish(SCENE, old_task.id, "done", "已完成旧报表", None)

        # 2) Recent completed task (within 6 hours) with registered file: included with can_continue=True.
        now[0] = START + 5 * 3600
        recent_done = tasks.create(SCENE, "onebot:70001", "生成季度汇总", "Excel 表格", "ctx", "汇总 Q3 数据")
        tasks.start(SCENE, recent_done.id)
        file_rec = tasks.add_file(SCENE, recent_done.id, name="q3.xlsx", path="/deliveries/q3.xlsx", size=1024, note=None)
        now[0] = START + 5 * 3600 + 60
        tasks.finish(SCENE, recent_done.id, "done", "已生成季度汇总表格", None)

        # 3) Recent failed task with discarded workspace: included with can_continue=False and error.
        now[0] = START + 6 * 3600
        recent_failed = tasks.create(SCENE, "onebot:70002", "抓取接口文档", "Markdown", "ctx", "抓取文档")
        tasks.start(SCENE, recent_failed.id)
        tasks.finish(SCENE, recent_failed.id, "failed", None, "连接超时")
        tasks.add_event(SCENE, recent_failed.id, "workspace_discard", {"reason": "expired"})

        # 4) Active waiting_input task with progress and question.
        now[0] = START + 7 * 3600
        active_task = tasks.create(SCENE, "onebot:70001", "导出用户明细", "CSV 文件", "ctx", "按地区导出")
        tasks.start(SCENE, active_task.id)
        tasks.add_event(SCENE, active_task.id, "progress", {"text": "已拉取 80% 记录"})
        tasks.set_question(SCENE, active_task.id, {"id": "q-export", "kind": "info", "text": "按创建时间倒序吗？"})

        # Query at START + 7h + 600s: old_task ended > 7h ago (excluded); recent_done & recent_failed within 6h.
        query_now = START + 7 * 3600 + 600
        content = turn_state(config, store, now=query_now)["content"]

        active_entries = _extract_tag(content, "未完成工作")
        assert len(active_entries) == 1
        assert active_entries[0] == {
            "id": active_task.id,
            "requester": "onebot:70001",
            "status": "waiting_input",
            "goal": "导出用户明细",
            "deliverable": "CSV 文件",
            "question": {"id": "q-export", "kind": "info", "text": "按创建时间倒序吗？"},
            "latest_progress": "已拉取 80% 记录",
        }

        recent_entries = _extract_tag(content, "近期结束工作")
        assert [entry["id"] for entry in recent_entries] == [recent_failed.id, recent_done.id]
        assert old_task.id not in [entry["id"] for entry in recent_entries]
        assert recent_entries[1] == {
            "id": recent_done.id,
            "requester": "onebot:70001",
            "status": "done",
            "goal": "生成季度汇总",
            "can_continue": True,
            "files": [{"id": file_rec.id, "name": "q3.xlsx"}],
            "summary": "已生成季度汇总表格",
        }
        assert recent_entries[0] == {
            "id": recent_failed.id,
            "requester": "onebot:70002",
            "status": "failed",
            "goal": "抓取接口文档",
            "can_continue": False,
            "error": "连接超时",
        }

        # Without worker configured, <近期结束工作> is omitted while active tickets remain visible.
        config.worker = None
        no_worker_content = turn_state(config, store, now=query_now)["content"]
        assert "<未完成工作>" in no_worker_content
        assert "<近期结束工作>" not in no_worker_content


def test_turn_state_keeps_active_overflow_notice(tmp_path):
    config, _ = _instance(tmp_path)
    config.worker = _worker_settings(tmp_path)

    with Store(config.database, now=lambda: START) as store:
        tasks = TaskStore(store)
        for index in range(21):
            tasks.create(SCENE, "onebot:70001", f"任务 {index}", "结果", "ctx", f"执行 {index}")

        content = turn_state(config, store, now=START + 10)["content"]
        active_entries = _extract_tag(content, "未完成工作")
        assert len(active_entries) == 20
        assert "这里只列前20项；task可继续查看。" in content
