"""One process's explicit stop/restart intent; no persistent restart queue."""

from collections.abc import Callable
from dataclasses import dataclass, field
import os
import time
from typing import Literal

RESTART_EXIT = 75
# The host wrote <deployment>/updates/request.json; the launcher switches versions before the next start.
UPDATE_EXIT = 76


@dataclass
class HostLifecycle:
    restartable: bool = False
    intent: Literal['running', 'stop', 'restart', 'update'] = 'running'
    started_at: float = field(default_factory=time.time)
    shutdown: Callable[[], None] | None = None

    def process(self) -> dict:
        return {'pid': os.getpid(), 'started_at': self.started_at}

    def require_restart(self) -> None:
        if not self.restartable or self.shutdown is None:
            raise RuntimeError('当前宿主不具备重启能力；请使用 len-bot 启动器运行')
        if self.intent == 'stop':
            raise RuntimeError('宿主正在停止')

    async def restart(self) -> None:
        self.require_restart()
        self.intent = 'restart'
        self.shutdown()

    async def update(self) -> None:
        """Exit for the launcher to carry out the request written beside the instance."""
        self.require_restart()
        self.intent = 'update'
        self.shutdown()

    def stop(self) -> None:
        self.intent = 'stop'
        if self.shutdown is not None:
            self.shutdown()
