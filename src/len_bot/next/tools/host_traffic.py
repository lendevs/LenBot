"""Host-side web reads and searches made for a task: destination checks and byte accounting.

A task's data tools run on the host, so the worker's egress mode and limits apply to them here.
The task service opens ``metering`` around one call; the HTTP code of the web tools reports to it.
Outside a metering block, as in chat, everything is a no-op.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol

import httpx


class Hop(Protocol):
    """One HTTP request being counted."""
    def sent(self, amount: int) -> None: ...
    def received(self, amount: int) -> None: ...
    def close(self, error: str | None) -> None: ...


class HostTraffic(Protocol):
    def admit(self, url: str) -> None:
        """Raise ``EgressBlocked`` when the task's egress mode does not allow this URL's host."""

    def open(self, host: str, port: int, method: str, ip: str | None) -> Hop:
        """Start counting one request; raise ``EgressBlocked`` when a traffic limit is already reached."""


_current: ContextVar[HostTraffic | None] = ContextVar("host_traffic", default=None)


@contextmanager
def metering(traffic: HostTraffic) -> Iterator[None]:
    token = _current.set(traffic)
    try:
        yield
    finally:
        _current.reset(token)


def admit(url: str) -> None:
    """Check one destination URL against the task's egress mode, if a task call is being metered."""
    traffic = _current.get()
    if traffic is not None:
        traffic.admit(url)


class _CountedStream(httpx.AsyncByteStream):
    def __init__(self, inner: httpx.AsyncByteStream, hop: Hop):
        self.inner, self.hop = inner, hop

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.inner:
                self.hop.received(len(chunk))
                yield chunk
        except BaseException as error:
            self.hop.close(f"{type(error).__name__}: {error}"[:300])
            raise

    async def aclose(self) -> None:
        try:
            await self.inner.aclose()
        finally:
            self.hop.close(None)


class MeteredTransport(httpx.AsyncBaseTransport):
    """Counts every request through ``inner`` when a task call is being metered.

    ``host`` and ``ip`` name the logical destination when the request itself carries a numeric address.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, *, host: str | None = None, ip: str | None = None):
        self.inner, self.host, self.ip = inner, host, ip

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        traffic = _current.get()
        if traffic is None:
            return await self.inner.handle_async_request(request)
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        hop = traffic.open(self.host or request.url.host, port, request.method, self.ip)
        head = len(request.method) + len(request.url.raw_path) + 12 + sum(
            len(name) + len(value) + 4 for name, value in request.headers.raw)
        try:
            hop.sent(head + int(request.headers.get("content-length", 0)))
            response = await self.inner.handle_async_request(request)
        except BaseException as error:
            hop.close(f"{type(error).__name__}: {error}"[:300])
            raise
        response.stream = _CountedStream(response.stream, hop)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
