"""A failed retention batch keeps its error for display and is retried with a growing delay, not skipped."""

import asyncio
from types import SimpleNamespace

import pytest

from len_bot.next.runtime import retention
from len_bot.next.runtime.retention import PERIOD_SECONDS, RETRY_SECONDS, Retention

EMPTY = {key: 0 for key in ('model_snapshots', 'auxiliary_snapshots', 'task_snapshots', 'turns', 'messages',
                            'notices', 'memory_snapshots', 'extraction_jobs')}


class Clock:
    """Stands in for the wait between cycles: records each delay and releases the loop at once."""

    def __init__(self, runtime, stop_after):
        self.delays, self.runtime, self.stop_after = [], runtime, stop_after

    async def wait(self, tasks, *, timeout, return_when):
        self.delays.append(timeout)
        if len(self.delays) >= self.stop_after:
            self.runtime.stopped.set()
        await asyncio.sleep(0)
        return set(), set(tasks)


def fixture(monkeypatch, outcomes, stop_after):
    runtime = SimpleNamespace(stopped=asyncio.Event(), config=SimpleNamespace(retention=object()),
                              notify=lambda: None, _emit=lambda event: events.append(event))
    events = []
    work = Retention(runtime)
    results = iter(outcomes)

    async def batch_async(*, preview=False, drain=False):
        outcome = next(results)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    work.batch_async = batch_async
    clock = Clock(runtime, stop_after)
    monkeypatch.setattr(retention.asyncio, 'wait', clock.wait)
    return work, clock, events


@pytest.mark.asyncio
async def test_failed_batch_is_retried_with_doubling_delay_and_error_clears_on_success(monkeypatch):
    failure = OSError('disk full')
    work, clock, events = fixture(monkeypatch, [failure, failure, failure, EMPTY, EMPTY], 5)
    await asyncio.wait_for(work.run(), 5)
    assert clock.delays == [RETRY_SECONDS, RETRY_SECONDS * 2, RETRY_SECONDS * 4, PERIOD_SECONDS, PERIOD_SECONDS]
    assert [event['error'] for event in events] == ['OSError: disk full'] * 3
    assert work.error is None and work.retry is None


@pytest.mark.asyncio
async def test_error_stays_visible_until_a_batch_succeeds_and_delay_is_capped(monkeypatch):
    failure = OSError('locked')
    work, clock, _ = fixture(monkeypatch, [failure] * 12, 12)
    await asyncio.wait_for(work.run(), 5)
    assert work.error == 'OSError: locked'
    assert clock.delays[0] == RETRY_SECONDS and max(clock.delays) == PERIOD_SECONDS
    assert clock.delays == sorted(clock.delays)


@pytest.mark.asyncio
async def test_wake_restarts_the_backoff(monkeypatch):
    work, _, _ = fixture(monkeypatch, [], 1)
    work.error, work.retry = 'OSError: locked', RETRY_SECONDS * 8
    work.wake()
    assert work.error is None and work.retry is None and work.changed.is_set()


def test_retention_seeks_past_anchors_and_expires_out_of_order_calls(tmp_path, caplog):
    from len_bot.next.storage.store import Store
    from len_bot.next.runtime.retention import RetentionSettings

    now = 150 * 86400
    scene = 'onebot:group:80001'
    config = SimpleNamespace(database=tmp_path / 'test.db', retention=RetentionSettings(), scenes={})
    with Store(config.database, now=lambda: now) as store:
        work = Retention(SimpleNamespace(store=store, config=config, stopped=asyncio.Event()))
        with store.db as db:
            def call(role, ended, scene=scene, turn=None, plugin=None):
                return db.execute(
                    "INSERT INTO model_calls(role,started,ended,request,response,scene,turn_id,plugin) "
                    """VALUES (?,0,?,'{"messages":[1]}','{}',?,?,?)""",
                    (role, ended, scene, turn, plugin)).lastrowid

            # A page of anchors ends first. Later pages finish in reverse insertion order.
            expected = {call('upkeep', 10 + (index % 3)) for index in range(215)}
            expected.add(call('mind', 10))
            anchors = {call('mind', 1, f'onebot:group:archived{idx}') for idx in range(106)}
            db.execute("INSERT INTO turns(id,scene,started,ended,status) VALUES ('latest',?,0,1,'done')", (scene,))
            anchors.add(call('mind', 1, turn='latest'))
            plugin = call('mind', now - 10 * 86400, plugin='notes')
            expected.add(plugin)
            db.execute("INSERT INTO turns(id,scene,started,status) VALUES ('active',?,0,'running')", (scene,))
            active = call('upkeep', 1, turn='active')
            unfinished = call('upkeep', None)

        caplog.set_level('INFO', logger=retention.__name__)
        preview = work.batch(preview=True)
        assert preview['model_snapshots'] == 100 and preview['protected_latest_mind_requests'] == len(anchors)
        assert not caplog.records
        result = work.batch(drain=True)
        assert result['model_snapshots'] == len(expected)
        assert caplog.records[-1].event == 'retention_finished'
        assert caplog.records[-1].fields['model_snapshots'] == len(expected)
        assert {row[0] for row in store.db.execute(
            "SELECT id FROM model_calls WHERE json_extract(request,'$.snapshot_expired_at') IS NOT NULL AND response IS NULL"
        )} == expected
        assert {row[0] for row in store.db.execute(
            "SELECT id FROM model_calls WHERE json_extract(request,'$.messages') IS NOT NULL"
        )} == anchors | {active, unfinished}
        assert store.db.execute("SELECT COUNT(*) FROM turns WHERE id='latest'").fetchone()[0] == 1
        caplog.clear()
        assert work.batch(drain=True)['model_snapshots'] == 0
        assert not caplog.records


