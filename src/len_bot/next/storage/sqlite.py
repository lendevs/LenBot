"""The one connection convention for LenBot's own SQLite files.

Rollback journal with synchronous=FULL: the business database keeps send intents and
consumer cursors, so a committed write must survive power loss, and stopped-instance
snapshots copy single database files without WAL side files. Store calls that still run
on the event loop keep a lock wait bounded instead of blocking it for long; the chat path
runs its calls on the store's database thread through ``SerializedConnection``.
"""

from __future__ import annotations

from collections.abc import Iterable
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
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
    except BaseException:
        db.close()
        raise
    return db


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
