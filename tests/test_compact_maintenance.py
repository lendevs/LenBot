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
