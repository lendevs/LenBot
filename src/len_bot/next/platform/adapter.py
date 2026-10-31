"""The chat platform behind the runtime: one adapter per configured platform.

The runtime only uses this interface. An adapter owns its transport (WebSocket, HTTP polling ...),
turns each inbound event into a raw dict for ``on_event`` and parses it back with ``parse``; the
runtime stores the raw dict next to the parsed message. Scenes are ``<platform>:group:<id>`` or
``<platform>:private:<id>``, accounts ``<platform>:<id>``, with ``name`` as the platform prefix.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .messages import ChatMessage, Notice, SendResult, UploadResult

if TYPE_CHECKING:
    from ..config import SharedConfig


class PlatformCallError(RuntimeError):
    """A platform call that failed; ``submitted`` tells whether it had entered the actual send."""

    def __init__(self, message: str, *, submitted: bool):
        super().__init__(message)
        self.submitted = submitted


@runtime_checkable
class PlatformAdapter(Protocol):
    name: str

    @property
    def connected(self) -> bool: ...

    @property
    def addresses(self) -> list[tuple]: ...

    async def start(self) -> None:
        """Open the transport; a wrong address or credential fails here."""

    async def close(self) -> None: ...

    async def wait_connected(self, timeout_seconds: float | None) -> None: ...

    async def wait_terminated(self) -> None:
        """Return when the transport ended for good (closed, or failed beyond reconnecting)."""

    def parse(self, raw: dict) -> ChatMessage | Notice | None:
        """The message or notice of one raw event; None for events the runtime ignores."""

    async def identify(self) -> str:
        """The bot's own account as ``<platform>:<id>``, as the platform confirms it."""

    async def send_message(self, message: ChatMessage, *, image_bytes: bytes | None = None) -> SendResult: ...

    async def upload_file(self, scene: str, file: str, name: str) -> UploadResult: ...

    async def scene_title(self, scene: str) -> tuple[str, int | None]:
        """The group name and member count, or the private contact's name, for labelling the scene."""

    async def call(self, action: str, params: dict) -> dict:
        """A platform-specific action (a OneBot action) with its raw answer."""


