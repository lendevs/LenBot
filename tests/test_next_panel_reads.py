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
            "WITH recent(seq,body) AS MATERIALIZED (SELECT seq,body FROM messages WHERE scene=? AND seq<=? ORDER BY seq DESC LIMIT ?) "
            "SELECT m.seq,m.body FROM recent m CROSS JOIN message_search s ON s.rowid=m.seq WHERE instr(s.search_text,?)>0 "
            "ORDER BY json_extract(m.body,'$.time') DESC,m.seq DESC LIMIT ? OFFSET ?",
            (SCENE, 1000, 5000, 'hi', 10, 0),
        )
        assert any('USING INDEX message_scene_seq' in step for step in search_short), search_short
        assert not any(step.startswith('SCAN messages') for step in search_short), search_short

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
