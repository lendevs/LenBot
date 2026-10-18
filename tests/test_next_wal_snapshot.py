"""WAL with synchronous=FULL, and stopped-instance snapshots of databases that still have a log."""
import shutil
import sqlite3
from contextlib import closing

import pytest

from len_bot.next.maintenance.snapshot import create, restore
from len_bot.next.storage.sqlite import checkpoint, connect
from len_bot.next.storage.store import Store


def test_read_write_connections_use_wal_with_full_sync(tmp_path):
    with closing(connect(tmp_path / 'state.db')) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert db.execute('PRAGMA synchronous').fetchone()[0] == 2  # FULL


def test_reader_does_not_wait_for_an_open_write_transaction(tmp_path):
    path = tmp_path / 'state.db'
    with Store(path) as store:
        store.db.execute("CREATE TABLE probe(value TEXT)")
        with store.db:
            store.db.execute("INSERT INTO probe VALUES ('committed')")
        with closing(connect(path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("INSERT INTO probe VALUES ('open')")
            with closing(connect(path, readonly=True)) as reader:
                reader.execute('PRAGMA busy_timeout=0')
                assert reader.execute("SELECT value FROM probe").fetchall() == [('committed',)]
            writer.rollback()


def _crashed_instance(tmp_path):
    """A stopped instance whose last commits are only in the WAL, as after power loss."""
    live, root = tmp_path / 'live', tmp_path / 'instance'
    live.mkdir()
    root.mkdir()
    db = connect(live / 'state.db')
    db.execute('PRAGMA wal_autocheckpoint=0')
    with db:
        db.execute('CREATE TABLE probe(value TEXT)')
        db.execute("INSERT INTO probe VALUES ('intent')")
    for name in ('state.db', 'state.db-wal', 'state.db-shm'):
        shutil.copyfile(live / name, root / name)
    db.close()
    assert (root / 'state.db-wal').stat().st_size > 0
    return root


def test_snapshot_folds_the_log_into_the_saved_database(tmp_path):
    root = _crashed_instance(tmp_path)
    snapshot = tmp_path / 'backup'
    create([str(root)], snapshot)
    saved = snapshot / '0' / 'state.db'
    assert not (snapshot / '0' / 'state.db-wal').exists() or (snapshot / '0' / 'state.db-wal').stat().st_size == 0
    # The saved file alone (immutable ignores any log) holds the committed row.
    with closing(sqlite3.connect(saved.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        assert db.execute('SELECT value FROM probe').fetchall() == [('intent',)]


def test_restore_after_a_failed_new_version_returns_the_snapshot_rows(tmp_path):
    root = _crashed_instance(tmp_path)
    snapshot = tmp_path / 'backup'
    create([str(root)], snapshot)
    with closing(connect(root / 'state.db')) as db:
        db.execute('PRAGMA wal_autocheckpoint=0')
        with db:
            db.execute("INSERT INTO probe VALUES ('from the failed version')")
        shutil.copyfile(root / 'state.db-wal', tmp_path / 'left-behind-wal')
    # The failed version crashed: its log is still beside the database.
    shutil.copyfile(tmp_path / 'left-behind-wal', root / 'state.db-wal')
    restore(root, snapshot)
    with closing(connect(root / 'state.db')) as db:
        assert db.execute('SELECT value FROM probe').fetchall() == [('intent',)]


def test_checkpoint_refuses_a_database_that_is_still_open(tmp_path):
    path = tmp_path / 'state.db'
    with closing(connect(path)) as db:
        db.execute('PRAGMA wal_autocheckpoint=0')
        with db:
            db.execute('CREATE TABLE probe(value TEXT)')
        reader = connect(path, readonly=True)
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM probe').fetchall()
        with db:
            db.execute("INSERT INTO probe VALUES ('later')")
        with pytest.raises(sqlite3.OperationalError, match='WAL'):
            checkpoint(path)
        reader.close()
