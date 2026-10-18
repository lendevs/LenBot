"""The event loop's reads do not wait while the database thread holds the write connection.

Review finding: a 0.8 s database-thread transaction (standing in for a slow fsync'd commit) held
the connection lock, and one ``SELECT 1`` on the event loop stalled the loop for ~0.76 s.
"""
import asyncio
import sqlite3
import threading
import time

import pytest

from len_bot.next.storage.store import Store

HOLD_SECONDS = 0.8


async def loop_lag_while(store: Store, job, on_loop) -> float:
    """Largest event-loop delay while ``job`` runs on the database thread and ``on_loop`` runs on the loop."""
    lag = []

    async def ticker():
        started = time.perf_counter()
        while time.perf_counter() - started < HOLD_SECONDS + 0.4:
            before = time.perf_counter()
            await asyncio.sleep(0.01)
            lag.append(time.perf_counter() - before)

    tick = asyncio.create_task(ticker())
    running = asyncio.create_task(job)
    await asyncio.sleep(0.05)
    on_loop()
    await running
    await tick
    return max(lag)


@pytest.mark.asyncio
async def test_a_loop_read_does_not_wait_for_a_database_thread_transaction(tmp_path):
    with Store(tmp_path / 'state.db') as store:
        store.db.execute('CREATE TABLE probe(x)')
        entered = threading.Event()

        def slow_write():
            with store.db:
                store.db.execute('INSERT INTO probe VALUES (1)')
                entered.set()
                time.sleep(HOLD_SECONDS)

        seen = []

        def read_on_loop():
            assert entered.wait(1)
            seen.append(store.db.execute('SELECT 1').fetchone()[0])
            # It reads the state from before the other thread's transaction, not its uncommitted row.
            seen.append(store.db.execute('SELECT COUNT(*) FROM probe').fetchone()[0])

        lag = await loop_lag_while(store, store.call(slow_write), read_on_loop)
        assert seen == [1, 0]
        assert lag < 0.25, f'event loop stalled {lag:.3f}s behind the database thread'
        # Once the call returns its commit is visible to the next read.
        assert store.db.execute('SELECT COUNT(*) FROM probe').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_writes_still_serialize_and_an_explicit_begin_keeps_the_connection(tmp_path):
    with Store(tmp_path / 'state.db') as store:
        store.db.execute('CREATE TABLE probe(x)')
        store.db.execute('BEGIN IMMEDIATE')
        store.db.execute('INSERT INTO probe VALUES (1)')
        # The loop thread reads its own uncommitted row on the write connection.
        assert store.db.execute('SELECT COUNT(*) FROM probe').fetchone()[0] == 1
        other = asyncio.create_task(store.call(store.db.execute, 'INSERT INTO probe VALUES (2)'))
        await asyncio.sleep(0.2)
        assert not other.done(), 'a database-thread statement joined the loop thread transaction'
        store.db.commit()
        await other
        assert [row[0] for row in store.db.execute('SELECT x FROM probe ORDER BY x')] == [1, 2]


@pytest.mark.asyncio
async def test_store_read_does_not_hold_the_write_connection_and_cannot_write(tmp_path):
    with Store(tmp_path / 'state.db') as store:
        store.db.execute('CREATE TABLE probe(x)')
        with store.db:
            store.db.execute('INSERT INTO probe VALUES (1)')

        def snapshot():
            first = store.db.execute('SELECT COUNT(*) FROM probe').fetchone()[0]
            return first, [row[0] for row in store.db.execute('SELECT x FROM probe')]

        store.db.execute('BEGIN IMMEDIATE')
        store.db.execute('INSERT INTO probe VALUES (2)')
        try:
            # A read call finishes while the loop thread holds an open write transaction.
            assert await asyncio.wait_for(store.read(snapshot), 2) == (1, [1])
        finally:
            store.db.commit()
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            await store.read(store.db.execute, 'INSERT INTO probe VALUES (3)')
        assert await store.read(snapshot) == (2, [1, 2])


@pytest.mark.asyncio
async def test_contended_reads_return_complete_rows(tmp_path):
    with Store(tmp_path / 'state.db') as store:
        store.db.execute('CREATE TABLE probe(x)')
        with store.db:
            store.db.executemany('INSERT INTO probe VALUES (?)', [(n,) for n in range(5)])
        entered = threading.Event()

        def hold():
            with store.db:
                store.db.execute('INSERT INTO probe VALUES (99)')
                entered.set()
                time.sleep(0.3)

        running = asyncio.create_task(store.call(hold))
        assert await asyncio.to_thread(entered.wait, 1)
        rows = store.db.execute('SELECT x FROM probe ORDER BY x')
        assert rows.fetchone()[0] == 0 and [r[0] for r in rows.fetchmany(2)] == [1, 2] and [r[0] for r in rows] == [3, 4]
        assert store.db.execute('SELECT x FROM probe WHERE x>10').fetchone() is None
        await running
