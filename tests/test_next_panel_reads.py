"""Panel reads must leave the message loop available while another connection writes."""

import asyncio
from contextlib import closing
import gc
import json
import sqlite3
import time

import pytest

from len_bot.next.chat.proactive import ProactiveStore
from len_bot.next.deployment import Deployment
from len_bot.next.learning.store import LearningStore
from len_bot.next.runtime.updater import Updater
from len_bot.next.storage.schema import business_script
from len_bot.next.storage.store import Store
from test_next_panel_acts_as_owner import exercise, write_instance, SCENE


@pytest.mark.parametrize('path,status', [
    ('/api/host/state', 200),
    ('/api/host/overview', 200),
    ('/api/host/usage', 200),
    ('/api/host/plugins', 200),
    (f'/api/host/schedules/proactive?scene={SCENE}', 200),
    (f'/api/host/scenes/{SCENE}/learning', 200),
    (f'/api/host/scenes/{SCENE}/learning/expressions', 200),
    (f'/api/host/tasks?scene={SCENE}', 200),
    (f'/api/host/scenes/{SCENE}/timeline', 200),
    (f'/api/host/scenes/{SCENE}/turns/missing', 404),
    (f'/api/host/scenes/{SCENE}/turns/missing/export', 404),
])
def test_panel_database_reads_do_not_block_the_loop(tmp_path, path, status):
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client):
        with sqlite3.connect(tmp_path / 'host.sqlite3') as blocker:
            # WAL: an open write transaction elsewhere no longer holds panel reads back at all.
            blocker.execute('BEGIN IMMEDIATE')
            # Late in the suite a full garbage collection pauses the loop longer than the bound on a slow
            # runner; it is kept out of the measured window.
            gc.collect()
            gc.disable()
            try:
                request = asyncio.create_task(client.get(path))
                started = time.perf_counter()
                await asyncio.sleep(0.03)
                delay = time.perf_counter() - started
            finally:
                gc.enable()
            response = await asyncio.wait_for(request, 2)
            blocker.rollback()
        assert delay < 0.1
        assert response.status_code == status, response.text
        if path == '/api/host/overview':
            cached = await client.get(path)
            assert cached.json() == response.json()

    exercise(tmp_path, check)


