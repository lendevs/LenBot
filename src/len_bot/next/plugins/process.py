"""Host side of out-of-process plugins: describe, proxy and answer capability calls.

The proxy class carries the same entry-point marks as the real plugin, so the host registers
commands, rules, notices and background loops exactly as for an in-process plugin. Every call
goes to a worker process; if that process dies, pending calls fail and the plugin is marked
failed while the host and other plugins keep running. Reload starts a fresh worker.

Identity stays on this side: an invocation triggered by a real message gets an unguessable token
for its duration, and a capability that acts for a person (``delegate``) takes the requester from
the message behind the token, never from the worker.
"""

import asyncio
import base64
from dataclasses import asdict
import itertools
import json
import logging
from pathlib import Path
import re
import secrets
import subprocess
import sys

from ...plugin import MARK, CompactRequest, Invocation, Plugin, PluginContext, RecallRequest
from ..platform.messages import ChatMessage, Notice
from ..runtime.logs import log_event
from .codec import (blocks_from, error_value, message_value, notice_value, part_from, raise_error, recall_value,
                    sent_value)

logger = logging.getLogger(__name__)
DESCRIBE_SECONDS = 60
STOP_SECONDS = 10
WORKER = [sys.executable, "-m", "len_bot.next.plugins.worker"]


def describe(directory: Path, name: str) -> list[dict]:
    try:
        done = subprocess.run([*WORKER, "describe", str(directory), name], capture_output=True, text=True,
                              timeout=DESCRIBE_SECONDS, check=False)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"插件 {name} 的进程在 {DESCRIBE_SECONDS} 秒内未完成导入") from error
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        raise RuntimeError(f"插件 {name} 的进程导入失败（退出码 {done.returncode}）：{done.stderr.strip()[-2000:]}")
    result = json.loads(lines[-1])
    if "error" in result:
        raise_error(result["error"])
    return result["entries"]


def proxy_class(directory: Path, name: str, entries: list[dict] | None = None) -> type[Plugin]:
    """A Plugin subclass whose marked methods forward to the worker process.

    ``entries`` is a ``describe`` result taken off the event loop; None runs ``describe`` here.
    """
    namespace: dict = {"directory": directory}
    for entry in describe(directory, name) if entries is None else entries:
        mark = tuple(entry["mark"])
        if mark[0] == "regex":
            mark = ("regex", re.compile(mark[1]), mark[2], mark[3])
        namespace[entry["attribute"]] = _forwarder(entry["attribute"], mark)
    return type(f"Process_{name}", (ProcessPlugin,), namespace)


def _forwarder(attribute: str, mark: tuple):
    async def forward(self, target, *arguments):
        if isinstance(target, RecallRequest):
            return blocks_from(await self.worker.request({"type": "recall", "attribute": attribute,
                                                          "request": recall_value(target)}))
        if isinstance(target, CompactRequest):
            return await self.worker.request({"type": "compact", "attribute": attribute, "request": asdict(target)})
        if isinstance(target, Invocation):
            scene, message = target.scene, message_value(target.message)
        else:
            scene, message = None, None
        notice = None
        if arguments and isinstance(arguments[0], Notice):
            notice, arguments = notice_value(arguments[0]), ()
        elif arguments and isinstance(arguments[0], re.Match):
            arguments = (arguments[0].string,)
        token = None
        if isinstance(target, Invocation) and target.message is not None and not target.message.is_self:
            token = secrets.token_hex(16)
            self.worker.invocations[token] = (target.scene, target.message)
        try:
            return await self.worker.request({"type": "invoke", "attribute": attribute, "scene": scene,
                                              "message": message, "args": list(arguments), "notice": notice,
                                              "invocation": token})
        finally:
            if token is not None:
                self.worker.invocations.pop(token, None)
    forward.__name__ = attribute
    setattr(forward, MARK, mark)
    return forward


def _line(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False) + "\n").encode()


