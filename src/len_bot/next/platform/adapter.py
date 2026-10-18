"""The chat platform behind the runtime: one adapter per configured platform.

The runtime only uses this interface. An adapter owns its transport (WebSocket, HTTP polling ...),
turns each inbound event into a raw dict for ``on_event`` and parses it back with ``parse``; the
runtime stores the raw dict next to the parsed message. Scenes are ``<platform>:group:<id>`` or
``<platform>:private:<id>``, accounts ``<platform>:<id>``, with ``name`` as the platform prefix.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
        """A platform-specific action (OneBot action, Telegram Bot API method) with its raw answer."""


def open_platform(config: SharedConfig, *, on_event: Callable[[dict], None], on_error: Callable[[str], None],
                  on_connection_change: Callable[[], None] | None = None,
                  wait_for_events: Callable[[], Awaitable[None]] | None = None) -> PlatformAdapter | None:
    """The adapter of the configured platform, or None for stdin and panel-only hosts."""
    if config.onebot is not None:
        from .onebot import OneBot
        return OneBot(config.onebot, bot_id=config.bot_id, on_event=on_event, on_error=on_error,
                      on_connection_change=on_connection_change)
    if config.telegram is not None:
        from .telegram import Telegram
        return Telegram(config.telegram, bot_id=config.bot_id, on_event=on_event, on_error=on_error,
                        on_connection_change=on_connection_change, wait_for_events=wait_for_events)
    return None