def test_slow_queries_use_indexes_without_full_table_scans():
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(business_script())

        def plan(sql: str, params: tuple) -> list[str]:
            return [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql, params)]

        wake_scene = plan(
            "WITH recent_turns AS MATERIALIZED (SELECT id,wake_channel FROM turns WHERE scene=? AND started>=? AND started<?) "
            "SELECT c.turn_id,c.tokens FROM recent_turns CROSS JOIN model_calls c ON c.turn_id=recent_turns.id WHERE c.role='mind'",
            (SCENE, 0.0, 100.0),
        )
        assert any('USING INDEX turns_scene_time' in step for step in wake_scene), wake_scene
        assert any('USING INDEX turn_calls' in step for step in wake_scene), wake_scene
        assert not any(step.startswith('SCAN model_calls') or step.startswith('SCAN turns') for step in wake_scene), wake_scene

        wake_all = plan(
            "WITH recent_turns AS MATERIALIZED (SELECT id,wake_channel FROM turns WHERE started>=? AND started<?) "
            "SELECT c.turn_id,c.tokens FROM recent_turns CROSS JOIN model_calls c ON c.turn_id=recent_turns.id WHERE c.role='mind'",
            (0.0, 100.0),
        )
        assert any('USING INDEX turns_started' in step for step in wake_all), wake_all
        assert any('USING INDEX turn_calls' in step for step in wake_all), wake_all

        known = plan(
            "SELECT COALESCE(NULLIF(json_extract(body,'$.sender.card'),''),json_extract(body,'$.sender.nickname')) "
            "FROM messages WHERE scene=? AND json_extract(body,'$.sender.uid')=? "
            "ORDER BY json_extract(body,'$.time') DESC, seq DESC LIMIT 1",
            (SCENE, 'onebot:70001'),
        )
        assert any('USING INDEX message_sender_time' in step for step in known), known
        assert not any(step.startswith('SCAN') or 'TEMP B-TREE' in step for step in known), known

        last_req = plan(
            "SELECT request FROM model_calls WHERE scene=? AND role='mind' AND plugin IS NULL AND turn_id IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (SCENE,),
        )
        assert any('USING INDEX model_call_mind_usage' in step for step in last_req), last_req
        assert not any(step.startswith('SCAN') or 'TEMP B-TREE' in step for step in last_req), last_req

        search_long = plan(
            "WITH hit(seq) AS MATERIALIZED (SELECT rowid FROM message_search WHERE search_text MATCH ? AND rowid<=?) "
            "SELECT m.seq,m.body FROM hit CROSS JOIN messages m ON m.seq=hit.seq WHERE m.scene=? "
            "ORDER BY json_extract(m.body,'$.time') DESC,m.seq DESC LIMIT ? OFFSET ?",
            ('"hello"', 1000, SCENE, 10, 0),
        )
        assert any('SEARCH m USING INTEGER PRIMARY KEY' in step for step in search_long), search_long
        assert not any(step.startswith('SCAN messages') for step in search_long), search_long

        search_short = plan(
            "WITH recent(seq,body) AS MATERIALIZED ("
            "SELECT m.seq,m.body FROM messages m WHERE m.scene=? AND +m.seq<=? "
            "ORDER BY json_extract(m.body,'$.time') DESC,m.seq DESC LIMIT ?"
            ") SELECT m.seq,m.body FROM recent m CROSS JOIN message_search s ON s.rowid=m.seq WHERE instr(s.search_text,?)>0 "
            "ORDER BY json_extract(m.body,'$.time') DESC,m.seq DESC LIMIT ? OFFSET ?",
            (SCENE, 1000, 5000, 'hi', 10, 0),
        )
        assert any('USING INDEX message_scene_time' in step for step in search_short), search_short
        assert not any(step.startswith('SCAN messages') for step in search_short), search_short

        search_short_who = plan(
            "WITH recent(seq,body) AS MATERIALIZED ("
            "SELECT m.seq,m.body FROM messages m WHERE m.scene=? AND +m.seq<=? AND json_extract(m.body,'$.sender.uid')=? "
            "ORDER BY json_extract(m.body,'$.time'),m.seq LIMIT ?"
            ") SELECT m.seq,m.body FROM recent m CROSS JOIN message_search s ON s.rowid=m.seq WHERE instr(s.search_text,?)>0 "
            "ORDER BY json_extract(m.body,'$.time'),m.seq LIMIT ? OFFSET ?",
            (SCENE, 1000, 'onebot:70001', 5000, '过敏', 10, 0),
        )
        assert any('USING INDEX message_sender_time' in step for step in search_short_who), search_short_who
        assert not any(step.startswith('SCAN messages') for step in search_short_who), search_short_who

        activity = plan(
            "SELECT received_at FROM messages WHERE scene=? AND raw IS NOT NULL AND received_at IS NOT NULL "
            "AND json_extract(body,'$.is_self')=0 ORDER BY received_at DESC, seq DESC LIMIT 1",
            (SCENE,),
        )
        assert any('USING INDEX message_scene_received' in step for step in activity), activity
        assert not any(step.startswith('SCAN') or 'TEMP B-TREE' in step for step in activity), activity


def test_proactive_route_reuses_single_last_activity_query(tmp_path, monkeypatch):
    write_instance(tmp_path, ['onebot:70001'])
    calls = 0
    original = ProactiveStore.last_activity

    def counted(self, scene, exclude_uids):
        nonlocal calls
        calls += 1
        return original(self, scene, exclude_uids)

    monkeypatch.setattr(ProactiveStore, 'last_activity', counted)

    async def check(client):
        response = await client.get(f'/api/host/schedules/proactive?scene={SCENE}')
        assert response.status_code == 200, response.text

    exercise(tmp_path, check)
    assert calls == 1


def test_expressions_page_scopes_disliked_to_current_page_items(tmp_path, monkeypatch):
    with Store(tmp_path / 'host.sqlite3') as store:
        learning = LearningStore(store)
        learning.initialize(SCENE, 0)
        batch = learning.begin(SCENE, 0, 1, {})
        learning.complete(batch, [(f'情境{i}', f'说法{i}', []) for i in range(5)], auto_adopt=True)
        requested_ids = []
        original = learning.disliked

        def spy(scene, since, *, expression_ids=None):
            requested_ids.append(list(expression_ids) if expression_ids is not None else None)
            return original(scene, since, expression_ids=expression_ids)

        monkeypatch.setattr(learning, 'disliked', spy)
        page = learning.expressions(SCENE, status='adopted', limit=2, offset=0)
        assert len(page['items']) == 2
        assert requested_ids == [[item['id'] for item in page['items']]]
        empty = learning.expressions(SCENE, status='rejected', limit=2, offset=0)
        assert empty['items'] == [] and len(requested_ids) == 1


