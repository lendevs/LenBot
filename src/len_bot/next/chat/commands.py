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
import math
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from string import Template
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from ...plugin import Text
from ..models.failover import HEALTH, ProviderHealth
from ..models.limits import speech_quota
from ..platform.messages import ChatMessage
from ..prompt_files import read_prompt
from ..runtime.logs import log_context, log_event
from ..runtime.identity import roles_for

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


def allowed(level: Level, runtime: NetworkRuntime, runner: SceneRunner, message: ChatMessage) -> bool:
    """The scene_control and host_manage checks, with the group role this message carries.

    The message is checked before it is stored, so its own sender role counts, not only an older one.
    """
    config, requester = runner.config, message.sender.uid
    if requester == config.bot_id or requester in config.permissions.blacklist:
        return False
    if level == "member":
        return True
    if level == "manage":
        from ..runtime.management import require_management
        try:
            require_management(runtime.config, config.scene, requester)
        except PermissionError:
            return False
        return True
    group = config.scene.split(":", 2)[1] == "group"
    role = (message.sender.role or runner.store.latest_sender_role(config.scene, requester)) if group else None
    identities = roles_for(requester, owners=config.owners, scoped_owner=None, admins=config.permissions.admins,
                           whitelist=config.permissions.whitelist, group_role=role)
    return bool(identities.intersection(config.chat_control_roles))


async def _help(call: CommandCall) -> str:
    lines = ["可用的宿主命令："]
    for command in call.runtime.commands.available(call.runtime, call.runner, call.message):
        lines.append(f"{command.usage} — {command.summary}")
    lines.append("其他消息照常交给我。")
    return "\n".join(lines)


async def _id(call: CommandCall) -> str:
    return f"场景：{call.scene}\n你的账号：{call.requester}\n机器人账号：{call.runner.config.bot_id}"


# A command that changes the scene waits this long for the running turn, so the turn cannot overwrite it.
EXECUTION_WAIT_SECONDS = 30
MAX_QUIET_MINUTES = 7 * 24 * 60


def _clock(call: CommandCall, timestamp: float) -> str:
    moment = datetime.fromtimestamp(timestamp, ZoneInfo(call.runner.config.timezone))
    today = datetime.fromtimestamp(call.runner.store.now(), ZoneInfo(call.runner.config.timezone)).date()
    return moment.strftime("%H:%M" if moment.date() == today else "%m-%d %H:%M")


@asynccontextmanager
async def _between_turns(call: CommandCall):
    """Hold the scene between turns, as the panel does, so a turn ending later keeps the change."""
    if not call.runtime.accepting:
        raise CommandError("宿主正在停止，没有改变")
    try:
        async with asyncio.timeout(EXECUTION_WAIT_SECONDS):
            await call.runner.execution.acquire()
    except TimeoutError:
        raise CommandError("我正在处理上一轮，稍后再试；这次没有改变") from None
    try:
        yield
    finally:
        call.runner.execution.release()


def _chat_line(call: CommandCall) -> str:
    runner, now = call.runner, call.runner.store.now()
    if runner.state.paused:
        return "聊天：已关闭（消息照常记录，/chat on 打开）"
    period = runner.quiet_period(now)
    if period is None or not period[0] <= now < period[1]:
        return "聊天：开启"
    direct = "被叫到时仍回应" if runner.quiet_direct(now) == "allow" else "被叫到也延后"
    return f"聊天：安静到 {_clock(call, period[1])}，{direct}"


def _speech_line(call: CommandCall) -> str:
    quota = speech_quota(call.runner.store, call.runner.config)
    if quota.source == "private":
        return "发言上限：私聊不限"
    if quota.limit is None:
        return f"发言上限：不限（最近一小时 {quota.used} 条）"
    source = "本群单独设置" if quota.source == "scene" else "全局设置"
    return (f"发言：最近一小时 {quota.used}/{quota.limit} 条（{source}），"
            f"被叫到时另有余量 {quota.reserve_left}/{quota.reserve} 条")


def _mind_health(call: CommandCall) -> dict | None:
    """The mind's circuits in the host's provider health, for the configured candidates only.

    None unless the mind lists fallbacks. Rows and the last served model that do not belong to the
    running configuration (another model opened under the same role) are left out.
    """
    candidates = [(item.provider, item.model) for item in call.runtime.config.models.roles.mind.candidates()]
    state = call.runtime.commands.health.state()["roles"].get("mind")
    if len(candidates) < 2 or state is None:
        return None
    served = state["last_served"]
    return {"candidates": [row for row in state["candidates"] if (row["provider"], row["model"]) in candidates],
            "last_served": served if served is not None and (served["provider"], served["model"]) in candidates
            else None}


