"""Read-only runtime health for the panel: event loop stalls (and model provider health)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, Request

from ...runtime.loop_monitor import MONITOR, LoopMonitor


def register_host_diagnostics(app: FastAPI, *, user: Callable[[Request], str],
                              monitor: LoopMonitor = MONITOR) -> None:
    @app.get('/api/host/event-loop')
    async def event_loop(_: str = Depends(user)) -> dict:
        return monitor.state()
