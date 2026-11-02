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

    async def download(self, data: dict, max_bytes: int) -> bytes:
        """The bytes of an inbound image, voice or file segment that names a platform file instead of a URL."""


async def read_capped(chunks, max_bytes: int) -> bytes:
    """Collect an async byte stream, refusing it once it passes ``max_bytes``."""
    body = bytearray()
    async for chunk in chunks:
        body += chunk
        if len(body) > max_bytes:
            raise ValueError(f"download exceeds {max_bytes} bytes")
    return bytes(body)


class PlatformGroup:
    """The configured adapters behind one interface; each scene goes to the adapter named by its prefix.

    Every adapter must start; afterwards each one connects, reconnects and ends on its own, so a
    platform that drops leaves the others running. ``parse`` runs inside the delivering adapter's
    ``on_event`` call, which tells the group whose event it is. ``apply`` replaces members while
    the host runs; the group ends only when its current members have all ended.
    """

    def __init__(self, openers: dict[str, Callable[..., PlatformAdapter]], *, on_event: Callable[[dict], None],
                 on_error: Callable[[str], None], on_connection_change: Callable[[], None] | None = None):
        self.on_event = on_event
        self._callbacks = dict(on_error=on_error, on_connection_change=on_connection_change)
        self._delivering: PlatformAdapter | None = None
        self._members_changed = asyncio.Event()
        self._apply_lock = asyncio.Lock()
        self._applying = False
        self.adapters = {name: self._open(name, open) for name, open in openers.items()}

    def _open(self, name: str, open: Callable[..., PlatformAdapter]) -> PlatformAdapter:
        adapter = open(on_event=lambda raw: self._deliver(adapter, raw), **self._callbacks)
        return adapter

    def _changed(self) -> None:
        """Wake every waiter of the current membership; later waiters wait for the next change."""
        self._members_changed.set()
        self._members_changed = asyncio.Event()

    @property
    def name(self) -> str:
        return '+'.join(self.adapters)

    async def apply(self, openers: dict[str, Callable[..., PlatformAdapter] | None]) -> None:
        """Replace named members, retain entries set to None, and remove omitted members."""
        async with self._apply_lock:
            self._applying = True
            try:
                await self._apply(openers)
            finally:
                self._applying = False
                self._changed()

    async def _apply(self, openers: dict[str, Callable[..., PlatformAdapter] | None]) -> None:
        stale = [name for name in self.adapters if openers.get(name) is not None or name not in openers]
        closing = [self.adapters.pop(name) for name in stale]
        self._changed()
        notify = self._callbacks['on_connection_change']
        try:
            for adapter in closing:
                await adapter.close()
        finally:
            opened = {name: self._open(name, open) for name, open in openers.items() if open is not None}
            results = await asyncio.gather(*(adapter.start() for adapter in opened.values()), return_exceptions=True)
            await asyncio.gather(*(adapter.close() for adapter, result in zip(opened.values(), results)
                                   if isinstance(result, BaseException)))
            # Only started members join; one that failed is opened again by the next save or connect.
            self.adapters.update({name: adapter for (name, adapter), result in zip(opened.items(), results)
                                  if not isinstance(result, BaseException)})
            self._changed()
            if notify is not None:
                notify()
        failed = [(name, result) for name, result in zip(opened, results) if isinstance(result, BaseException)]
        if failed:
            for _, result in failed:
                if not isinstance(result, Exception):
                    raise result
            raise PlatformCallError('；'.join(f'{name}: {error}' for name, error in failed), submitted=False)

    def _deliver(self, adapter: PlatformAdapter, raw: dict) -> None:
        self._delivering = adapter
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

    async def wait_connected(self, timeout_seconds: float | None, *, scene: str | None = None) -> None:
        """Follow replacement adapters until this scene, or any platform, connects."""
        async with asyncio.timeout(timeout_seconds):
            while True:
                members = list(self.adapters.values()) if scene is None else [self.member(scene)]
                members = [adapter for adapter in members if adapter is not None]
                if any(adapter.connected for adapter in members):
                    return
                changed = asyncio.create_task(self._members_changed.wait())
                waits = [asyncio.create_task(adapter.wait_connected(None)) for adapter in members]
                try:
                    pending = set(waits) | {changed}
                    while pending:
                        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                        if changed in done:
                            break
                        if any(task.exception() is None for task in done):
                            return
                        if pending == {changed} and not self._applying:
                            raise waits[0].exception()
                finally:
                    for task in [*waits, changed]:
                        task.cancel()
                    await asyncio.gather(*waits, changed, return_exceptions=True)

    async def wait_terminated(self) -> None:
        while True:
            change = self._members_changed
            if not self.adapters or self._applying:
                # Disconnected from the panel: the group lasts until members are added again.
                await change.wait()
                continue
            ended = asyncio.ensure_future(asyncio.gather(*(adapter.wait_terminated() for adapter in self.adapters.values())))
            changed = asyncio.ensure_future(change.wait())
            try:
                done, _ = await asyncio.wait({ended, changed}, return_when=asyncio.FIRST_COMPLETED)
                if changed not in done:
                    return await ended
            finally:
                ended.cancel()
                changed.cancel()
                await asyncio.gather(ended, changed, return_exceptions=True)

    def parse(self, raw: dict) -> ChatMessage | Notice | None:
        if self._delivering is not None:
            return self._delivering.parse(raw)
        if len(self.adapters) == 1:
            return next(iter(self.adapters.values())).parse(raw)
        raise ValueError('a grouped platform parses only the event its adapter is delivering')

    def _single(self, what: str) -> PlatformAdapter:
        if len(self.adapters) != 1:
            raise PlatformCallError(f'{what} needs the adapter of one platform', submitted=False)
        return next(iter(self.adapters.values()))

    async def identify(self) -> str:
        return await self._single('identify').identify()

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
        return await self._single(f'platform action {action!r}').call(action, params)

    async def download(self, data: dict, max_bytes: int) -> bytes:
        return await self._single('a download').download(data, max_bytes)


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


def platform_openers(config: SharedConfig, names) -> dict[str, Callable[..., PlatformAdapter]]:
    return {name: (lambda name=name, **member: OPENERS[name](config, **member)) for name in names}


def platform_changes(running: SharedConfig, saved: SharedConfig) -> dict[str, Callable[..., PlatformAdapter] | None] | None:
    """What ``PlatformGroup.apply`` takes to move from the running platforms to the saved ones; None when nothing changed.

    A platform kept unchanged maps to None; OneBot also reopens when the bot account changes.
    """
    changed = {name for name in set(running.platform_names) | set(saved.platform_names)
               if getattr(running, name) != getattr(saved, name)
               or name == 'onebot' and running.bot_id != saved.bot_id}
    if not changed:
        return None
    openers = platform_openers(saved, [name for name in saved.platform_names if name in changed])
    return {**{name: None for name in saved.platform_names if name not in changed}, **openers}


def open_platform(config: SharedConfig, *, on_event: Callable[[dict], None], on_error: Callable[[str], None],
                  on_connection_change: Callable[[], None] | None = None) -> PlatformGroup | None:
    """The configured platforms as one group, or None for stdin and panel-only hosts."""
    names = config.platform_names
    if not names:
        return None
    return PlatformGroup(platform_openers(config, names), on_event=on_event, on_error=on_error,
                         on_connection_change=on_connection_change)