class PlatformGroup:
    """Several adapters behind one interface; each scene goes to the adapter named by its prefix.

    Every adapter must start; afterwards each one connects, reconnects and ends on its own, so a
    platform that drops leaves the others running. ``parse`` runs inside the delivering adapter's
    ``on_event`` call, which tells the group whose event it is.
    """

    def __init__(self, openers: dict[str, Callable[..., PlatformAdapter]], *, on_event: Callable[[dict], None],
                 on_error: Callable[[str], None], on_connection_change: Callable[[], None] | None = None):
        self.on_event = on_event
        self._delivering: PlatformAdapter | None = None
        self.adapters = {name: open(on_event=lambda raw, name=name: self._deliver(name, raw), on_error=on_error,
                                    on_connection_change=on_connection_change)
                         for name, open in openers.items()}
        self.name = '+'.join(self.adapters)

    def _deliver(self, name: str, raw: dict) -> None:
        self._delivering = self.adapters[name]
        try:
            self.on_event(raw)
        finally:
            self._delivering = None

    def member(self, scene_or_name: str) -> PlatformAdapter | None:
        return self.adapters.get(scene_or_name.split(':', 1)[0])

    def _for(self, scene: str) -> PlatformAdapter:
        adapter = self.member(scene)
        if adapter is None:
            raise PlatformCallError(f'no adapter for the platform of {scene!r}', submitted=False)
        return adapter

    @property
    def connected(self) -> bool:
        return any(adapter.connected for adapter in self.adapters.values())

    @property
    def addresses(self) -> list[tuple]:
        return [address for adapter in self.adapters.values() for address in adapter.addresses]

    async def start(self) -> None:
        results = await asyncio.gather(*(adapter.start() for adapter in self.adapters.values()), return_exceptions=True)
        failed = [(name, result) for name, result in zip(self.adapters, results) if isinstance(result, BaseException)]
        if failed:
            await self.close()
            for _, result in failed:
                if not isinstance(result, Exception):
                    raise result
            raise PlatformCallError('；'.join(f'{name}: {error}' for name, error in failed), submitted=False)

    async def close(self) -> None:
        results = await asyncio.gather(*(adapter.close() for adapter in self.adapters.values()), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def wait_connected(self, timeout_seconds: float | None) -> None:
        """Return once any adapter is connected; scenes wait for their own adapter separately."""
        waits = [asyncio.create_task(adapter.wait_connected(timeout_seconds)) for adapter in self.adapters.values()]
        try:
            pending = set(waits)
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                if any(task.exception() is None for task in done):
                    return
            raise waits[0].exception()
        finally:
            for task in waits:
                task.cancel()
            await asyncio.gather(*waits, return_exceptions=True)

    async def wait_terminated(self) -> None:
        await asyncio.gather(*(adapter.wait_terminated() for adapter in self.adapters.values()))

    def parse(self, raw: dict) -> ChatMessage | Notice | None:
        if self._delivering is None:
            raise ValueError('a grouped platform parses only the event its adapter is delivering')
        return self._delivering.parse(raw)

    async def identify(self) -> str:
        raise PlatformCallError('a platform group has one account per platform; identify a member', submitted=False)

    async def send_message(self, message: ChatMessage, *, image_bytes: bytes | None = None) -> SendResult:
        adapter = self.member(message.scene)
        if adapter is None:
            return SendResult('failed', None, f'no adapter for the platform of {message.scene!r}')
        return await adapter.send_message(message, image_bytes=image_bytes)

    async def upload_file(self, scene: str, file: str, name: str) -> UploadResult:
        adapter = self.member(scene)
        if adapter is None:
            return UploadResult('failed', None, f'no adapter for the platform of {scene!r}', None)
        return await adapter.upload_file(scene, file, name)

    async def scene_title(self, scene: str) -> tuple[str, int | None]:
        return await self._for(scene).scene_title(scene)

    async def call(self, action: str, params: dict) -> dict:
        raise PlatformCallError(f'platform action {action!r} needs the adapter of one platform', submitted=False)


def adapter_for(platform: PlatformAdapter | None, scene_or_name: str) -> PlatformAdapter | None:
    """The adapter serving a scene (or a platform name): a group's member, or the single adapter of that platform."""
    if isinstance(platform, PlatformGroup):
        return platform.member(scene_or_name)
    return platform if platform is not None and platform.name == scene_or_name.split(':', 1)[0] else None


def _open_onebot(config: SharedConfig, **callbacks) -> PlatformAdapter:
    from .onebot import OneBot
    return OneBot(config.onebot, bot_id=config.bot_id, **callbacks)


def _open_telegram(config: SharedConfig, **callbacks) -> PlatformAdapter:
    from .telegram import Telegram
    return Telegram(config.telegram, **callbacks)


def _open_feishu(config: SharedConfig, **callbacks) -> PlatformAdapter:
    from .feishu import Feishu
    return Feishu(config.feishu, **callbacks)


OPENERS = {'onebot': _open_onebot, 'telegram': _open_telegram, 'feishu': _open_feishu}


def open_platform(config: SharedConfig, *, on_event: Callable[[dict], None], on_error: Callable[[str], None],
                  on_connection_change: Callable[[], None] | None = None) -> PlatformAdapter | None:
    """The configured platform's adapter, a group when several are configured, or None for stdin and panel-only hosts."""
    callbacks = dict(on_event=on_event, on_error=on_error, on_connection_change=on_connection_change)
    names = config.platform_names
    if not names:
        return None
    if len(names) == 1:
        return OPENERS[names[0]](config, **callbacks)
    return PlatformGroup({name: (lambda name=name, **member: OPENERS[name](config, **member)) for name in names},
                         **callbacks)
