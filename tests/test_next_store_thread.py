"""Store calls on the database thread: no interleaved transactions, writes survive cancellation."""
import asyncio
import threading
import time

import pytest

from len_bot.next.storage.store import Store


def _table(store):
    store.db.execute("CREATE TEMP TABLE probe(value TEXT)")


def _values(store):
    return sorted(row[0] for row in store.db.execute("SELECT value FROM probe"))


def test_loop_thread_statement_does_not_join_a_database_thread_transaction(tmp_path):
    with Store(tmp_path / 'state.db') as store:
        _table(store)
        started = threading.Event()

        def failing_transaction():
            with store.db:
                store.db.execute("INSERT INTO probe VALUES ('worker')")
                started.set()
                time.sleep(0.2)
                raise RuntimeError('rolled back')

        async def run():
            job = asyncio.create_task(store.call(failing_transaction))
            await asyncio.to_thread(started.wait)
            # A legacy synchronous call on the event loop thread waits for the transaction to end.
            with store.db:
                store.db.execute("INSERT INTO probe VALUES ('loop')")
            with pytest.raises(RuntimeError, match='rolled back'):
                await job
        asyncio.run(run())
        assert _values(store) == ['loop']


def test_database_thread_keeps_the_event_loop_running(tmp_path):
    with Store(tmp_path / 'state.db') as store:
        def slow():
            time.sleep(0.3)
            return threading.current_thread().name

        async def run():
            ticks = 0
            job = asyncio.create_task(store.call(slow))
            while not job.done():
                ticks += 1
                await asyncio.sleep(0.01)
            return ticks, await job
        ticks, thread = asyncio.run(run())
        assert ticks >= 10
        assert thread.startswith('lenbot-db')


def test_cancelled_caller_still_sees_the_committed_write(tmp_path):
    with Store(tmp_path / 'state.db') as store:
        _table(store)
        started = threading.Event()

        def write():
            started.set()
            time.sleep(0.1)
            with store.db:
                store.db.execute("INSERT INTO probe VALUES ('kept')")

        async def run():
            job = asyncio.create_task(store.call(write))
            await asyncio.to_thread(started.wait)
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
            # Cancellation is delivered only after the write finished.
            return _values(store)
        assert asyncio.run(run()) == ['kept']


def test_store_methods_run_on_the_database_thread(tmp_path):
    with Store(tmp_path / 'state.db', now=lambda: 1790618400.) as store:
        async def run():
            turn = await store.call(store.start_turn, 'onebot:group:80001')
            await store.call(store.end_turn, turn, 'settled')
            return turn
        turn = asyncio.run(run())
        row = store.db.execute("SELECT status FROM turns WHERE id=?", (turn,)).fetchone()
        assert row[0] == 'settled'
