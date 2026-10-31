"""Opening the persistent files: structures that differ from the current format are refused with what differs,
a refused file is left unchanged, and an unreadable chat-test database does not stop the usage count."""
import asyncio
from contextlib import closing
import logging
import sqlite3

import pytest

from len_bot.next import config as root_config
from len_bot.next.memory.jobs import MemoryJobs
from len_bot.next.memory.local import LocalMemory, LocalMemorySettings
from len_bot.next.models.usage import instance_usage, record_usage
from len_bot.next.plugins.kv import PluginKV
from len_bot.next.storage.schema import FORMAT_RESET
from len_bot.next.storage.store import Store

SCENE = 'onebot:group:80001'


def _usage(store, scene=SCENE, *, time=100.0, tokens=30):
    with store.db:
        record_usage(store.db, time=time, scene=scene, purpose='mind', provider='fixture', model='fixture-model',
                     tokens={'input': tokens - 10, 'output': 10, 'cached': None})


def _create_business(path):
    Store(path).__exit__()


def _create_jobs(path):
    MemoryJobs(path).close()


def _create_index(path):
    LocalMemory(LocalMemorySettings(directory=path.parent))


def _create_kv(path):
    PluginKV(path.parent).set('key', 1)


def _open_business(path):
    Store(path).__exit__()


def _open_jobs(path):
    MemoryJobs(path).close()


def _open_index(path):
    LocalMemory(LocalMemorySettings(directory=path.parent))


def _open_kv(path):
    PluginKV(path.parent).get('key', None)


# (file name, create, open, a table of that file, a column of it that can be dropped, a type to change)
FILES = {
    'business': ('state.db', _create_business, _open_business, 'usage', 'cached'),
    'memory_jobs': ('jobs.db', _create_jobs, _open_jobs, 'memory_cursors', 'enabled_at'),
    'local_memory_index': ('.memory-index.sqlite3', _create_index, _open_index, 'memory_changes', 'reason'),
    'plugin_kv': ('kv.sqlite3', _create_kv, _open_kv, 'kv', 'value'),
}


def _file(tmp_path, name):
    filename, create, opener, table, column = FILES[name]
    path = tmp_path / filename
    create(path)
    return path, opener, table, column


def _edit(path, statements):
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        for statement in statements:
            db.execute(statement)


@pytest.mark.parametrize('name', FILES)
def test_a_file_missing_a_column_is_refused_with_the_table_and_column(tmp_path, name):
    path, opener, table, column = _file(tmp_path, name)
    opener(path)
    _edit(path, [f'ALTER TABLE {table} DROP COLUMN {column}'])
    with pytest.raises(ValueError, match=rf'{table}（缺少列 {column}）.*{FORMAT_RESET}'):
        opener(path)


@pytest.mark.parametrize('name', FILES)
def test_a_file_with_an_extra_column_is_refused_with_the_table_and_column(tmp_path, name):
    path, opener, table, _ = _file(tmp_path, name)
    _edit(path, [f'ALTER TABLE {table} ADD COLUMN surplus TEXT'])
    with pytest.raises(ValueError, match=rf'{table}（多出列 surplus）.*{FORMAT_RESET}'):
        opener(path)


def test_a_column_with_another_type_or_constraint_is_refused(tmp_path):
    path, opener, *_ = _file(tmp_path, 'plugin_kv')
    _edit(path, ['DROP TABLE kv', 'CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB)'])
    with pytest.raises(ValueError, match=r'kv（列 value 为 value BLOB，应为 value TEXT NOT NULL）'):
        opener(path)


def test_the_business_database_names_every_differing_table(tmp_path):
    path, opener, *_ = _file(tmp_path, 'business')
    _edit(path, ['ALTER TABLE speech ADD COLUMN surplus TEXT', 'ALTER TABLE usage DROP COLUMN cached'])
    with pytest.raises(ValueError) as refused:
        opener(path)
    assert 'speech（多出列 surplus）' in str(refused.value) and 'usage（缺少列 cached）' in str(refused.value)
    with pytest.raises(ValueError, match='usage（缺少列 cached）'):
        Store(path, readonly=True)


def test_columns_in_another_order_are_accepted(tmp_path):
    # tasks.materials was added after the other columns of an older root instance, so it comes last there.
    path, opener, *_ = _file(tmp_path, 'business')
    _edit(path, ['DROP TABLE speech', 'DROP TABLE usage',
                 'CREATE TABLE speech (time REAL NOT NULL, scene TEXT NOT NULL, id INTEGER PRIMARY KEY)',
                 'CREATE INDEX scene_speech ON speech(scene, time)',
                 'CREATE TABLE usage (cached INTEGER, output INTEGER NOT NULL, input INTEGER NOT NULL, '
                 'model TEXT NOT NULL, provider TEXT NOT NULL, purpose TEXT NOT NULL, scene TEXT NOT NULL, '
                 'time REAL NOT NULL, id INTEGER PRIMARY KEY)'])
    opener(path)
    with Store(path, readonly=True) as reopened:
        assert reopened.db.execute('SELECT COUNT(*) FROM speech').fetchone()[0] == 0


