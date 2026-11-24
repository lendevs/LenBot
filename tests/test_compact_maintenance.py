"""Stopped-instance compaction expires old snapshots and shrinks SQLite files via VACUUM INTO."""

from contextlib import closing
import json
import sqlite3

from len_bot.next.maintenance.compact import compact_instance
from len_bot.next.maintenance.upgrade import migrate_business_database
from len_bot.next.storage.schema import business_script
from len_bot.next.storage.store import FORMAT_VERSION, Store


def test_compact_shrinks_format_3_database_before_upgrade_and_preserves_anchors(tmp_path):
    root = tmp_path / 'instance'
    root.mkdir()
    db_path = root / 'data' / 'state.sqlite3'
    db_path.parent.mkdir(parents=True)
    (root / 'lenbot.config.json').write_text(json.dumps({
        'database': 'data/state.sqlite3',
        'retention': {'request_days': 7},
    }), encoding='utf-8')

    # Build a pre-upgrade format 3 database bloated with old multi-megabyte request snapshots.
    script = business_script().replace('frames INTEGER NOT NULL DEFAULT 1, ', '')
    now = 100 * 86400.0
    big_payload = json.dumps({'messages': [{'role': 'user', 'content': 'x' * 80000}], 'provider': 'p', 'settings': {}})
    with closing(sqlite3.connect(db_path)) as db:
        db.executescript('PRAGMA application_id=1279413809; PRAGMA user_version=3;\n' + script)
        with db:
            for index in range(30):
                db.execute(
                    "INSERT INTO model_calls(role,started,ended,request,response,scene,plugin) "
                    "VALUES ('upkeep',1,2,?,'{\"raw\":1}','onebot:group:80001',NULL)",
                    (big_payload,),
                )
            anchor_id = db.execute(
                "INSERT INTO model_calls(role,started,ended,request,response,scene,plugin) "
                "VALUES ('mind',1,2,?,'{\"raw\":1}','onebot:group:80001',NULL)",
                (big_payload,),
            ).lastrowid

    before_size = db_path.stat().st_size
    assert before_size > 2_000_000

    preview = compact_instance(root, dry_run=True, now=now)
    assert preview['dry_run'] is True

    result = compact_instance(root, now=now)
    after_size = db_path.stat().st_size
    assert result['status'] == 'ok'
    assert result['databases'][0]['expired']['model_snapshots'] == 30
    assert after_size < before_size // 3

    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
        kept = json.loads(db.execute('SELECT request FROM model_calls WHERE id=?', (anchor_id,)).fetchone()[0])
        assert 'messages' in kept and 'snapshot_expired_at' not in kept

    # Subsequent upgrade to format 4 succeeds cleanly on the compacted database.
    assert migrate_business_database(db_path)
    with Store(db_path) as store:
        assert store.db.execute('PRAGMA user_version').fetchone()[0] == FORMAT_VERSION


def test_compact_with_retention_null_skips_snapshot_expiry_unless_request_days_passed(tmp_path):
    root = tmp_path / 'instance'
    root.mkdir()
    db_path = root / 'data' / 'state.sqlite3'
    db_path.parent.mkdir(parents=True)
    (root / 'lenbot.config.json').write_text(json.dumps({
        'database': 'data/state.sqlite3',
        'retention': None,
    }), encoding='utf-8')

    now = 100 * 86400.0
    big_payload = json.dumps({'messages': [{'role': 'user', 'content': 'x' * 20000}], 'provider': 'p', 'settings': {}})
    with Store(db_path) as store:
        with store.db as db:
            for _ in range(10):
                db.execute(
                    "INSERT INTO model_calls(role,started,ended,request,response,scene,plugin) "
                    "VALUES ('upkeep',1,2,?,'{\"raw\":1}','onebot:group:80001',NULL)",
                    (big_payload,),
                )
            anchor_id = db.execute(
                "INSERT INTO model_calls(role,started,ended,request,response,scene,plugin) "
                "VALUES ('mind',1,2,?,'{\"raw\":1}','onebot:group:80001',NULL)",
                (big_payload,),
            ).lastrowid

    # retention: null without --request-days only runs safe VACUUM INTO and never expires snapshots.
    kept_result = compact_instance(root, now=now)
    assert kept_result['status'] == 'ok'
    assert kept_result['databases'][0]['expired'] == {}
    with closing(sqlite3.connect(db_path)) as db:
        unexpired = db.execute(
            "SELECT COUNT(*) FROM model_calls WHERE json_extract(request,'$.messages') IS NOT NULL "
            "AND json_extract(request,'$.snapshot_expired_at') IS NULL"
        ).fetchone()[0]
        assert unexpired == 11

    # Explicitly passing request_days=7 expires old upkeep snapshots while preserving the mind anchor.
    expired_result = compact_instance(root, request_days=7, now=now)
    assert expired_result['status'] == 'ok'
    assert expired_result['databases'][0]['expired']['model_snapshots'] == 10
    with closing(sqlite3.connect(db_path)) as db:
        kept = json.loads(db.execute('SELECT request FROM model_calls WHERE id=?', (anchor_id,)).fetchone()[0])
        assert 'messages' in kept and 'snapshot_expired_at' not in kept
        remaining = db.execute(
            "SELECT COUNT(*) FROM model_calls WHERE json_extract(request,'$.snapshot_expired_at') IS NOT NULL"
        ).fetchone()[0]
        assert remaining == 10


def test_retention_drain_stops_before_second_batch_when_policy_disabled_or_changed(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from len_bot.next.runtime.retention import Retention, RetentionSettings

    now = 150 * 86400.0
    config = SimpleNamespace(database=tmp_path / 'retention.sqlite3', retention=RetentionSettings(request_days=7), scenes={})
    with Store(config.database, now=lambda: now) as store:
        with store.db as db:
            for idx in range(250):
                db.execute(
                    "INSERT INTO model_calls(role,started,ended,request,response,scene,plugin) "
                    """VALUES ('upkeep',0,?,'{"messages":[1]}','{}','onebot:group:80001',NULL)""",
                    (10 + idx,),
                )
        runtime = SimpleNamespace(store=store, config=config, stopped=asyncio.Event())
        work = Retention(runtime)
        original_apply = work._apply_batch
        calls = 0

        def apply_then_disable(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original_apply(*args, **kwargs)
            config.retention = None
            return result

        work._apply_batch = apply_then_disable
        drained = work.batch(drain=True)
        assert calls == 1
        assert drained['model_snapshots'] == 100
        expired_count = store.db.execute(
            "SELECT COUNT(*) FROM model_calls WHERE json_extract(request,'$.snapshot_expired_at') IS NOT NULL"
        ).fetchone()[0]
        assert expired_count == 100

        # Changing policy parameters mid-drain also stops before the next batch under stale settings.
        config.retention = RetentionSettings(request_days=7)
        calls = 0

        def apply_then_change(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original_apply(*args, **kwargs)
            config.retention = RetentionSettings(request_days=30)
            return result

        work._apply_batch = apply_then_change
        drained_again = work.batch(drain=True)
        assert calls == 1
        assert drained_again['model_snapshots'] == 100
        expired_count = store.db.execute(
            "SELECT COUNT(*) FROM model_calls WHERE json_extract(request,'$.snapshot_expired_at') IS NOT NULL"
        ).fetchone()[0]
        assert expired_count == 200
