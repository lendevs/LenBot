"""Read-only runtime health for the panel: event loop stalls and model provider circuits."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, Request

from ...models.failover import HEALTH, ProviderHealth
from ...runtime.loop_monitor import MONITOR, LoopMonitor


def register_host_diagnostics(app: FastAPI, *, user: Callable[[Request], str],
                              monitor: LoopMonitor = MONITOR, health: ProviderHealth = HEALTH) -> None:
    @app.get('/api/host/event-loop')
    async def event_loop(_: str = Depends(user)) -> dict:
        return monitor.state()

    @app.get('/api/host/model-providers/health')
    async def provider_health(_: str = Depends(user)) -> dict:
        """Only roles opened with fallbacks appear; a role without them has no circuit."""
        return health.state()
