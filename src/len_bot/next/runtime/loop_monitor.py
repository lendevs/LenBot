"""Warn when the event loop stalls: a slow synchronous call delays every scene, the panel and OneBot."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .logs import log_event

logger = logging.getLogger(__name__)

# Sleep between probes and the lag beyond which one warning is logged.
INTERVAL_SECONDS = 0.5
THRESHOLD_SECONDS = 0.5


async def watch_event_loop(*, interval: float = INTERVAL_SECONDS, threshold: float = THRESHOLD_SECONDS,
                           clock: Callable[[], float] = time.monotonic,
                           on_stall: Callable[[float], None] | None = None) -> None:
    """Run until cancelled; a probe that wakes up more than ``threshold`` late logs ``event_loop_stall``."""
    while True:
        expected = clock() + interval
        await asyncio.sleep(interval)
        lag = clock() - expected
        if lag > threshold:
            log_event(logger, 'event_loop_stall', f'事件循环卡顿 {lag * 1000:.0f} ms', level=logging.WARNING,
                      lag_ms=round(lag * 1000), threshold_ms=round(threshold * 1000))
            if on_stall is not None:
                on_stall(lag)
