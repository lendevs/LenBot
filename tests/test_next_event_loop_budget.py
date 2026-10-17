"""Token budget checks off the event loop and loop-stall monitoring (audit C-1, C-2)."""
import asyncio
import logging
import time
from types import SimpleNamespace

import pytest

from len_bot.next.models.limits import LimitReached, ModelBudget, ResourceLimits
from len_bot.next.storage.store import Store


def _settings(path, **values):
    return SimpleNamespace(database=path, timezone='UTC', limits=ResourceLimits(**values),
                           scene_timezone=lambda _: 'UTC')


def _spend(store, scene, tokens):
    turn = store.start_turn(scene)
    call = store.start_call(turn, 'mind', {'provider': 'fixture'})
    store.end_call(call, {}, None, tokens={'input': tokens - 10, 'output': 10, 'cached': None})
    store.end_turn(turn, 'settled')


def test_polling_checks_share_recent_totals_but_admission_is_exact(tmp_path, monkeypatch):
    from len_bot.next.models import limits
    now, clock = 1790618400., [0.0]
    path = tmp_path / 'state.db'
    with Store(path, now=lambda: now) as store:
        budget = ModelBudget(_settings(path, daily_tokens=100), store, None, clock=lambda: clock[0])
        counted = []
        real = limits.instance_calls
        monkeypatch.setattr(limits, 'instance_calls', lambda *a, **k: counted.append(1) or real(*a, **k))
        # A settings save wakes every runner at once: one aggregation serves them all.
        for scene in ('onebot:group:80001', 'onebot:group:80002', 'onebot:group:80003'):
            budget.check(scene, max_age=2)
        assert len(counted) == 1
        _spend(store, 'onebot:group:80001', 100)
        budget.check('onebot:group:80002', max_age=2)  # cached, within two seconds
        with pytest.raises(LimitReached):
            budget.check('onebot:group:80002')  # the real model admission never uses the cache
        clock[0] += 3
        with pytest.raises(LimitReached):
            budget.check('onebot:group:80003', max_age=2)


def test_budget_reads_through_a_read_only_store_in_a_thread(tmp_path):
    now = 1790618400.
    path = tmp_path / 'state.db'
    with Store(path, now=lambda: now) as store:
        _spend(store, 'onebot:group:80001', 100)
        budget = ModelBudget(_settings(path, daily_tokens=100), store, None)

        def read():
            with Store(path, readonly=True, now=lambda: now) as source:
                budget.check('onebot:group:80001', store=source)
        with pytest.raises(LimitReached):
            asyncio.run(asyncio.to_thread(read))


def test_runner_admission_loop_uses_the_short_cache(tmp_path):
    from test_next_persona_permissions import _config, _package
    from len_bot.next.chat.attention import SceneRunner
    from len_bot.next.chat.session import Chat
    from len_bot.next.models.slots import ModelSlots
    from len_bot.next.persona.profile import load_persona
    package = _package(tmp_path, 'plain', tools=['say'], documents={})
    config = _config(tmp_path / 'instance', package)
    with Store(config.database) as store:
        slots = ModelSlots(1)
        calls = []

        class Budget(ModelBudget):
            def check(self, scene, *, max_age=0.0, store=None):
                calls.append(max_age)
        slots.admit = Budget(SimpleNamespace(database=config.database, timezone='UTC', limits=ResourceLimits()),
                             store, None).check
        runner = SceneRunner(Chat(config, load_persona(package), store, None, slots=slots), lambda event: None)
        asyncio.run(runner.ready_messages(wait=False))
        assert calls and all(age > 0 for age in calls)
        runner.chat.check_limits(model=True)
        assert calls[-1] == 0


def test_limits_route_runs_budget_off_the_event_loop():
    import inspect
    from len_bot.next.panel.routes import operations
    source = inspect.getsource(operations)
    route = source[source.index("def limit_states"):source.index("@app.post('/api/host/scenes/{scene}/speech/reset')")]
    assert 'asyncio.to_thread' in route and 'readonly=True' in route


def test_event_loop_stall_is_logged(caplog):
    from len_bot.next.runtime.loop_monitor import watch_event_loop

    async def run():
        stalls = []
        monitor = asyncio.create_task(watch_event_loop(interval=0.01, threshold=0.05, on_stall=stalls.append))
        await asyncio.sleep(0.03)
        time.sleep(0.2)  # a synchronous call holding the loop
        await asyncio.sleep(0.05)
        monitor.cancel()
        return stalls
    with caplog.at_level(logging.WARNING):
        stalls = asyncio.run(run())
    assert stalls and stalls[0] >= 0.1
    assert any('event_loop_stall' in record.getMessage() or getattr(record, 'event', None) == 'event_loop_stall'
               for record in caplog.records)


def test_stall_names_the_blocking_task_and_its_stack():
    from len_bot.next.runtime.loop_monitor import LoopMonitor

    def hold_the_loop():
        time.sleep(0.3)

    async def blocking_handler():
        await asyncio.sleep(0.05)
        hold_the_loop()

    async def run():
        monitor = LoopMonitor(interval=0.02, threshold=0.08)
        probe = asyncio.create_task(monitor.run())
        await asyncio.create_task(blocking_handler(), name='scene:onebot:group:80001')
        await asyncio.sleep(0.05)
        probe.cancel()
        await asyncio.gather(probe, return_exceptions=True)
        return monitor.state()
    state = asyncio.run(run())
    assert state['stalls'] == 1 and not state['running']
    stall = state['recent'][0]
    assert stall['lag_ms'] >= 150 and state['max_lag_ms'] == stall['lag_ms']
    # Captured while the loop was held, not after it was released.
    assert stall['task'] == 'scene:onebot:group:80001'
    assert 'hold_the_loop' in stall['stack']
