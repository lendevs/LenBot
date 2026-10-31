"""A task's host-side web calls on the same connection and byte records as its own egress."""

from __future__ import annotations

import itertools
import time
from urllib.parse import urlsplit

from .egress_policy import host_refusal
from .egress_usage import EgressUsage

# Wire ids of the egress proxy count up from 1 per task; host-side calls take their own range.
_FIRST_ID = 1 << 40
_ids = itertools.count(_FIRST_ID)


class _Hop:
    def __init__(self, usage: EgressUsage, scene: str, task_id: int, wire_id: int):
        self.usage, self.scene, self.task_id, self.wire_id = usage, scene, task_id, wire_id
        self.ip: str | None = None
        self.closed = False

    def _count(self, side: str, amount: int) -> None:
        if amount and not self.closed:
            self.usage.before_bytes(self.scene, self.task_id, self.wire_id, side, amount)
            self.usage.on_bytes(self.scene, self.task_id, self.wire_id, side, amount)

    def sent(self, amount: int) -> None:
        self._count("up", amount)

    def received(self, amount: int) -> None:
        self._count("down", amount)

    def close(self, error: str | None) -> None:
        if self.closed:
            return
        self.closed = True
        self.usage.on_connection(self.scene, self.task_id, {
            "connection_id": self.wire_id, "phase": "end", "ip": self.ip, "ended": time.time(), "error": error})


class TaskHostTraffic:
    """Destination checks and byte counts for the web tools one task calls on the host."""

    def __init__(self, usage: EgressUsage, scene: str, task_id: int):
        self.usage, self.scene, self.task_id = usage, scene, task_id

    def admit(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.hostname is None:
            raise ValueError(f"网址缺少主机名：{url[:200]}")
        try:
            host = parts.hostname.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError(f"主机名无法转为域名：{parts.hostname[:200]}") from error
        settings = self.usage.config.worker.egress
        reason = host_refusal(host, settings.mode, settings.allowed_hosts)
        if reason is not None:
            self.usage.refuse(self.scene, self.task_id, host, parts.port or (443 if parts.scheme == "https" else 80),
                              "GET", reason)

    def open(self, host: str, port: int, method: str, ip: str | None) -> _Hop:
        wire_id = next(_ids)
        # The host's own search and reader endpoints are fixed by its configuration, not chosen by the task.
        self.usage.on_connection(self.scene, self.task_id, {
            "connection_id": wire_id, "phase": "start", "host": host, "port": port, "method": method,
            "started": time.time()}, check_host=False)
        hop = _Hop(self.usage, self.scene, self.task_id, wire_id)
        if ip is not None:
            hop.ip = ip
            self.usage.on_connection(self.scene, self.task_id,
                                     {"connection_id": wire_id, "phase": "connected", "ip": ip})
        return hop
