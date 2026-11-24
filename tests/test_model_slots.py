"""Priority scheduling, worker reservation, and cancellation safety for ModelSlots."""

import asyncio

import pytest

from len_bot.next.models.slots import ModelSlots


async def _yield_loop(steps: int = 3) -> None:
    for _ in range(steps):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_four_tier_priority_order_is_direct_normal_worker_background():
    slots = ModelSlots(1)
    held = asyncio.Event()
    release_holder = asyncio.Event()
    order: list[str] = []

    async def holder() -> None:
        async with slots.slot():
            held.set()
            await release_holder.wait()

    async def acquire(name: str, **kwargs: bool) -> None:
        async with slots.slot(**kwargs):
            order.append(name)

    holder_task = asyncio.create_task(holder())
    await held.wait()

    waiters = [
        asyncio.create_task(acquire("background", background=True)),
        asyncio.create_task(acquire("worker", worker=True)),
        asyncio.create_task(acquire("normal")),
        asyncio.create_task(acquire("direct", direct=True)),
    ]
    await _yield_loop()
    assert order == []

    release_holder.set()
    await asyncio.gather(holder_task, *waiters)

    assert order == ["direct", "normal", "worker", "background"]
    assert slots._active == 0
    assert slots._worker_active == 0
    assert slots._background_active == 0


@pytest.mark.asyncio
async def test_worker_limit_reserves_hot_slot_for_interactive_turns():
    slots = ModelSlots(4)
    assert slots.worker_limit == 3

    entered = [asyncio.Event() for _ in range(4)]
    releases = [asyncio.Event() for _ in range(4)]

    async def worker_turn(index: int) -> None:
        async with slots.slot(worker=True):
            entered[index].set()
            await releases[index].wait()

    workers = [asyncio.create_task(worker_turn(i)) for i in range(4)]
    await _yield_loop()

    assert sum(event.is_set() for event in entered) == 3
    assert not entered[3].is_set()
    assert slots._active == 3
    assert slots._worker_active == 3

    normal_entered = asyncio.Event()
    async with slots.slot():
        normal_entered.set()
        assert slots._active == 4
        assert not entered[3].is_set()
    assert normal_entered.is_set()

    direct_entered = asyncio.Event()
    async with slots.slot(direct=True):
        direct_entered.set()
        assert slots._active == 4
        assert not entered[3].is_set()
    assert direct_entered.is_set()

    assert not entered[3].is_set()
    releases[0].set()
    await asyncio.wait_for(entered[3].wait(), timeout=1.0)
    assert slots._worker_active == 3

    for event in releases[1:]:
        event.set()
    await asyncio.gather(*workers)

    assert slots._active == 0
    assert slots._worker_active == 0


@pytest.mark.asyncio
async def test_limit_one_allows_worker_without_deadlock():
    slots = ModelSlots(1)
    assert slots.worker_limit == 1

    acquired = False
    async with slots.slot(worker=True):
        acquired = True
        assert slots._active == 1
        assert slots._worker_active == 1
    assert acquired
    assert slots._active == 0
    assert slots._worker_active == 0

    held = asyncio.Event()
    release_holder = asyncio.Event()
    worker_done = asyncio.Event()

    async def holder() -> None:
        async with slots.slot():
            held.set()
            await release_holder.wait()

    async def queued_worker() -> None:
        async with slots.slot(worker=True):
            worker_done.set()

    holder_task = asyncio.create_task(holder())
    await held.wait()
    worker_task = asyncio.create_task(queued_worker())
    await _yield_loop()
    assert not worker_done.is_set()

    release_holder.set()
    await asyncio.wait_for(asyncio.gather(holder_task, worker_task), timeout=1.0)
    assert worker_done.is_set()
    assert slots._active == 0
    assert slots._worker_active == 0


