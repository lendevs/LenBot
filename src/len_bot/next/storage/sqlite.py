"""The one connection convention for LenBot's own SQLite files.

WAL with synchronous=FULL: the business database keeps send intents and consumer cursors,
so a committed write must survive power loss; in WAL mode FULL syncs the log at every commit.
Readers (the panel's budget and limit reads in a thread) no longer wait for a writer.
Stopped-instance snapshots first fold each log into its database with ``checkpoint`` so
the main file alone is complete. Store calls that still run on the event loop keep a lock
wait bounded instead of blocking it for long; the chat path runs its calls on the store's
database thread through ``SerializedConnection``.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
import sqlite3
import threading

BUSY_TIMEOUT_SECONDS = 5.0


def connect(path: Path, *, readonly: bool = False, immutable: bool = False, create: bool = True,
            threaded: bool = False) -> sqlite3.Connection:
    """Read-write connections set the journal and durability; read-only ones only read.

    ``immutable`` reads a file nothing else writes (a stopped instance or a snapshot) without
    taking locks; ``create=False`` refuses to make a new empty file, for upgrades of existing data.
    ``threaded`` allows use from another thread; only ``SerializedConnection`` should ask for it.
    """
    options = {'timeout': BUSY_TIMEOUT_SECONDS, 'check_same_thread': not threaded}
    if readonly or immutable:
        query = '?mode=ro&immutable=1' if immutable else '?mode=ro'
        return sqlite3.connect(path.resolve().as_uri() + query, uri=True, **options)
    if create:
        db = sqlite3.connect(path, **options)
    else:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, **options)
    try:
        mode = db.execute('PRAGMA journal_mode=WAL').fetchone()[0]
        if mode != 'wal':
            raise sqlite3.OperationalError(f'SQLite 无法为 {path} 启用 WAL 日志，返回 journal_mode={mode!r}；'
                                           '数据库需要放在支持共享内存映射的本地文件系统上')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
    except BaseException:
        db.close()
        raise
    return db


def checkpoint(path: Path) -> None:
    """Fold a stopped database's WAL into the main file and empty the log.

    Only for a database nothing else has open (a stopped instance under its lock); a reader or
    writer elsewhere would keep frames in the log, which is reported instead of copied around.
    """
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True,
                                 timeout=BUSY_TIMEOUT_SECONDS)) as db:
        busy, frames, moved = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if busy or frames != moved:
            raise sqlite3.OperationalError(f'{path} 的 WAL 未能完整写回（busy={busy}, frames={frames}, '
                                           f'checkpointed={moved}）；确认实例已停止后重试')


def checkpoint_logs(paths: Iterable[Path]) -> list[Path]:
    """Checkpoint every SQLite file under ``paths`` that has a WAL beside it; return those files."""
    done = []
    for root in paths:
        if root.is_symlink() or not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob('*'))
        for candidate in candidates:
            log = candidate.with_name(candidate.name + '-wal')
            if candidate.is_file() and not candidate.is_symlink() and log.is_file():
                checkpoint(candidate)
                done.append(candidate)
    return done


class SerializedConnection:
    """One connection shared by the event loop thread and a store's database thread.

    A ``with db:`` transaction holds the lock until it commits or rolls back, and a single
    statement outside a transaction holds it while it runs, so statements of two threads never
    join one transaction. The lock is reentrant: a store method running on the database thread
    under ``hold()`` uses the same connection freely.
    """

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._lock = threading.RLock()

    @property
    def row_factory(self):
        return self._db.row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        self._db.row_factory = value

    @property
    def in_transaction(self) -> bool:
        return self._db.in_transaction

    def hold(self) -> threading.RLock:
        return self._lock

    def execute(self, sql: str, parameters: Iterable = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, parameters)

    def executemany(self, sql: str, parameters: Iterable) -> sqlite3.Cursor:
        with self._lock:
            return self._db.executemany(sql, parameters)

    def executescript(self, script: str) -> sqlite3.Cursor:
        with self._lock:
            return self._db.executescript(script)

    def commit(self) -> None:
        with self._lock:
            self._db.commit()

    def rollback(self) -> None:
        with self._lock:
            self._db.rollback()

    def backup(self, target: sqlite3.Connection, **options) -> None:
        with self._lock:
            self._db.backup(target, **options)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> SerializedConnection:
        self._lock.acquire()
        try:
            self._db.__enter__()
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, *exc) -> bool:
        try:
            return self._db.__exit__(*exc)
        finally:
            self._lock.release()