@pytest.mark.asyncio
async def test_updater_prechecks_disk_space_before_downloading(tmp_path, monkeypatch):
    from collections import namedtuple
    from test_updater import Files, _bundle, _install, _manifest, _release

    deployment = Deployment('package', tmp_path)
    _install(deployment, '0.1.0')
    deployment.select('0.1.0')
    bundle = _bundle('0.2.0', 'linux-x64')
    assets = {'lenbot-0.2.0-linux-x64.tar.gz': bundle}
    manifest = _manifest('0.2.0', assets, 'linux-x64')
    Usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr('len_bot.next.runtime.updater.shutil.disk_usage', lambda _: Usage(10**9, 10**9 - 1024, 1024))

    async def exit_for_update():
        raise AssertionError('not reached')

    with Files({**assets, 'release-manifest.json': json.dumps(manifest).encode()}) as files:
        updater = Updater(deployment, '0.1.0', exit_for_update=exit_for_update)
        updater.start(_release(files, '0.2.0', manifest), plugins=False)
        await updater.task
    assert updater.state()['stage'] == 'failed'
    assert '磁盘空间' in updater.state()['error']
    assert not deployment.installed('0.2.0')


def test_short_query_search_pushes_down_filters_and_direction(tmp_path, monkeypatch):
    from len_bot.next.platform.messages import ChatMessage, Segment, Sender
    from len_bot.next.storage import store as store_module

    monkeypatch.setattr(store_module, 'SHORT_QUERY_SCAN_LIMIT', 3)
    with Store(tmp_path / 'host.sqlite3') as store:
        for index in range(1, 8):
            uid = 'onebot:rare' if index == 1 else 'onebot:chatty'
            text = '花生过敏记录' if index in (1, 7) else f'普通闲聊消息 {index}'
            msg = ChatMessage(
                id=f'm-{index}', platform='onebot', bot_id='onebot:90001', scene=SCENE,
                platform_message_id=f'm-{index}', sender=Sender(uid, '群友', None, None),
                time=float(index * 10), segments=[Segment('text', {'text': text})],
                reply_to=None, mentions_bot=False, is_self=False, send_status='received',
            )
            store.enqueue(msg, {}, float(index * 10))
        snap = store.max_message_seq(SCENE)
        # Sender filter finds seq=1 despite 6 newer messages exceeding SHORT_QUERY_SCAN_LIMIT=3.
        by_who = store.search_messages(
            SCENE, query='过敏', who='onebot:rare', after=None, before=None,
            snapshot=snap, offset=0, limit=10, order='newest',
        )
        assert [seq for seq, _ in by_who] == [1]
        # Time window filter finds seq=1 in [5, 25).
        by_window = store.search_messages(
            SCENE, query='过敏', who=None, after=5.0, before=25.0,
            snapshot=snap, offset=0, limit=10, order='newest',
        )
        assert [seq for seq, _ in by_window] == [1]
        # Oldest ordering scans from earliest messages first.
        oldest = store.search_messages(
            SCENE, query='过敏', who=None, after=None, before=None,
            snapshot=snap, offset=0, limit=1, order='oldest',
        )
        assert [seq for seq, _ in oldest] == [1]


def test_egress_status_does_not_mutate_in_memory_day_cache(tmp_path):
    from types import SimpleNamespace
    from len_bot.next.work.egress_usage import EgressUsage
    from len_bot.next.work.store import TaskStore

    with Store(tmp_path / 'host.sqlite3') as store:
        cfg = SimpleNamespace(
            scene_timezone=lambda _scene: 'UTC',
            worker=SimpleNamespace(egress=SimpleNamespace(
                max_task_bytes=10_000, max_scene_daily_bytes=50_000,
                max_task_upload_bytes=5_000, enabled=True, mode='allowlist',
            )),
            scenes={SCENE: SimpleNamespace(tasks=SimpleNamespace(
                egress_max_task_bytes=None, egress_max_daily_bytes=None,
            ))},
        )
        usage = EgressUsage(cfg, TaskStore(store), lambda _scene: None)
        usage._scene_days[(SCENE, '1999-01-01')] = [12, 34]
        state = usage.status(SCENE)
        assert state['up'] == 0 and state['down'] == 0
        # Read-only status query must neither insert the new day key nor delete older keys in _scene_days.
        assert list(usage._scene_days.keys()) == [(SCENE, '1999-01-01')]


