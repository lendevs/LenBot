"""Live panel events; each reader owns a bounded queue, never a replay log."""

from __future__ import annotations

import asyncio
from collections import deque
import threading
import time


class Subscription:
    def __init__(self, hub: EventHub):
        self.hub = hub
        self.loop = asyncio.get_running_loop()
        self.ready = asyncio.Event()
        self.queue: deque[dict] = deque()

    async def get(self) -> dict:
        while True:
            with self.hub.lock:
                if self.queue:
                    return self.queue.popleft()
                self.ready.clear()
            await self.ready.wait()

    def close(self) -> None:
        with self.hub.lock:
            self.hub.readers.remove(self)


class EventHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.readers: set[Subscription] = set()
        self.seq = 0
        self.changed_at = 0.0
        self.pending_changed: tuple[str | None, dict] | None = None

    def subscribe(self) -> tuple[Subscription, dict]:
        reader = Subscription(self)
        with self.lock:
            self.readers.add(reader)
            hello = {"type": "hello", "seq": self.seq}
        return reader, hello

    def publish(self, type: str, scene: str | None = None, **fields) -> None:
        with self.lock:
            if type == "host.changed":
                if self.pending_changed is not None:
                    self.pending_changed = (scene, fields)
                    return
                delay = self.changed_at + 0.25 - time.monotonic()
                if delay > 0:
                    if self.readers:
                        if self.pending_changed is None:
                            loop = next(iter(self.readers)).loop
                            loop.call_soon_threadsafe(self._schedule_changed, loop, delay)
                        self.pending_changed = (scene, fields)
                    return
                self.changed_at = time.monotonic()
            self._publish(type, scene, fields)

    def _schedule_changed(self, loop: asyncio.AbstractEventLoop, delay: float) -> None:
        loop.call_later(delay, self._flush_changed)

    def _flush_changed(self) -> None:
        with self.lock:
            scene, fields = self.pending_changed
            self.pending_changed = None
            self.changed_at = time.monotonic()
            self._publish("host.changed", scene, fields)

    def _publish(self, type: str, scene: str | None, fields: dict) -> None:
        self.seq += 1
        event = {**fields, "seq": self.seq, "at": time.time(), "type": type, "scene": scene}
        for reader in self.readers:
            wake = not reader.queue
            if len(reader.queue) == 2000:
                reader.queue.clear()
                reader.queue.append({"seq": self.seq, "at": event["at"], "type": "resync", "scene": None})
            else:
                reader.queue.append(event)
            if wake:
                reader.loop.call_soon_threadsafe(reader.ready.set)
