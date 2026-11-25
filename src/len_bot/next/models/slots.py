"""Shared admission for actual model HTTP requests in one event loop.

Four priority tiers keep interactive chat responsive while background workers and upkeep run:
0. ``direct=True`` — @-mentions, private chats and operator actions (up to ``limit``).
1. Interactive router — normal scene chat, recap, vision and ASR (up to ``limit``).
2. ``worker=True`` — isolated sandboxed task workers (up to ``worker_limit``).
3. ``background=True`` — session upkeep, memory summaries and sticker labeling (up to ``background_limit``).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal

Tier = Literal["direct", "normal", "worker", "background"]
WORKER_BURST_LIMIT = 2


class ModelSlots:
    def __init__(self, limit: int):
        if limit <= 0:
            raise ValueError("model request slot limit must be positive")
        self.limit = limit
        self.admit: Callable[[str | None], None] | None = None
        self._active = 0
        self._worker_active = 0
        self._background_active = 0
        self._worker_streak = 0
        self._direct: deque[asyncio.Future[None]] = deque()
        self._normal: deque[asyncio.Future[None]] = deque()
        self._worker: deque[asyncio.Future[None]] = deque()
        self._background: deque[asyncio.Future[None]] = deque()

    @property
    def worker_limit(self) -> int:
        """Reserve one hot slot for interactive router turns whenever ``limit >= 2``."""
        return max(1, self.limit - 1)

    @property
    def background_limit(self) -> int:
        return max(1, self.limit // 2)

    def _can_take(self, tier: Tier) -> bool:
        if self._active >= self.limit:
            return False
        noninteractive_active = self._worker_active + self._background_active
        if tier == "worker":
            return noninteractive_active < self.worker_limit
        if tier == "background":
            return noninteractive_active < self.worker_limit and self._background_active < self.background_limit
        return True

    def _increment(self, tier: Tier) -> None:
        self._active += 1
        if tier == "worker":
            self._worker_active += 1
            self._worker_streak = self._worker_streak + 1 if self._background else 0
        elif tier == "background":
            self._background_active += 1
            self._worker_streak = 0

    def _fill(self) -> None:
        while self._active < self.limit:
            noninteractive_active = self._worker_active + self._background_active
            if self._direct:
                waiter, tier = self._direct.popleft(), "direct"
            elif self._normal:
                waiter, tier = self._normal.popleft(), "normal"
            elif noninteractive_active < self.worker_limit:
                if (
                    self._background
                    and self._background_active < self.background_limit
                    and (not self._worker or self._worker_streak >= WORKER_BURST_LIMIT)
                ):
                    waiter, tier = self._background.popleft(), "background"
                elif self._worker:
                    waiter, tier = self._worker.popleft(), "worker"
                else:
                    break
            else:
                break
            if waiter.cancelled():
                continue
            self._increment(tier)
            waiter.set_result(None)

    def _release(self, tier: Tier) -> None:
        self._active -= 1
        if tier == "worker":
            self._worker_active -= 1
        elif tier == "background":
            self._background_active -= 1
        self._fill()

    def resize(self, limit: int) -> None:
        """A lower limit lets active calls finish; a higher one releases queued calls now."""
        self.limit = limit
        self._fill()

    @asynccontextmanager
    async def slot(self, *, direct: bool = False, worker: bool = False, background: bool = False,
                   scene: str | None = None) -> AsyncIterator[None]:
        tier: Tier = ("direct" if direct else "background" if background
                      else "worker" if worker else "normal")
        background_due = (
            bool(self._background)
            and self._background_active < self.background_limit
            and self._worker_streak >= WORKER_BURST_LIMIT
        )
        higher_waiting = {
            "direct": bool(self._direct),
            "normal": bool(self._direct or self._normal),
            "worker": bool(self._direct or self._normal or self._worker or background_due),
            "background": bool(self._direct or self._normal or self._worker or self._background),
        }[tier]
        waiter: asyncio.Future[None] | None = None
        granted = False
        if self._can_take(tier) and not higher_waiting:
            self._increment(tier)
            granted = True
        else:
            waiter = asyncio.get_running_loop().create_future()
            queue = {
                "direct": self._direct,
                "normal": self._normal,
                "worker": self._worker,
                "background": self._background,
            }[tier]
            queue.append(waiter)
            self._fill()
        try:
            if waiter is not None:
                await waiter
            if self.admit is not None:
                self.admit(scene)
            yield
        finally:
            # A waiter may be granted and then cancelled before its await resumes.
            if granted or (waiter is not None and waiter.done() and not waiter.cancelled()):
                self._release(tier)
            elif waiter is not None:
                for queue in (self._direct, self._normal, self._worker, self._background):
                    if waiter in queue:
                        queue.remove(waiter)
                        break