def test_plugin_only_backlog_drains_all_pages_and_keeps_pending_events(tmp_path):
    from len_bot.next.storage.store import Store
    from len_bot.next.runtime.retention import RetentionSettings

    now = 150 * 86400
    config = SimpleNamespace(database=tmp_path / 'test.db', retention=RetentionSettings(), scenes={})
    with Store(config.database, now=lambda: now) as store:
        work = Retention(SimpleNamespace(store=store, config=config, stopped=asyncio.Event()))
        with store.db as db:
            for seq in range(241):
                db.execute("INSERT INTO model_calls(scene,role,plugin,started,ended,request) "
                           """VALUES ('onebot:group:1','mind','notes',0,?,'{"snapshot_expired_at":1}')""", (seq,))
                db.execute("INSERT INTO plugin_events(scene,plugin,kind,content,created,delivered_at) "
                           "VALUES ('onebot:group:1','notes','event','old',0,?)", (seq,))
            for content, created, delivered in [('pending', 0, None), ('recent', now, now)]:
                db.execute("INSERT INTO plugin_events(scene,plugin,kind,content,created,delivered_at) "
                           "VALUES ('onebot:group:1','notes','event',?,?,?)", (content, created, delivered))
        preview = work.batch(preview=True)
        assert preview['plugin_calls'] == preview['plugin_events'] == 100
        result = work.batch(drain=True)
        assert result['plugin_calls'] == result['plugin_events'] == 241
        assert store.db.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 0
        assert {row[0] for row in store.db.execute('SELECT content FROM plugin_events')} == {'pending', 'recent'}


def test_retention_uses_active_entry_time_after_compaction(tmp_path):
    from len_bot.next.storage.store import Store
    from len_bot.next.runtime.retention import RetentionSettings
    from test_plugin_memory_boundary import GROUP, receive

    config = SimpleNamespace(database=tmp_path / 'test.db', retention=RetentionSettings(message_days={GROUP: 1}), scenes={})
    with Store(config.database, now=lambda: 5 * 86400) as store:
        work = Retention(SimpleNamespace(store=store, config=config))
        for seq, at in enumerate((10, 20, 30, 40, 50)):
            receive(store, GROUP, seq, at)
        with store.db as db:
            db.execute('INSERT INTO mind_sessions(scene,last_message_seq) VALUES (?,4)', (GROUP,))
            for seq, at in [(100, 11), (200, 30)]:
                db.execute("INSERT INTO mind_entries(seq,scene,created,message) VALUES (?,?,?,'{}')", (seq, GROUP, at))
        assert work.batch(preview=True)['messages'] == 0
        with store.db as db:
            db.execute('UPDATE mind_sessions SET compact_through=100 WHERE scene=?', (GROUP,))
        assert work.batch()['messages'] == 2
        assert [row[0] for row in store.db.execute('SELECT seq FROM messages ORDER BY seq')] == [3, 4, 5]


def test_retention_preserves_quiet_held_message_batched_after_compaction(tmp_path):
    from len_bot.next.platform.messages import render_batch
    from len_bot.next.storage.store import Store
    from len_bot.next.runtime.retention import RetentionSettings
    from test_plugin_memory_boundary import GROUP, receive

    now = 5 * 86400
    config = SimpleNamespace(database=tmp_path / 'test.db', retention=RetentionSettings(message_days={GROUP: 1}), scenes={})
    with Store(config.database, now=lambda: now) as store:
        work = Retention(SimpleNamespace(store=store, config=config))
        m1 = receive(store, GROUP, 1, 10)
        m2 = receive(store, GROUP, 2, 20)
        # m3 arrives during quiet/paused window at T1=25 (< now - 86400), before compaction at t=30,
        # and is only batched into active mind_entries (seq=200 > compact_through=100) at T2=now.
        m3 = receive(store, GROUP, 3, 25)
        m4 = receive(store, GROUP, 4, now)
        with store.db as db:
            db.execute('INSERT INTO mind_sessions(scene,compact_through,last_message_seq) VALUES (?,100,4)', (GROUP,))
            first_batch = render_batch([(m1, None, {}), (m2, None, {})], timezone='UTC')
            second_batch = render_batch([(m3, None, {}), (m4, None, {})], timezone='UTC')
            db.execute("INSERT INTO mind_entries(seq,scene,created,message) VALUES (100,?,30,?)",
                       (GROUP, retention.encode({'role': 'user', 'content': first_batch})))
            db.execute("INSERT INTO mind_entries(seq,scene,created,message) VALUES (200,?,?,?)",
                       (GROUP, now, retention.encode({'role': 'user', 'content': second_batch})))
        assert work.batch()['messages'] == 2
        assert [row[0] for row in store.db.execute('SELECT seq FROM messages ORDER BY seq')] == [3, 4]
