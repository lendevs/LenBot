"""Instances written by released-format code upgrade to exactly what a fresh instance creates.

Fixtures come from scripts/build_history_fixtures.py, which runs the old commits' own code.
"""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import shutil
import sqlite3
import regex

import pytest

from len_bot.next.chat.schedule_store import ScheduleStore
from len_bot.next.config import CONFIG_VERSION
from len_bot.next.maintenance.doctor import check
from len_bot.next.maintenance.upgrade import migrate_instance
from len_bot.next.memory.jobs import MemoryJobs
from len_bot.next.memory.local import FORMAT_VERSION as LOCAL_FORMAT_VERSION, LocalMemory, LocalMemorySettings
from len_bot.next.storage.codec import decode_message
from len_bot.next.storage.store import Store
from len_bot.next.runtime.retention import expire_request
from len_bot.next.work.store import TaskStore, _task

HISTORY = Path(__file__).parent / 'fixtures' / 'history'
FIXTURES = sorted(path.name for path in HISTORY.iterdir() if path.is_dir())
SCENE = 'onebot:group:80001'


def _schema(path: Path) -> list[tuple]:
    """Every table, index and trigger with its columns; SQL text normalized for whitespace."""
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                          "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        result = []
        for kind, name, table, sql in rows:
            columns = None
            constraints = None
            if kind == 'table':
                columns = sorted(tuple(row[1:]) for row in db.execute(f'PRAGMA table_xinfo("{name}")'))
                checks = sorted(re.sub(r'\s+', ' ', check).strip() for check in
                                regex.findall(r'\bCHECK\s*(\((?:[^()]|(?1))*\))', sql or '', flags=regex.I))
                foreign_keys = sorted(tuple(row[1:]) for row in db.execute(f'PRAGMA foreign_key_list("{name}")'))
                unique = sorted(tuple(col[2] for col in db.execute(f'PRAGMA index_info("{index[1]}")'))
                                for index in db.execute(f'PRAGMA index_list("{name}")') if index[2] and index[3] == 'u')
                constraints = checks, foreign_keys, unique
                sql = None  # ALTER TABLE leaves different text for the same columns.
            result.append((kind, name, table, None if sql is None else re.sub(r'\s+', ' ', sql), columns, constraints))
        identity = (db.execute('PRAGMA application_id').fetchone()[0], db.execute('PRAGMA user_version').fetchone()[0])
    return [identity, *result]


def _fresh(root: Path) -> Path:
    fresh = root.parent / 'fresh'
    fresh.mkdir()
    Store(fresh / 'state.db').db.close()
    MemoryJobs(fresh / 'state.db.memory.sqlite3').close()
    LocalMemory(LocalMemorySettings(directory=fresh / 'memory'))
    return fresh


@pytest.mark.parametrize('fixture', FIXTURES)
def test_history_fixture_upgrades_to_the_fresh_schema_and_every_body_decodes(tmp_path, fixture):
    root = tmp_path / 'instance'
    shutil.copytree(HISTORY / fixture, root)
    migrate_instance(root)

    fresh = _fresh(root)
    for name in ('state.db', 'state.db.memory.sqlite3', 'memory/.memory-index.sqlite3'):
        assert _schema(root / name) == _schema(fresh / name), name
    assert json.loads((root / 'lenbot.config.json').read_text())['config_version'] == CONFIG_VERSION

    with Store(root / 'state.db') as store:
        bodies = [row[0] for row in store.db.execute('SELECT body FROM messages')]
        assert [decode_message(body).segments[0].data['text'] for body in bodies] == ['明天提醒我交报告', '收到']
        tasks = [_task(row) for row in store.db.execute('SELECT * FROM tasks')]
        assert [(task.status, task.summary) for task in tasks] == [('done', '完成')]
        assert [file.name for file in TaskStore(store).list_files(SCENE, tasks[0].id)] == ['report.md']
        schedules = ScheduleStore(store).list_schedules(SCENE)
        assert [schedule.target for schedule in schedules] == ['onebot:70001']
        tokens = [json.loads(row[0]) for row in store.db.execute('SELECT tokens FROM model_calls')]
        assert all(record is not None for record in tokens)
        event = json.loads(store.db.execute("SELECT body FROM task_events WHERE kind='model_call'").fetchone()[0])
        assert 'cost' not in event['response'] and event['response']['tokens'] is not None
    with MemoryJobs(root / 'state.db.memory.sqlite3') as jobs:
        assert jobs.latest(SCENE)['details']['calls'][0]['tokens'] is not None

    summaries = root / 'memory/scenes/onebot-group-80001'
    assert not (summaries / '.abstract.md').exists() and (summaries / 'people.md').exists()
    assert all(item['status'] != 'error' for item in check(root)), check(root)
    assert not list(root.rglob('*.v[0-9]*.bak')), 'the upgrade command relies on its snapshot, not per-file copies'


def test_local_index_starts_only_from_an_empty_file_or_its_own_format(tmp_path):
    directory = tmp_path / 'memory'
    directory.mkdir()
    with closing(sqlite3.connect(directory / '.memory-index.sqlite3')) as db:
        db.execute('PRAGMA user_version=3')
    with pytest.raises(ValueError, match='application_id=0, user_version=3'):
        LocalMemory(LocalMemorySettings(directory=directory))
    (directory / '.memory-index.sqlite3').unlink()
    LocalMemory(LocalMemorySettings(directory=directory))
    assert _schema(directory / '.memory-index.sqlite3')[0] == (0x4C424D31, LOCAL_FORMAT_VERSION)


