"""A failed retention batch keeps its error for display and is retried with a growing delay, not skipped."""

import asyncio
from types import SimpleNamespace

import pytest

from len_bot.next.runtime import retention
from len_bot.next.runtime.retention import PERIOD_SECONDS, RETRY_SECONDS, Retention

EMPTY = {key: 0 for key in ('model_snapshots', 'auxiliary_snapshots', 'task_snapshots', 'turns', 'messages',
                            'notices', 'memory_snapshots', 'extraction_jobs')}


class Clock:
    """Stands in for the wait between cycles: records each delay and releases the loop at once."""

    def __init__(self, runtime, stop_after):
        self.delays, self.runtime, self.stop_after = [], runtime, stop_after

    async def wait(self, tasks, *, timeout, return_when):
        self.delays.append(timeout)
        if len(self.delays) >= self.stop_after:
            self.runtime.stopped.set()
        await asyncio.sleep(0)
        return set(), set(tasks)


def fixture(monkeypatch, outcomes, stop_after):
    runtime = SimpleNamespace(stopped=asyncio.Event(), config=SimpleNamespace(retention=object()),
                              notify=lambda: None, _emit=lambda event: events.append(event))
    events = []
    work = Retention(runtime)
    results = iter(outcomes)

    async def batch_async(*, preview=False):
        outcome = next(results)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    work.batch_async = batch_async
    clock = Clock(runtime, stop_after)
    monkeypatch.setattr(retention.asyncio, 'wait', clock.wait)
    return work, clock, events


@pytest.mark.asyncio
async def test_failed_batch_is_retried_with_doubling_delay_and_error_clears_on_success(monkeypatch):
    failure = OSError('disk full')
    work, clock, events = fixture(monkeypatch, [failure, failure, failure, EMPTY, EMPTY], 5)
    await asyncio.wait_for(work.run(), 5)
    assert clock.delays == [RETRY_SECONDS, RETRY_SECONDS * 2, RETRY_SECONDS * 4, PERIOD_SECONDS, PERIOD_SECONDS]
    assert [event['error'] for event in events] == ['OSError: disk full'] * 3
    assert work.error is None and work.retry is None


@pytest.mark.asyncio
async def test_error_stays_visible_until_a_batch_succeeds_and_delay_is_capped(monkeypatch):
    failure = OSError('locked')
    work, clock, _ = fixture(monkeypatch, [failure] * 12, 12)
    await asyncio.wait_for(work.run(), 5)
    assert work.error == 'OSError: locked'
    assert clock.delays[0] == RETRY_SECONDS and max(clock.delays) == PERIOD_SECONDS
    assert clock.delays == sorted(clock.delays)


@pytest.mark.asyncio
async def test_wake_restarts_the_backoff(monkeypatch):
    work, _, _ = fixture(monkeypatch, [], 1)
    work.error, work.retry = 'OSError: locked', RETRY_SECONDS * 8
    work.wake()
    assert work.error is None and work.retry is None and work.changed.is_set()