@pytest.mark.asyncio
async def test_cancelled_waiters_do_not_leak_slot_counts():
    slots = ModelSlots(1)
    held = asyncio.Event()
    release_holder = asyncio.Event()

    async def holder() -> None:
        async with slots.slot():
            held.set()
            await release_holder.wait()

    async def waiter(*, worker: bool = False, background: bool = False) -> None:
        async with slots.slot(worker=worker, background=background):
            await asyncio.sleep(0)

    holder_task = asyncio.create_task(holder())
    await held.wait()

    # Cancel a waiter while still queued.
    cancelled_queued = asyncio.create_task(waiter(worker=True))
    cancelled_bg = asyncio.create_task(waiter(background=True))
    await _yield_loop()
    cancelled_queued.cancel()
    cancelled_bg.cancel()
    for task in (cancelled_queued, cancelled_bg):
        with pytest.raises(asyncio.CancelledError):
            await task

    # Queue two workers, release holder (granting first synchronously), then cancel first before it resumes.
    granted_then_cancelled = asyncio.create_task(waiter(worker=True))
    second_worker_entered = asyncio.Event()

    async def second_worker() -> None:
        async with slots.slot(worker=True):
            second_worker_entered.set()

    second_task = asyncio.create_task(second_worker())
    await _yield_loop()

    release_holder.set()
    await holder_task
    granted_then_cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await granted_then_cancelled

    await asyncio.wait_for(second_task, timeout=1.0)
    assert second_worker_entered.is_set()
    assert slots._active == 0
    assert slots._worker_active == 0
    assert slots._background_active == 0
    assert not slots._direct and not slots._normal and not slots._worker and not slots._background


@pytest.mark.asyncio
async def test_worker_plus_background_share_noninteractive_cap_preserving_hot_slot():
    slots = ModelSlots(4)
    entered: list[str] = []
    release = asyncio.Event()

    async def hold(label: str, *, worker: bool = False, background: bool = False) -> None:
        async with slots.slot(worker=worker, background=background):
            entered.append(label)
            await release.wait()

    tasks = [
        asyncio.create_task(hold("w1", worker=True)),
        asyncio.create_task(hold("w2", worker=True)),
        asyncio.create_task(hold("bg1", background=True)),
        asyncio.create_task(hold("w3", worker=True)),
        asyncio.create_task(hold("bg2", background=True)),
    ]
    await _yield_loop()
    # Combined worker + background must not exceed limit - 1 (3), leaving 1 hot slot for normal chat.
    assert len(entered) == 3
    assert slots._worker_active + slots._background_active == 3

    async with slots.slot():
        assert slots._active == 4

    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2])
async def test_continuous_worker_stream_cannot_starve_queued_background(limit: int):
    slots = ModelSlots(limit)
    assert slots.worker_limit == 1
    assert slots.background_limit == 1

    order: list[str] = []
    w0_entered = asyncio.Event()
    w0_release = asyncio.Event()
    bg_entered = asyncio.Event()

    async def hold_w0() -> None:
        async with slots.slot(worker=True):
            order.append("w0")
            w0_entered.set()
            await w0_release.wait()

    async def run_bg() -> None:
        async with slots.slot(background=True):
            order.append("bg1")
            bg_entered.set()

    async def run_worker(name: str, next_spawn: list[asyncio.Task[None]], remaining: list[str]) -> None:
        async with slots.slot(worker=True):
            order.append(name)
            if remaining:
                nxt = remaining.pop(0)
                next_spawn.append(asyncio.create_task(run_worker(nxt, next_spawn, remaining)))
            await asyncio.sleep(0)

    w0_task = asyncio.create_task(hold_w0())
    await w0_entered.wait()

    bg_task = asyncio.create_task(run_bg())
    spawned: list[asyncio.Task[None]] = []
    remaining = ["w2", "w3", "w4"]
    w1_task = asyncio.create_task(run_worker("w1", spawned, remaining))
    await _yield_loop()

    w0_release.set()
    await asyncio.wait_for(bg_entered.wait(), timeout=1.0)
    await asyncio.gather(w0_task, bg_task, w1_task, *spawned)

    # At most WORKER_BURST_LIMIT (2) workers may run ahead of a waiting background task.
    assert order == ["w0", "w1", "w2", "bg1", "w3", "w4"]
    assert slots._active == 0
    assert slots._worker_active == 0
    assert slots._background_active == 0
    assert not slots._worker and not slots._background