def _model_line(call: CommandCall) -> str:
    candidates = call.runtime.config.models.roles.mind.candidates()
    text = f"主脑模型：{candidates[0].provider} / {candidates[0].model}"
    if len(candidates) > 1:
        health = _mind_health(call)
        served = None if health is None else health["last_served"]
        text += f"（另有 {len(candidates) - 1} 个备用"
        if served is not None and served["priority"] > 0:
            text += f"，最近一次由备用 {served['provider']} / {served['model']} 回复"
        text += "）"
    return text


async def _status(call: CommandCall) -> str:
    lines = [f"场景：{call.scene}", _chat_line(call), _speech_line(call), _model_line(call)]
    if call.runtime.held(call.scene):
        lines.append("发送：已暂停，消息只记录不发出")
    return "\n".join(lines)


async def _chat(call: CommandCall) -> str:
    if call.arguments not in (["on"], ["off"]):
        raise CommandError("用法：/chat on 或 /chat off")
    enabled = call.arguments == ["on"]
    async with _between_turns(call):
        before = call.runner.state.paused
        call.runner.set_paused(not enabled)
    log_event(logger, "command_chat", scene=call.scene, enabled=enabled, requester=call.requester)
    if before != enabled:
        return "本群聊天本来就是开启的" if enabled else "本群聊天本来就是关闭的"
    return ("已打开本群聊天；关闭期间的消息只作为背景，不逐条回复" if enabled
            else "已关闭本群聊天；消息照常记录，/chat on 重新打开")


async def _quiet(call: CommandCall) -> str:
    arguments = call.arguments
    if not 1 <= len(arguments) <= 2 or not arguments[0].isdecimal() or arguments[1:] not in ([], ["defer"]):
        raise CommandError(f"用法：/quiet <分钟> [defer]，分钟为 1 到 {MAX_QUIET_MINUTES}")
    minutes = int(arguments[0])
    if not 1 <= minutes <= MAX_QUIET_MINUTES:
        raise CommandError(f"安静时长为 1 到 {MAX_QUIET_MINUTES} 分钟")
    direct = "defer" if arguments[1:] else "allow"
    async with _between_turns(call):
        state = call.runner.set_temporary_quiet(minutes * 60, direct, call.requester)
    return (f"本群安静到 {_clock(call, state['temporary_quiet']['until'])}；"
            + ("被叫到也延后，/resume 提前恢复" if direct == "defer" else "被@或回复时仍会回应，/resume 提前恢复"))


async def _resume(call: CommandCall) -> str:
    async with _between_turns(call):
        before = call.runner.state.temporary_quiet
        call.runner.set_temporary_quiet(None, "allow", call.requester)
    text = "已结束临时安静" if before is not None and before.until > call.runner.store.now() else "本群没有临时安静"
    configured = call.runner.quiet_period(call.runner.store.now())
    if not call.runner.state.paused and configured is not None and configured[0] <= call.runner.store.now() < configured[1]:
        text += f"；根配置的安静时段到 {_clock(call, configured[1])} 结束"
    return text


async def _reset(call: CommandCall) -> str:
    if call.arguments:
        raise CommandError("用法：/reset")
    store, scene = call.runner.store, call.scene
    async with _between_turns(call):
        if store.db.execute("SELECT 1 FROM turns WHERE scene=? AND ended IS NULL LIMIT 1", (scene,)).fetchone():
            raise CommandError("本群还有没结束或等待恢复的一轮，没有重置")
        through = store.new_context(scene)
        call.runner.chat.toolset.discovered_tools = set()
    log_event(logger, "command_reset", scene=scene, compact_through=through, requester=call.requester)
    call.runtime.notify()
    return "已开始新的对话上下文；聊天记录、记忆和未读消息都保留"


STATE_TITLES = {"closed": "正常", "open": "熔断冷却中", "half_open": "冷却结束待试"}


async def _model(call: CommandCall) -> str:
    """The mind's binding and its fallbacks with each circuit; switching is a configuration change."""
    if call.arguments:
        raise CommandError("用法：/model。调整顺序或备用服务请在面板的模型页修改")
    candidates = call.runtime.config.models.roles.mind.candidates()
    health = _mind_health(call)
    rows = {(row["provider"], row["model"]): row for row in ([] if health is None else health["candidates"])}
    lines = ["主脑服务（按顺序尝试）：" if len(candidates) > 1 else "主脑服务："]
    for index, candidate in enumerate(candidates, 1):
        row = rows.get((candidate.provider, candidate.model))
        state = "" if row is None else f"，{STATE_TITLES[row['state']]}"
        if row is not None and row["state"] == "open" and row["reopens_in_seconds"] is not None:
            state += f"，{math.ceil(row['reopens_in_seconds'])} 秒后再试"
        lines.append(f"{index}. {candidate.provider} / {candidate.model}{state}")
    served = None if health is None else health["last_served"]
    if served is not None:
        lines.append(f"最近一次由 {served['provider']} / {served['model']} 回复")
    if len(candidates) == 1:
        lines.append("没有配置备用服务；出错时不会切换")
    return "\n".join(lines)