def test_wake_migration_keeps_expired_requests_as_unknown(tmp_path):
    root = tmp_path / 'instance'
    shutil.copytree(HISTORY / 'config0-business4-jobs6-index3', root)
    with closing(sqlite3.connect(root / 'state.db')) as db:
        call_id, request = db.execute("SELECT id,request FROM model_calls WHERE role='mind'").fetchone()
        expired = expire_request(json.loads(request), 1_790_000_100)
        db.execute('UPDATE model_calls SET request=?,response=NULL WHERE id=?', (json.dumps(expired), call_id))
        db.commit()
    migrate_instance(root)
    with Store(root / 'state.db') as store:
        assert store.recent_turns(SCENE)[0]['wake_channel'] == 'unknown'


@pytest.mark.parametrize('fixture', FIXTURES)
def test_fixture_names_match_the_formats_they_contain(fixture):
    """Audit D-3: a fixture called configN must carry config_version N (missing means 0)."""
    config, business = re.match(r'config(\d+)-business(\d+)-', fixture).groups()
    saved = json.loads((HISTORY / fixture / 'lenbot.config.json').read_text(encoding='utf-8'))
    assert saved.get('config_version', 0) == int(config)
    with sqlite3.connect(HISTORY / fixture / 'state.db') as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == int(business)


def test_documented_business_format_matches_the_code():
    """Audit F-1: the operations guide names the current business format."""
    from len_bot.next.storage.store import FORMAT_VERSION
    repo = Path(__file__).parents[1]
    operations = (repo / 'deploy' / 'current' / 'operations.md').read_text(encoding='utf-8')
    assert f'目前是格式 {FORMAT_VERSION}。' in operations
    assert f'业务数据库从格式 {FORMAT_VERSION - 1} 升级到 {FORMAT_VERSION} 时' in operations


def test_verdict_migration_keeps_old_messages_unknown_and_replay_unchanged(tmp_path):
    from len_bot.next.maintenance.replay_attention import replay
    root = tmp_path / 'instance'
    shutil.copytree(HISTORY / 'config0-business6-jobs6-index3', root)
    def replay_fixture():
        with closing(sqlite3.connect(root / 'state.db')) as db:
            return replay(db, 1_790_000_000, 1_800_000_000, scene=SCENE, timezone='UTC', aliases=['报告'])
    before = replay_fixture()
    migrate_instance(root)
    assert replay_fixture() == before
    with Store(root / 'state.db') as store:
        assert [row[0] for row in store.db.execute('SELECT wake_verdict FROM messages')] == [None, None]


@pytest.mark.parametrize('fixture', FIXTURES)
def test_source_upgrade_snapshots_old_formats_and_doctor_lists_every_component(tmp_path, fixture):
    from len_bot.next.maintenance.upgrade import upgrade_instance
    from len_bot.next.maintenance.snapshot import verify
    root, backup = tmp_path / 'instance', tmp_path / 'backup'
    shutil.copytree(HISTORY / fixture, root)
    before = (root / 'lenbot.config.json').read_bytes()
    results = check(root)
    assert {'config', 'business_database', 'memory_jobs', 'local_memory_index', 'plugins'} == {item['check'] for item in results}
    assert (root / 'lenbot.config.json').read_bytes() == before
    upgrade_instance(root, backup)
    assert verify(backup)
    assert (backup / '0/lenbot.config.json').read_bytes() == before
    assert all(item['status'] in {'ok', 'disabled'} for item in check(root))
    assert not list(root.rglob('*.bak'))


def test_source_upgrade_restores_partial_migrations_and_external_persona(tmp_path):
    from len_bot.next.maintenance.upgrade import upgrade_instance
    from len_bot.next.maintenance.snapshot import manifest
    root, backup = tmp_path / 'instance', tmp_path / 'backup'
    shutil.copytree(HISTORY / 'config0-business4-jobs6-index3', root)
    external = tmp_path / 'external-persona'
    shutil.move(root / 'role', external)
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['scenes'][SCENE]['persona'] = str(external)
    path.write_text(json.dumps(source))
    # The local index fails after configuration, business and job migrations have already completed.
    with sqlite3.connect(root / 'memory/.memory-index.sqlite3') as db:
        db.execute('PRAGMA application_id=123')
    before, outside = manifest(root), manifest(external)
    with pytest.raises(ValueError):
        upgrade_instance(root, backup)
    assert manifest(root) == before
    assert manifest(external) == outside
    assert (backup / 'snapshot.json').exists()


def test_failed_trial_upgrade_restores_both_instances_and_preserves_trial_lock(tmp_path):
    from len_bot.next.maintenance.snapshot import manifest
    from len_bot.next.maintenance.upgrade import upgrade_instance
    root, backup = tmp_path / 'instance', tmp_path / 'backup'
    fixture = HISTORY / 'config0-business4-jobs6-index3'
    shutil.copytree(fixture, root)
    trial = root / '.runtime/chat-tests/fixture'
    shutil.copytree(fixture, trial)
    lock = trial / '.lenbot-instance.lock'
    lock.write_bytes(b'0')
    inode = lock.stat().st_ino
    with sqlite3.connect(trial / 'state.db') as db:
        db.execute('PRAGMA application_id=123')
    before = manifest(root)
    with pytest.raises(ValueError):
        upgrade_instance(root, backup)
    assert manifest(root) == before
    assert lock.stat().st_ino == inode
    assert (backup / 'snapshot.json').exists()


@pytest.mark.parametrize('content', ['{broken', '[]', '{"mode":"isolated-multi"}'])
def test_doctor_reports_configuration_errors_with_unreadable_locations(tmp_path, content):
    (tmp_path / 'lenbot.config.json').write_text(content)
    result = check(tmp_path)
    assert result[0]['check'] == 'config' and result[0]['status'] == 'error'
