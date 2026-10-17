"""Host commands typed in a scene: fixed answers from the host, never a turn of the mind.

A message whose text is ``/<name> [arguments]`` (after an optional reply or a mention of the bot)
is a host command when ``name`` is a built-in command, the command is not turned off in
``commands``, no plugin claimed the same message, and the sender holds the command's level:

- ``member``: anyone the scene does not blacklist;
- ``control``: the scene's ``chat_control_roles`` (the same check as the scene_control tool);
- ``manage``: the bot's owners and global admins (the same check as host_manage).

A sender without the level, or an unknown name, is not answered by the host: the message reaches the
conversation like any other, so an ordinary member typing ``/reset`` is not refused in public.
The command message is stored with a note that the host handled it, does not wake the mind, and the
reply goes through the scene outlet like a plugin reply (send hold and simulation included, no speech count).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from string import Template
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from ...plugin import Text
from ..platform.messages import ChatMessage
from ..prompt_files import read_prompt
from ..runtime.logs import log_context, log_event
from .scene_control import require_control

if TYPE_CHECKING:
    from ..runtime.network import NetworkRuntime
    from .attention import SceneRunner

logger = logging.getLogger(__name__)

Level = Literal["member", "control", "manage"]
LEVEL_TITLES = {"member": "所有人", "control": "本群聊天管理", "manage": "机器人主人和全局管理员"}


class CommandError(ValueError):
    """A command refused with a reason for the sender; the text is the reply."""


@dataclass(frozen=True)
class Command:
    name: str
    usage: str
    summary: str
    level: Level
    run: Callable[[CommandCall], Awaitable[str]]


@dataclass(frozen=True)
class CommandCall:
    command: Command
    arguments: list[str]
    message: ChatMessage
    runner: SceneRunner
    runtime: NetworkRuntime

    @property
    def scene(self) -> str:
        return self.message.scene

    @property
    def requester(self) -> str:
        return self.message.sender.uid


def command_text(message: ChatMessage, bot_id: str) -> str | None:
    """The text of a message that starts with ``/``, or None; a reply or a mention of the bot may precede it."""
    pieces, started = [], False
    for segment in message.segments:
        if segment.type == "text":
            pieces.append(segment.data["text"])
            started = started or bool(segment.data["text"].strip())
        elif not started and (segment.type == "reply" or
                              (segment.type == "mention" and str(segment.data["user"]) == bot_id)):
            continue
        else:
            return None
    text = "".join(pieces).strip()
    return text if text.startswith("/") else None


def parse(text: str) -> tuple[str, list[str]] | None:
    match = re.fullmatch(r"/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?", text, re.DOTALL)
    if match is None:
        return None
    return match[1].lower(), (match[2] or "").split()


def allowed(level: Level, runtime: NetworkRuntime, runner: SceneRunner, requester: str) -> bool:
    config = runner.config
    if requester == config.bot_id or requester in config.permissions.blacklist:
        return False
    if level == "member":
        return True
    if level == "manage":
        from ..runtime.management import require_management
        check = lambda: require_management(runtime.config, config.scene, requester)  # noqa: E731
    else:
        check = lambda: require_control(runner.store, config, requester)  # noqa: E731
    try:
        check()
    except PermissionError:
        return False
    return True


async def _help(call: CommandCall) -> str:
    lines = ["可用的宿主命令："]
    for command in call.runtime.commands.available(call.runtime, call.runner, call.requester):
        lines.append(f"{command.usage} — {command.summary}")
    lines.append("其他消息照常交给我。")
    return "\n".join(lines)


async def _id(call: CommandCall) -> str:
    return f"场景：{call.scene}\n你的账号：{call.requester}\n机器人账号：{call.runner.config.bot_id}"


BUILTIN: list[Command] = [
    Command("help", "/help", "列出你可以使用的命令", "member", _help),
    Command("id", "/id", "显示本场景、你和机器人的账号，用于填写权限", "member", _id),
]


class Commands:
    """The scene command layer of one runtime."""

    def __init__(self, commands: list[Command] | None = None):
        self.table = {command.name: command for command in (BUILTIN if commands is None else commands)}
        self.tasks: set[asyncio.Task] = set()

    def enabled(self, runtime: NetworkRuntime) -> list[Command]:
        settings = runtime.config.commands
        if not settings.enabled:
            return []
        return [command for name, command in self.table.items() if name not in settings.disabled]

    def available(self, runtime: NetworkRuntime, runner: SceneRunner, requester: str) -> list[Command]:
        return [command for command in self.enabled(runtime) if allowed(command.level, runtime, runner, requester)]

    def match(self, runtime: NetworkRuntime, runner: SceneRunner, message: ChatMessage) -> CommandCall | None:
        if message.is_self or message.sender.uid in runner.settings.other_bot_ids:
            return None
        text = command_text(message, runner.config.bot_id)
        parsed = None if text is None else parse(text)
        if parsed is None:
            return None
        name, arguments = parsed
        command = next((item for item in self.enabled(runtime) if item.name == name), None)
        if command is None or not allowed(command.level, runtime, runner, message.sender.uid):
            return None
        return CommandCall(command, arguments, message, runner, runtime)

    def report(self, call: CommandCall) -> str:
        now = datetime.fromtimestamp(call.runner.store.now(), ZoneInfo(call.runner.config.timezone))
        return Template(read_prompt("next_command_handled.md")).substitute(
            command="/" + call.command.name, time=now.isoformat(timespec="seconds"),
            sender_id=call.requester, message_id=call.message.platform_message_id).strip()

    async def execute(self, call: CommandCall) -> str:
        """Run the command and return the reply text; a refusal or failure is the reply too."""
        try:
            reply = await call.command.run(call)
        except CommandError as error:
            reply = str(error)
        except Exception as error:
            log_event(logger, "command_failed", level=logging.ERROR, command=call.command.name, error=error)
            reply = f"命令 /{call.command.name} 执行失败：{type(error).__name__}: {error}"
        else:
            log_event(logger, "command", command=call.command.name, requester=call.requester)
        return reply

    def dispatch(self, call: CommandCall) -> None:
        async def run() -> None:
            reply = await self.execute(call)
            chat = call.runtime.chats[call.scene]
            await chat.expression.send_plugin_content("/" + call.command.name, [Text(reply)],
                                                      reply_to=call.message.platform_message_id,
                                                      reply_prompt="next_command_reply.md")

        with log_context(scene=call.scene, platform_message_id=call.message.platform_message_id):
            task = asyncio.create_task(run(), name=f"command:{call.command.name}")
        self.tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log_event(logger, "command_reply_failed", level=logging.ERROR, error=task.exception())
