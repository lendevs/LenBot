"""Shared admission for actual model HTTP requests in one event loop."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager


class ModelSlots:
    def __init__(self, limit: int):
        if limit <= 0:
            raise ValueError("model request slot limit must be positive")
        self.limit = limit
        self.admit: Callable[[str | None], None] | None = None
        self._active = 0
        self._background_active = 0
        self._direct: deque[asyncio.Future[None]] = deque()
        self._normal: deque[asyncio.Future[None]] = deque()
        self._background: deque[tuple[asyncio.Future[None], bool]] = deque()

    @property
    def background_limit(self) -> int:
        return max(1, self.limit // 2)

    def _fill(self) -> None:
        while self._active < self.limit:
            if self._direct:
                waiter = self._direct.popleft()
                is_bg = False
            elif self._normal:
                waiter = self._normal.popleft()
                is_bg = False
            elif self._background and self._background_active < self.background_limit:
                waiter, is_bg = self._background.popleft()
            else:
                break
            if waiter.cancelled():
                continue
            self._active += 1
            if is_bg:
                self._background_active += 1
            waiter.set_result(None)

    def _release(self, *, background: bool = False) -> None:
        self._active -= 1
        if background:
            self._background_active -= 1
        self._fill()

    def resize(self, limit: int) -> None:
        """A lower limit lets active calls finish; a higher one releases queued calls now."""
        self.limit = limit
        self._fill()

    @asynccontextmanager
    async def slot(self, *, direct: bool = False, background: bool = False,
                   scene: str | None = None) -> AsyncIterator[None]:
        waiter: asyncio.Future[None] | None = None
        granted = False
        is_bg = background and not direct
        if is_bg:
            can_grant_now = (self._active < self.limit and self._background_active < self.background_limit
                             and not (self._direct or self._normal or self._background))
        else:
            can_grant_now = self._active < self.limit and not (self._direct or self._normal)
        if can_grant_now:
            self._active += 1
            if is_bg:
                self._background_active += 1
            granted = True
        else:
            waiter = asyncio.get_running_loop().create_future()
            if direct:
                self._direct.append(waiter)
            elif is_bg:
                self._background.append((waiter, True))
            else:
                self._normal.append(waiter)
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
                self._release(background=is_bg)
            elif waiter is not None:
                if direct and waiter in self._direct:
                    self._direct.remove(waiter)
                elif is_bg:
                    self._background = deque(item for item in self._background if item[0] is not waiter)
                elif waiter in self._normal:
                    self._normal.remove(waiter)
