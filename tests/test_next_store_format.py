"""A business database of another format is refused at open with what to do, before any call fails on it."""
import sqlite3

import pytest

from len_bot.next.storage.store import FORMAT_VERSION, Store


def _database(path, *, application_id: int, version: int, tables: str = 'CREATE TABLE messages(seq INTEGER);'):
    with sqlite3.connect(path) as db:
        db.executescript(f'PRAGMA application_id={application_id}; PRAGMA user_version={version}; {tables}')


def test_a_newly_created_database_holds_every_table_and_opens_again(tmp_path):
    path = tmp_path / 'state.db'
    Store(path).__exit__()
    with Store(path, readonly=True):
        pass


@pytest.mark.parametrize('application_id,version,message', [
    (0x4C424E31, 7, '格式是 7，当前版本使用格式 1。发布前的格式变更不提供升级步骤'),
    (0x4C424E31, FORMAT_VERSION, '缺少数据表 .* 等 .* 张，属于格式 1 的早期结构。发布前的格式变更不提供升级步骤'),
    (0, 0, '不是 LenBot 的业务数据库'),
])
def test_another_format_is_refused_with_the_way_forward(tmp_path, application_id, version, message):
    path = tmp_path / 'state.db'
    _database(path, application_id=application_id, version=version)
    with pytest.raises(ValueError, match=message):
        Store(path)


def test_one_missing_table_is_named(tmp_path):
    path = tmp_path / 'state.db'
    Store(path).__exit__()
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE usage')
    with pytest.raises(ValueError, match='缺少数据表 usage，属于格式 1 的早期结构'):
        Store(path)