class ProcessPlugin(Plugin):
    directory: Path

    def __init__(self, ctx: PluginContext) -> None:
        super().__init__(ctx)
        self.worker = Worker(self.directory, ctx)

    async def migrate_data(self, from_version: int) -> None:
        await self.worker.request({"type": "migrate", "from_version": from_version})

    async def start(self) -> None:
        await self.worker.request({"type": "start"})

    async def stop(self) -> None:
        await self.worker.close()


class Worker:
    def __init__(self, directory: Path, ctx: PluginContext):
        self.directory, self.ctx, self.host = directory, ctx, ctx.host
        self.process: asyncio.subprocess.Process | None = None
        self.reader: asyncio.Task | None = None
        self.ids = itertools.count(1)
        self.pending: dict[int, asyncio.Future] = {}
        self.calls: set[asyncio.Task] = set()
        # Running invocations triggered by a real message: token -> (scene, message).
        self.invocations: dict[str, tuple[str, ChatMessage]] = {}
        self.closing = False
        self.lock = asyncio.Lock()

    async def _ensure(self) -> asyncio.subprocess.Process:
        async with self.lock:
            if self.closing:
                raise RuntimeError(f"插件 {self.ctx.name} 的进程已停止")
            if self.process is not None:
                if self.process.returncode is not None:
                    raise RuntimeError(f"插件 {self.ctx.name} 的进程已退出，请在面板重载插件")
                return self.process
            self.process = await asyncio.create_subprocess_exec(
                *WORKER, "run", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                limit=64 * 1024 * 1024)
            self._write({"directory": str(self.directory), "name": self.ctx.name, "config": dict(self.ctx.config),
                         "data_dir": str(self.ctx.data_dir), "scenes": list(self.ctx.enabled_scenes),
                         "bot_id": self.ctx.bot_id})
            while True:
                line = await self.process.stdout.readline()
                first = json.loads(line) if line else {"type": "failed", "error": {"type": "RuntimeError",
                                                                                "message": "进程启动后立即退出"}}
                if first["type"] == "call":
                    await self._answer(first)
                    continue
                if first["type"] != "ready":
                    await self.process.wait()
                    raise_error(first["error"])
                break
            self.reader = asyncio.create_task(self._read(self.process), name=f"{self.ctx.name}:worker")
            log_event(logger, "plugin_process_started", plugin=self.ctx.name, pid=self.process.pid)
            return self.process

    def _write(self, value: dict) -> None:
        self.process.stdin.write(_line(value))

    async def request(self, value: dict):
        await self._ensure()
        number = next(self.ids)
        future = asyncio.get_running_loop().create_future()
        self.pending[number] = future
        self._write({**value, "id": number})
        try:
            reply = await future
        finally:
            self.pending.pop(number, None)
        if "error" in reply:
            raise_error(reply["error"])
        return reply.get("value")

    async def _read(self, process: asyncio.subprocess.Process) -> None:
        failure = None
        try:
            while line := await process.stdout.readline():
                message = json.loads(line)
                if message["type"] == "result":
                    future = self.pending.get(message["id"])
                    if future is not None and not future.done():
                        future.set_result(message)
                elif message["type"] == "call":
                    task = asyncio.create_task(self._answer(message))
                    self.calls.add(task)
                    task.add_done_callback(self.calls.discard)
                else:
                    raise ValueError(f"未知的消息类型：{line[:200]!r}")
        except Exception as error:
            # A broken or oversized line ends this worker: nothing after it can be matched to a call.
            failure = f"{type(error).__name__}: {str(error)[:500]}"
            if process.returncode is None:
                process.kill()
        code = await process.wait()
        text = (f"插件 {self.ctx.name} 的进程退出（退出码 {code}）" if failure is None
                else f"插件 {self.ctx.name} 的进程协议出错，已结束进程：{failure}")
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError(text + "，本次调用未完成"))
        if not self.closing:
            log_event(logger, "plugin_process_exited", text, level=logging.ERROR, plugin=self.ctx.name, code=code)
            self.host.worker_exited(self.ctx.name, text)

    async def _answer(self, message: dict) -> None:
        try:
            value = await self._call(message["method"], message["args"])
            line = _line({"type": "reply", "id": message["id"], "value": value})
        except Exception as error:
            line = _line({"type": "reply", "id": message["id"], "error": error_value(error)})
        if self.process is not None and self.process.returncode is None:
            try:
                self.process.stdin.write(line)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _scene(self, scene: str) -> str:
        if scene not in self.ctx.enabled_scenes:
            raise PermissionError(f"插件 {self.ctx.name} 未在场景 {scene} 启用")
        return scene

    async def _call(self, method: str, args: list):
        """Answer one capability call with this plugin's own name; the worker never chooses it."""
        host, name = self.host, self.ctx.name
        match method:
            case "now":
                return host.now()
            case "scene_timezone":
                return host.scene_timezone(self._scene(args[0]))
            case "scene_paused":
                return host.scene_paused(self._scene(args[0]))
            case "require_owner":
                return host.require_owner(self._scene(args[0]), args[1])
            case "redact":
                return host.redact(name, args[0])
            case "report_error":
                return host.report_error(name, args[0], RuntimeError(args[1]))
            case "recent_messages":
                return [message_value(item) for item in host.recent_messages(name, self._scene(args[0]), args[1])]
            case "messages_between":
                return [message_value(item) for item in
                        host.messages_between(name, self._scene(args[0]), *args[1:])]
            case "emit_event":
                return host.emit_event(name, self._scene(args[0]), args[1])
            case "fetch_image":
                return base64.b64encode(await host.fetch_image(name, args[0], args[1])).decode()
            case "send_text":
                return sent_value(await host.send_text(name, self._scene(args[0]), args[1], args[2]))
            case "send_parts":
                return sent_value(await host.send_parts(name, self._scene(args[0]),
                                                        [part_from(item) for item in args[1]], args[2]))
            case "get_kv":
                return await host.get_kv(name, args[0], args[1])
            case "set_kv":
                return await host.set_kv(name, args[0], args[1])
            case "delete_kv":
                return await host.delete_kv(name, args[0])
            case "memory":
                return await host.memory(name, self._scene(args[0]), args[1])
            case "native_memory":
                return await host.native_memory(name, self._scene(args[0]), args[1])
            case "report_memory_progress":
                return await host.report_memory_progress(name, self._scene(args[0]), args[1])
            case "generate":
                return await host.generate(name, self._scene(args[0]), *args[1:])
            case "delegate":
                scene, token = self._scene(args[0]), args[1]
                invocation = self.invocations.get(token) if isinstance(token, str) else None
                if invocation is None or invocation[0] != scene:
                    raise ValueError("插件委派需要真实触发消息；后台和无发送者的工具调用不能伪造请求人")
                return await host.delegate(name, scene, invocation[1].sender.uid, *args[2:])
        raise ValueError(f"插件进程请求了未知的宿主能力 {method}")

    async def close(self) -> None:
        async with self.lock:
            self.closing = True
            process = self.process
        if process is None or process.returncode is not None:
            return
        try:
            number = next(self.ids)
            future = asyncio.get_running_loop().create_future()
            self.pending[number] = future
            self._write({"type": "stop", "id": number})
            reply = await asyncio.wait_for(future, STOP_SECONDS)
            if "error" in reply:
                raise_error(reply["error"])
        finally:
            if process.returncode is None:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), STOP_SECONDS)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                except asyncio.CancelledError:
                    # Cancelled by the host's stop limit: never leave the worker behind.
                    process.kill()
                    raise
            if self.reader is not None:
                await self.reader
            for task in tuple(self.calls):
                task.cancel()