@pytest.mark.parametrize('name', ['memory_jobs', 'plugin_kv'])
def test_other_files_accept_columns_in_another_order(tmp_path, name):
    path, opener, table, _ = _file(tmp_path, name)
    if name == 'plugin_kv':
        statements = ['DROP TABLE kv', 'CREATE TABLE kv (value TEXT NOT NULL, key TEXT PRIMARY KEY)']
    else:
        statements = ['DROP TABLE memory_cursors',
                      'CREATE TABLE memory_cursors (enabled_at REAL NOT NULL, after_seq INTEGER NOT NULL, '
                      'scene TEXT PRIMARY KEY)']
    _edit(path, statements)
    opener(path)


def test_the_local_index_with_a_vector_table_still_opens(tmp_path):
    path, opener, *_ = _file(tmp_path, 'local_memory_index')
    _edit(path, ['CREATE TABLE memory_vec_chunks (rowid INTEGER PRIMARY KEY)'])
    opener(path)


@pytest.mark.parametrize('name', FILES)
def test_a_refused_file_is_not_rewritten(tmp_path, name):
    path, opener, *_ = _file(tmp_path, name)
    # A rollback-journal file, so that opening it read-write would visibly switch it to WAL.
    _edit(path, ['PRAGMA user_version=9', 'PRAGMA journal_mode=DELETE'])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        opener(path)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + '-wal').exists()


def test_a_business_file_without_a_format_mark_gets_the_reset_hint_and_stays_as_it_was(tmp_path):
    path = tmp_path / 'state.db'
    with closing(sqlite3.connect(path)) as db:
        db.executescript('PRAGMA journal_mode=DELETE; CREATE TABLE messages(seq INTEGER);')
    before = path.read_bytes()
    with pytest.raises(ValueError, match=rf'application_id=0.*{FORMAT_RESET}'):
        Store(path)
    assert path.read_bytes() == before


def test_a_business_file_of_another_application_keeps_its_message(tmp_path):
    path = tmp_path / 'state.db'
    with closing(sqlite3.connect(path)) as db:
        db.executescript('PRAGMA application_id=12345; CREATE TABLE messages(seq INTEGER);')
    with pytest.raises(ValueError, match=r'不是 LenBot 的业务数据库（application_id=12345）'):
        Store(path)


@pytest.mark.parametrize('name', ['plugin_kv', 'local_memory_index'])
def test_a_refused_format_names_the_way_forward(tmp_path, name):
    path, opener, *_ = _file(tmp_path, name)
    _edit(path, ['PRAGMA user_version=9'])
    with pytest.raises(ValueError, match=FORMAT_RESET):
        opener(path)


def test_the_local_index_overview_read_names_the_way_forward(tmp_path):
    from len_bot.next.memory.local import scene_overview
    path, *_ = _file(tmp_path, 'local_memory_index')
    asyncio.run(LocalMemory(LocalMemorySettings(directory=tmp_path)).write(SCENE, 'a.md', '内容。', '写入'))
    base = tmp_path / 'scenes'
    for directory in base.iterdir():
        for name in ('.abstract.md', '.overview.md'):
            (directory / name).write_text('x', encoding='utf-8')
    _edit(path, ['PRAGMA user_version=9'])
    with pytest.raises(ValueError, match=FORMAT_RESET):
        scene_overview(tmp_path, SCENE)


def test_a_configuration_without_a_format_number_is_format_one(tmp_path, monkeypatch):
    from test_next_config import _host_config, _write_config
    source = _host_config()
    source.pop('config_version', None)
    root = tmp_path / 'lab'
    _write_config(root, source)
    assert root_config.load_host_config(root).config_version == 1
    monkeypatch.setattr(root_config, 'CONFIG_VERSION', 2)
    with pytest.raises(ValueError, match=rf'配置格式是 1，当前版本使用格式 2。{FORMAT_RESET}'):
        root_config.load_host_config(root)


@pytest.fixture
def trials(tmp_path):
    root = tmp_path / 'trials'
    good = root / 'good' / 'state.db'
    with Store(good) as store:
        _usage(store, tokens=40)
    empty = root / 'empty' / 'state.db'
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b'')
    without_table = root / 'without-table' / 'state.db'
    without_table.parent.mkdir(parents=True)
    with closing(sqlite3.connect(without_table)) as db:
        db.execute('CREATE TABLE other(a)')
    damaged = root / 'damaged' / 'state.db'
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(b'this is not a database' * 200)
    return root, {'empty': empty, 'without-table': without_table, 'damaged': damaged}


def test_unreadable_chat_test_databases_are_skipped_and_logged_while_the_rest_count(tmp_path, trials, caplog):
    root, unreadable = trials
    with Store(tmp_path / 'state.db') as store:
        _usage(store, tokens=30)
        with caplog.at_level(logging.WARNING):
            rows = instance_usage(store.db, None, 0.0, 1000.0, trials_root=root)
    assert sorted(row['input'] + row['output'] for row in rows) == [30, 40]
    skipped = {record.fields['path']: record.fields['error']['message']
               for record in caplog.records if getattr(record, 'event', None) == 'trial_usage_skipped'}
    assert set(skipped) == {str(path) for path in unreadable.values()}
    assert 'no such table: usage' in skipped[str(unreadable['empty'])]
    assert 'no such table: usage' in skipped[str(unreadable['without-table'])]
    assert 'not a database' in skipped[str(unreadable['damaged'])]