def test_short_query_search_finds_two_char_chinese_word_beyond_5000_messages(tmp_path):
    from dataclasses import asdict
    from len_bot.next.platform.messages import ChatMessage, Segment, Sender
    from len_bot.next.storage.codec import encode

    with Store(tmp_path / 'host.sqlite3') as store:
        def make_msg(index: int, text: str, at: float) -> ChatMessage:
            return ChatMessage(
                id=f'm-{index}', platform='onebot', bot_id='onebot:90001', scene=SCENE,
                platform_message_id=f'm-{index}', sender=Sender('onebot:70001', '群友', None, None),
                time=at, segments=[Segment('text', {'text': text})],
                reply_to=None, mentions_bot=False, is_self=False, send_status='received',
            )

        # Insert 5,050 filler messages after two early hits (sharing a timestamp to also verify seq tie-break).
        total = 5052
        message_rows = []
        search_rows = []
        for index in range(1, total + 1):
            if index == 1:
                text, at = '以前买过苹果很好吃', 100.0
            elif index == 2:
                text, at = '同秒也提到了苹果', 100.0
            elif index == total:
                text, at = '最新一条也有苹果', float(index * 10)
            else:
                text, at = f'普通闲聊记录编号 {index}', float(index * 10)
            body = encode(asdict(make_msg(index, text, at)))
            message_rows.append((index, SCENE, f'm-{index}', body, '{}', at))
            search_rows.append((index, text))
        with store.db as db:
            db.executemany(
                'INSERT INTO messages(seq,scene,platform_id,body,raw,received_at) VALUES (?,?,?,?,?,?)',
                message_rows,
            )
            db.executemany(
                'INSERT INTO message_search(rowid,search_text) VALUES (?,?)',
                search_rows,
            )

        snap = store.max_message_seq(SCENE)
        newest = store.search_messages(
            SCENE, query='苹果', who=None, after=None, before=None,
            snapshot=snap, offset=0, limit=10, order='newest',
        )
        assert [seq for seq, _ in newest] == [total, 2, 1]

        paged = store.search_messages(
            SCENE, query='苹果', who=None, after=None, before=None,
            snapshot=snap, offset=1, limit=2, order='newest',
        )
        assert [seq for seq, _ in paged] == [2, 1]

        oldest = store.search_messages(
            SCENE, query='苹果', who=None, after=None, before=None,
            snapshot=snap, offset=0, limit=10, order='oldest',
        )
        assert [seq for seq, _ in oldest] == [1, 2, total]


@pytest.mark.asyncio
async def test_host_state_tolerates_concurrent_scene_add_and_remove(tmp_path):
    from copy import deepcopy
    from test_host_stream import login, panel

    async with panel(tmp_path) as (runtime, client, _):
        await login(client)
        added_scene = 'onebot:group:80099'
        saved_scene_cfg = deepcopy(runtime.config.scenes[SCENE])
        saved_chat = runtime.chats[SCENE]
        saved_runner = runtime.runners[SCENE]
        original_read = runtime.store.read
        mutated = False

        async def read_with_scene_churn(fn, *args, **kwargs):
            nonlocal mutated
            # Mutate config.scenes, runtime.chats, and runtime.runners while store.read executes in its worker thread.
            task = asyncio.create_task(original_read(fn, *args, **kwargs))
            if not mutated:
                mutated = True
                runtime.config.scenes[added_scene] = saved_scene_cfg
                runtime.config.scenes.pop(SCENE, None)
                runtime.chats.pop(SCENE, None)
                runtime.runners.pop(SCENE, None)
            return await task

        runtime.store.read = read_with_scene_churn
        try:
            response = await client.get('/api/host/state')
        finally:
            runtime.store.read = original_read
            runtime.config.scenes.pop(added_scene, None)
            runtime.config.scenes[SCENE] = saved_scene_cfg
            runtime.chats[SCENE] = saved_chat
            runtime.runners[SCENE] = saved_runner

        assert response.status_code == 200, response.text
        body = response.json()
        assert [item['scene'] for item in body['scenes']] == [SCENE]
