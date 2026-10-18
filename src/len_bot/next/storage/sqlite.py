"""The one connection convention for LenBot's own SQLite files.

WAL with synchronous=FULL: the business database keeps send intents and consumer cursors,
so a committed write must survive power loss; in WAL mode FULL syncs the log at every commit.
Readers (the panel's budget and limit reads in a thread) no longer wait for a writer.
Stopped-instance snapshots first fold each log into its database with ``checkpoint`` so
the main file alone is complete. The chat path runs its store calls on the store's database
thread through ``SerializedConnection``; a read from the event loop that would wait for that
thread's write runs on a read-only connection instead.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
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


def fold_log(path: Path) -> bool:
    """Fold a stopped database's leftover WAL (after a kill or power loss) into the main file.

    Only committed transactions are in the log, so this changes no data; it is what a stopped
    snapshot does first. Call it only under the instance lock. Returns whether there was a log.
    """
    log = Path(str(path) + '-wal')
    if not path.is_file() or path.is_symlink() or not log.is_file() or not log.stat().st_size:
        return False
    checkpoint(path)
    return True


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


class FetchedRows:
    """A finished query's rows with the cursor interface the store uses.

    Rows read on a read connection are fetched at once so no statement stays open there; an
    open statement would keep the connection on an old snapshot for later reads of the thread.
    """

    def __init__(self, cursor: sqlite3.Cursor):
        self.description = cursor.description
        self.rowcount = cursor.rowcount
        self.lastrowid = cursor.lastrowid
        self._rows = cursor.fetchall()
        self._next = 0
        cursor.close()

    def fetchone(self):
        if self._next >= len(self._rows):
            return None
        self._next += 1
        return self._rows[self._next - 1]

    def fetchmany(self, size: int = 1) -> list:
        rows = self._rows[self._next:self._next + size]
        self._next += len(rows)
        return rows

    def fetchall(self) -> list:
        rows = self._rows[self._next:]
        self._next = len(self._rows)
        return rows

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class SerializedConnection:
    """The store's write connection, shared by the event loop thread and the database thread,
    plus read-only connections so a plain read never waits behind the other thread.

    Writes: a ``with db:`` transaction, an explicit ``BEGIN`` (until it commits or rolls back) and
    a single statement outside a transaction each hold the lock, so statements of two threads never
    join one transaction. The lock is reentrant: a store method running on the database thread
    under ``hold()`` uses the same connection freely and sees its own uncommitted writes.

    Reads: while another thread holds the write connection (the database thread committing, which
    waits for fsync, or a long store call), a ``SELECT`` from a thread that holds nothing runs on
    that thread's own read-only connection instead of waiting; WAL readers never wait for a writer.
    It sees what was committed before the other thread's transaction, the same as if it had run
    just before that call. Uncontended reads stay on the write connection, as before.
    Inside ``reading()`` every statement of the thread runs on its read connection in one read
    transaction (one consistent snapshot) without the lock; a write there fails.
    TEMP tables live on the write connection only and are not visible to these reads.
    """

    def __init__(self, db: sqlite3.Connection, *, reader: Callable[[], sqlite3.Connection] | None = None):
        self._db = db
        self._lock = threading.RLock()
        self._reader = reader
        self._local = threading.local()
        self._readers: list[sqlite3.Connection] = []
        self._readers_lock = threading.Lock()
        self._row_factory = db.row_factory
        self._closed = False

    @property
    def row_factory(self):
        return self._db.row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        self._row_factory = value
        self._db.row_factory = value
        with self._readers_lock:
            for reader in self._readers:
                reader.row_factory = value

    @property
    def in_transaction(self) -> bool:
        return self._db.in_transaction

    def _depth(self) -> int:
        return getattr(self._local, 'depth', 0)

    def _acquire(self) -> None:
        self._lock.acquire()
        self._local.depth = self._depth() + 1

    def _release(self) -> None:
        self._local.depth = self._depth() - 1
        self._lock.release()

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Hold the write connection for a whole store call on this thread."""
        self._acquire()
        try:
            yield
        finally:
            self._release()

    def _read_connection(self) -> sqlite3.Connection:
        db = getattr(self._local, 'reader', None)
        if db is None:
            db = self._reader()
            db.row_factory = self._row_factory
            with self._readers_lock:
                if self._closed:
                    db.close()
                    raise sqlite3.ProgrammingError('Cannot operate on a closed database.')
                self._readers.append(db)
            self._local.reader = db
        return db

    @contextmanager
    def reading(self) -> Iterator[None]:
        """Run this thread's statements on its read connection, in one snapshot, without the lock."""
        if self._reader is None or self._depth() or getattr(self._local, 'reading', False):
            # No read connections (a read-only store), or already holding or reading: nothing to change.
            yield
            return
        db = self._read_connection()
        db.execute('BEGIN')
        self._local.reading = True
        try:
            yield
        finally:
            self._local.reading = False
            db.rollback()

    def _settle(self) -> None:
        """Keep the lock across an explicit BEGIN until that transaction ends."""
        explicit = getattr(self._local, 'explicit', 0)
        if explicit and not self._db.in_transaction:
            self._local.explicit = explicit - 1
            self._release()

    def execute(self, sql: str, parameters: Iterable = ()) -> sqlite3.Cursor | FetchedRows:
        if self._reader is not None and getattr(self._local, 'reading', False):
            return self._read_connection().execute(sql, parameters)
        if not self._lock.acquire(blocking=False):
            if (self._reader is not None and not self._depth()
                    and sql.lstrip()[:6].upper() == 'SELECT'):
                return FetchedRows(self._read_connection().execute(sql, parameters))
            self._lock.acquire()
        try:
            begins = sql.lstrip()[:5].upper() == 'BEGIN'
            try:
                cursor = self._db.execute(sql, parameters)
            finally:
                if begins and self._db.in_transaction:
                    self._acquire()
                    self._local.explicit = getattr(self._local, 'explicit', 0) + 1
                else:
                    self._settle()
            return cursor
        finally:
            self._lock.release()

    def executemany(self, sql: str, parameters: Iterable) -> sqlite3.Cursor:
        with self._lock:
            return self._db.executemany(sql, parameters)

    def executescript(self, script: str) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self._db.executescript(script)
            finally:
                self._settle()

    def commit(self) -> None:
        with self._lock:
            try:
                self._db.commit()
            finally:
                self._settle()

    def rollback(self) -> None:
        with self._lock:
            try:
                self._db.rollback()
            finally:
                self._settle()

    def backup(self, target: sqlite3.Connection, **options) -> None:
        with self._lock:
            self._db.backup(target, **options)

    def close(self) -> None:
        with self._lock:
            with self._readers_lock:
                self._closed = True
                readers, self._readers = self._readers, []
            for reader in readers:
                reader.close()
            self._db.close()

    def __enter__(self) -> SerializedConnection:
        self._acquire()
        try:
            self._db.__enter__()
        except BaseException:
            self._release()
            raise
        return self

    def __exit__(self, *exc) -> bool:
        try:
            return self._db.__exit__(*exc)
        finally:
            self._settle()
            self._release()