async def _limit(call: CommandCall) -> str:
    from ..configuration.editing import save_config
    from ..models.limits import apply_speech_limits, clear_speech

    scene, runtime = call.scene, call.runtime
    if scene.split(":", 2)[1] != "group":
        raise CommandError("发言上限只用于群聊")
    arguments = call.arguments
    if arguments == []:
        return _speech_line(call)
    if arguments == ["reset"]:
        clear_speech(call.runner.store, scene)
        call.runner.changed.set()
        log_event(logger, "command_limit", scene=scene, change="reset", requester=call.requester)
        return "已清空本群最近一小时的发言计数"
    if len(arguments) != 1 or not (arguments[0] in ("off", "global") or arguments[0].isdecimal()):
        raise CommandError("用法：/limit、/limit <每小时条数>、/limit off、/limit global 或 /limit reset")
    change = arguments[0]
    if change.isdecimal() and not 1 <= int(change) <= 1000:
        raise CommandError("每小时条数为 1 到 1000")

    def edit(source: dict, saved) -> None:
        per_scene = source.setdefault("limits", {}).setdefault("scene_messages_per_hour", {})
        if change == "global":
            per_scene.pop(scene, None)
        else:
            per_scene[scene] = None if change == "off" else int(change)

    async with runtime.config_write_lock:
        saved = await asyncio.to_thread(save_config, runtime.config._instance_root, runtime.config, edit)
        apply_speech_limits(runtime.config, saved)
        for runner in runtime.runners.values():
            runner.changed.set()
    log_event(logger, "command_limit", scene=scene, change=change, requester=call.requester)
    runtime.notify()
    return "已保存到根配置并立即生效。" + _speech_line(call)


BUILTIN: list[Command] = [
    Command("help", "/help", "列出你可以使用的命令", "member", _help),
    Command("id", "/id", "显示本场景、你和机器人的账号，用于填写权限", "member", _id),
    Command("status", "/status", "查看本群聊天开关、安静、发言余量和主脑模型", "control", _status),
    Command("chat", "/chat on|off", "打开或关闭本群聊天，关闭时消息照常记录", "control", _chat),
    Command("quiet", "/quiet <分钟> [defer]", "本群临时安静；defer 时被叫到也延后", "control", _quiet),
    Command("resume", "/resume", "提前结束本群的临时安静", "control", _resume),
    Command("reset", "/reset", "开始新的对话上下文，原记录和记忆保留", "control", _reset),
    Command("model", "/model", "查看主脑服务、备用服务和熔断状态", "manage", _model),
    Command("limit", "/limit [<条数>|off|global|reset]", "查看或修改本群每小时发言上限", "manage", _limit),
]


class Commands:
    """The scene command layer of one runtime."""

    def __init__(self, commands: list[Command] | None = None, *, health: ProviderHealth = HEALTH):
        # The provider health the host's role models report to (the same instance the panel reads).
        self.health = health
        self.table = {command.name: command for command in (BUILTIN if commands is None else commands)}
        self.tasks: set[asyncio.Task] = set()

    def enabled(self, runtime: NetworkRuntime) -> list[Command]:
        settings = runtime.config.commands
        if not settings.enabled:
            return []
        return [command for name, command in self.table.items() if name not in settings.disabled]

    def available(self, runtime: NetworkRuntime, runner: SceneRunner, message: ChatMessage) -> list[Command]:
        return [command for command in self.enabled(runtime) if allowed(command.level, runtime, runner, message)]

    def match(self, runtime: NetworkRuntime, runner: SceneRunner, message: ChatMessage) -> CommandCall | None:
        if message.is_self or message.sender.uid in runner.settings.other_bot_ids:
            return None
        text = command_text(message, runner.config.bot_id)
        parsed = None if text is None else parse(text)
        if parsed is None:
            return None
        name, arguments = parsed
        command = next((item for item in self.enabled(runtime) if item.name == name), None)
        if command is None or not allowed(command.level, runtime, runner, message):
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
