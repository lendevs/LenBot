"""Store calls on the database thread: no interleaved transactions, writes survive cancellation."""
import asyncio
from contextlib import asynccontextmanager
import json
import threading
import time

import pytest

from len_bot.next.storage.store import Store


@asynccontextmanager
async def _busy_database(store):
    entered, release = threading.Event(), threading.Event()

    def hold_transaction():
        with store.db:
            entered.set()
            release.wait(2)

    job = asyncio.create_task(store.call(hold_transaction))
    await asyncio.to_thread(entered.wait)
    try:
        yield release
    finally:
        release.set()
        await job


async def _while_database_is_busy(store, operation):
    async with _busy_database(store) as release:
        responsive = []

        def heartbeat():
            responsive.append(not release.is_set())
            release.set()

        # A stalled event loop needs the separate timer to release the transaction.
        timer = threading.Timer(1, release.set)
        timer.start()
        asyncio.get_running_loop().call_later(.02, heartbeat)
        try:
            result = await operation
            await asyncio.sleep(0)
        finally:
            timer.cancel()
        assert responsive == [True], 'database lock held the event loop until the timer released it'
        return result


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


@pytest.mark.asyncio
async def test_send_intent_is_committed_before_the_platform_send(tmp_path):
    from test_next_persona_permissions import _config, _package
    from len_bot.next.chat.context import ChatContext
    from len_bot.next.chat.expression import ChatExpression
    from len_bot.next.chat.tools import SayArguments
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.platform.messages import SendResult
    package = _package(tmp_path, 'plain', tools=['say'], documents={})
    config = _config(tmp_path / 'instance', package)
    persona = load_persona(package)
    with Store(config.database) as store:
        seen = []

        async def send(part, *, image_bytes):
            # Another connection, as after a crash: the attempted part is already on disk.
            with Store(config.database, readonly=True) as reader:
                seen.append(reader.db.execute(
                    "SELECT COUNT(*) FROM messages WHERE json_extract(body,'$.is_self')").fetchone()[0])
            return SendResult(status='sent', platform_message_id=f'9{len(seen)}', error=None)

        context = ChatContext(config, persona, store, platform=False, memory=None)
        expression = ChatExpression(config, persona, store, context=context, send_message=send,
                                    notify=lambda: None, on_reply_sample=None, now=store.now)
        said = await expression.express('turn', SayArguments(content='你好'))
        _, status = await expression.deliver_expression('call', said, turn_id=store.start_turn(config.scene),
                                                        channels=set())
        assert status == 'sent'
        assert seen == [1]
        assert store.db.execute("SELECT json_extract(body,'$.send_status') FROM messages").fetchone()[0] == 'sent'


@pytest.mark.asyncio
async def test_store_calls_keep_the_callers_log_context(tmp_path):
    from len_bot.next.runtime.logs import current_context, log_context
    with Store(tmp_path / 'state.db') as store:
        with log_context(scene='onebot:group:80001', turn_id='synthetic-turn'):
            assert (await store.call(current_context))['scene'] == 'onebot:group:80001'
            assert (await store.read(current_context))['turn_id'] == 'synthetic-turn'
        assert 'scene' not in await store.call(current_context)


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['turn', 'scene', 'plugin'])
async def test_model_request_can_wait_for_storage_while_the_loop_runs(tmp_path, scope):
    from len_bot.next.models.client import ChatModel
    from len_bot.next.models.request import request_model
    from test_next_model import recorded_text_response
    from test_next_native_models import peer_server
    from test_next_persona_permissions import _config, _package
    config = _config(tmp_path / 'instance', _package(tmp_path, 'plain', tools=[], documents={}))
    received = []
    server = await peer_server([(200, 'application/json', json.dumps(recorded_text_response()).encode())], received)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            options = ({'turn_id': store.start_turn(config.scene)} if scope == 'turn'
                       else {'plugin': 'fixture'} if scope == 'plugin' else {})
            async with ChatModel(config.model_settings('mind')) as model:
                reply = await _while_database_is_busy(store, request_model(
                    config, store, model, [{'role': 'user', 'content': 'hello'}], [],
                    scene=config.scene, role='mind', output_tokens=512, **options))
            assert reply.text and len(received) == 1
            row = store.db.execute('SELECT ended,error,plugin FROM model_calls').fetchone()
            assert row['ended'] is not None and row['error'] is None
            assert row['plugin'] == ('fixture' if scope == 'plugin' else None)


@pytest.mark.asyncio
async def test_cancellation_while_starting_a_model_request_settles_the_record(tmp_path):
    from len_bot.next.models.client import ChatModel
    from len_bot.next.models.request import request_model
    from test_next_persona_permissions import _config, _package
    config = _config(tmp_path / 'instance', _package(tmp_path, 'plain', tools=[], documents={}))
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as model:
            async with _busy_database(store) as release:
                request = asyncio.create_task(request_model(
                    config, store, model, [{'role': 'user', 'content': 'hello'}], [],
                    scene=config.scene, role='mind', output_tokens=512))
                await asyncio.sleep(.02)
                request.cancel()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await request
            [row] = store.db.execute('SELECT ended,error FROM model_calls').fetchall()
            assert row['ended'] is not None and row['error'].startswith('CancelledError:')


@pytest.mark.asyncio
@pytest.mark.parametrize('switch,field', [('set_paused', 'paused'), ('set_closed', 'closed')])
async def test_scene_switch_can_wait_for_storage_while_the_loop_runs(tmp_path, switch, field):
    from len_bot.next.chat.attention import SceneRunner
    from len_bot.next.chat.session import Chat
    from len_bot.next.persona.profile import load_persona
    from test_next_persona_permissions import _config, _package
    package = _package(tmp_path, 'plain', tools=[], documents={})
    config = _config(tmp_path / 'instance', package)
    with Store(config.database) as store:
        runner = SceneRunner(Chat(config, load_persona(package), store, None), lambda _: None)
        state = await _while_database_is_busy(store, getattr(runner, switch)(True))
        assert state[field] and getattr(runner.state, field)
        assert store.load_attention(config.scene)[field]


@pytest.mark.asyncio
async def test_cancelled_scene_switch_commits_and_wakes_the_runner(tmp_path):
    from len_bot.next.chat.attention import SceneRunner
    from len_bot.next.chat.session import Chat
    from len_bot.next.persona.profile import load_persona
    from test_next_persona_permissions import _config, _package
    package = _package(tmp_path, 'plain', tools=[], documents={})
    config = _config(tmp_path / 'instance', package)
    with Store(config.database) as store:
        runner = SceneRunner(Chat(config, load_persona(package), store, None), lambda _: None)
        runner.changed.clear()
        async with _busy_database(store) as release:
            switch = asyncio.create_task(runner.set_paused(True))
            await asyncio.sleep(.02)
            assert runner.state.paused
            switch.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await switch
        assert store.load_attention(config.scene)['paused'] and runner.changed.is_set()
