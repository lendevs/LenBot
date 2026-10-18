"""Event loop stall monitoring: a slow synchronous call delays every scene, the panel and OneBot.

An async probe sleeps ``interval`` and measures how late it wakes. A watchdog thread checks the
probe's heartbeat: once the loop has not run the probe for ``threshold`` past its wake time, it
captures the event loop thread's stack and the asyncio task running at that moment, which is the
code holding the loop, not what runs after it lets go. When the probe finally wakes, one
``event_loop_stall`` event is logged with that stack and the totals the panel reads are updated.

When the whole process did not run (system sleep, a stopped or paused VM or container), the
monotonic clock can still advance on some systems and the probe wakes up very late. The watchdog
thread then missed its own wake-ups for as long; such a gap of ``PAUSE_SECONDS`` or more is logged
once as ``event_loop_paused`` and not counted as a stall.
"""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
import logging
import sys
import threading
import time
import traceback

from .logs import log_event

logger = logging.getLogger(__name__)

# Sleep between probes and the lag beyond which one stall is recorded.
INTERVAL_SECONDS = 0.5
THRESHOLD_SECONDS = 0.5
HISTORY = 20
# A probe this late while the watchdog thread was also not running is a process pause, not a stall.
PAUSE_SECONDS = 30.0
STACK_FRAMES = 30


@dataclass(frozen=True)
class Stall:
    at: float               # wall-clock time the probe woke up
    lag_ms: int
    task: str | None        # asyncio task running while the loop was held, when the watchdog saw it
    stack: str | None       # the event loop thread's stack at that moment


@dataclass
class _Capture:
    beat: float
    task: str | None
    stack: str


class LoopMonitor:
    def __init__(self, *, interval: float = INTERVAL_SECONDS, threshold: float = THRESHOLD_SECONDS,
                 history: int = HISTORY, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time):
        self.interval, self.threshold = interval, threshold
        self.clock, self.wall = clock, wall
        self.stalls: deque[Stall] = deque(maxlen=history)
        self.count = 0
        self.total_ms = 0
        self.max_ms = 0
        self.probes = 0
        self.started_at: float | None = None
        self.running = False
        self.pauses = 0
        self._lock = threading.Lock()
        self._beat = 0.0
        self._capture: _Capture | None = None
        # Longest gap between two watchdog wake-ups since the probe last woke, and its last wake-up.
        self._watch_gap = 0.0
        self._watch_woke = 0.0

    def _watch(self, loop: asyncio.AbstractEventLoop, thread_id: int, stop: threading.Event) -> None:
        while not stop.wait(min(self.interval, self.threshold) / 2):
            now = self.clock()
            with self._lock:
                self._watch_gap = max(self._watch_gap, now - self._watch_woke)
                self._watch_woke = now
            with self._lock:
                beat = self._beat
                if self.clock() - beat <= self.threshold or (
                        self._capture is not None and self._capture.beat == beat):
                    continue
            frame = sys._current_frames().get(thread_id)
            if frame is None:
                continue
            stack = ''.join(traceback.format_stack(frame, limit=STACK_FRAMES))
            task = asyncio.current_task(loop)
            with self._lock:
                if self._beat == beat:
                    self._capture = _Capture(beat, None if task is None else task.get_name(), stack)

    def _record(self, lag: float, capture: _Capture | None) -> Stall:
        stall = Stall(at=self.wall(), lag_ms=round(lag * 1000),
                      task=None if capture is None else capture.task,
                      stack=None if capture is None else capture.stack)
        self.stalls.append(stall)
        self.count += 1
        self.total_ms += stall.lag_ms
        self.max_ms = max(self.max_ms, stall.lag_ms)
        log_event(logger, 'event_loop_stall', f'事件循环卡顿 {stall.lag_ms} ms', level=logging.WARNING,
                  lag_ms=stall.lag_ms, threshold_ms=round(self.threshold * 1000), task=stall.task,
                  stack=stall.stack)
        return stall

    async def run(self, on_stall: Callable[[float], None] | None = None) -> None:
        """Run until cancelled."""
        loop = asyncio.get_running_loop()
        stop = threading.Event()
        with self._lock:
            self._beat, self._capture = self.clock(), None
            self._watch_woke, self._watch_gap = self._beat, 0.0
        watchdog = threading.Thread(target=self._watch, args=(loop, threading.get_ident(), stop),
                                    name='lenbot-loop-watchdog', daemon=True)
        self.running, self.started_at = True, self.wall()
        watchdog.start()
        try:
            while True:
                expected = self.clock() + self.interval
                with self._lock:
                    self._beat = expected
                await asyncio.sleep(self.interval)
                lag = self.clock() - expected
                with self._lock:
                    capture, self._capture = self._capture, None
                    # After a pause the probe may wake before the watchdog does: count its current gap too.
                    watch_gap = max(self._watch_gap, self.clock() - self._watch_woke)
                    self._watch_gap = 0.0
                self.probes += 1
                if lag >= PAUSE_SECONDS and watch_gap >= lag - self.interval:
                    # The watchdog thread did not run either: the process was paused, not the loop held.
                    self.pauses += 1
                    log_event(logger, 'event_loop_paused', f'进程约 {lag:.0f} 秒没有运行（例如系统休眠），不计为卡顿',
                              lag_ms=round(lag * 1000), watchdog_gap_ms=round(watch_gap * 1000))
                elif lag > self.threshold:
                    self._record(lag, capture)
                    if on_stall is not None:
                        on_stall(lag)
        finally:
            self.running = False
            stop.set()

    def state(self) -> dict:
        return {'running': self.running, 'started_at': self.started_at,
                'interval_ms': round(self.interval * 1000), 'threshold_ms': round(self.threshold * 1000),
                'probes': self.probes, 'stalls': self.count, 'pauses': self.pauses, 'stalled_ms_total': self.total_ms,
                'max_lag_ms': self.max_ms, 'recent': [asdict(item) for item in reversed(self.stalls)]}


# The host's loop. One per process: the panel reads the same instance the host runs.
MONITOR = LoopMonitor()


async def watch_event_loop(*, interval: float = INTERVAL_SECONDS, threshold: float = THRESHOLD_SECONDS,
                           clock: Callable[[], float] = time.monotonic,
                           on_stall: Callable[[float], None] | None = None) -> None:
    """Run a fresh monitor until cancelled; a probe that wakes up more than ``threshold`` late logs ``event_loop_stall``."""
    await LoopMonitor(interval=interval, threshold=threshold, clock=clock).run(on_stall)
