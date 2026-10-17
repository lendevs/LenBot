"""Run one plugin package in its own process and speak JSON lines with the host.

``describe <directory> <name>`` prints the plugin's entry points and exits. ``run`` reads an
init line, imports the plugin and serves invocations; every ``PluginContext`` capability is a
request back to the host, which applies the same scene and permission checks as in-process.
A crash here ends this process only.
"""

import asyncio
import base64
import importlib.util
import inspect
import itertools
import json
import os
from pathlib import Path
import re
import sys
import threading

from ...plugin import MARK, Invocation, Plugin, PluginContext
from .codec import (error_value, message_from, notice_from, part_value, raise_error, sent_from)

SUPPORTED = {"command", "fullmatch", "regex", "notice", "background"}


def plugin_class(directory: Path, name: str) -> type[Plugin]:
    module_name = f"lenbot_plugin_{name}"
    spec = importlib.util.spec_from_file_location(module_name, directory / "__init__.py",
                                                  submodule_search_locations=[str(directory)])
    if spec is None or spec.loader is None:
        raise ValueError(f"{directory} 缺少可导入的 __init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    classes = [value for value in vars(module).values()
               if isinstance(value, type) and issubclass(value, Plugin) and value is not Plugin
               and (value.__module__ == module_name or value.__module__.startswith(module_name + "."))]
    if len(classes) != 1:
        raise ValueError(f"插件模块必须恰好定义一个 Plugin 子类，实际 {len(classes)} 个")
    return classes[0]


def describe(cls: type[Plugin]) -> list[dict]:
    entries = []
    for attribute in dir(cls):
        mark = getattr(getattr(cls, attribute), MARK, None)
        if mark is None:
            continue
        if mark[0] not in SUPPORTED:
            raise ValueError(f"进程隔离的插件暂不支持 {mark[0]} 入口（{attribute}）；请改用 isolation = \"inline\"")
        if not inspect.iscoroutinefunction(getattr(cls, attribute)):
            raise ValueError(f"{attribute} 必须是 async 函数")
        if mark[0] == "regex":
            mark = ("regex", mark[1].pattern, mark[2], mark[3])
        entries.append({"attribute": attribute, "mark": list(mark)})
    return entries


class Channel:
    """Protocol output on a private copy of stdout; plugin prints go to stderr instead."""

    def __init__(self):
        self.output = os.fdopen(os.dup(1), "w", encoding="utf-8")
        os.dup2(2, 1)
        sys.stdout = sys.stderr
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self.waiting: dict[int, tuple[threading.Event | asyncio.Future, list]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def write(self, value: dict) -> None:
        line = json.dumps(value, ensure_ascii=False)
        with self.lock:
            self.output.write(line + "\n")
            self.output.flush()

    def call_sync(self, method: str, *args):
        number = next(self.ids)
        event, box = threading.Event(), []
        self.waiting[number] = (event, box)
        self.write({"type": "call", "id": number, "method": method, "args": list(args)})
        event.wait()
        return self._value(box[0])

    async def call(self, method: str, *args):
        number = next(self.ids)
        future = self.loop.create_future()
        self.waiting[number] = (future, [])
        self.write({"type": "call", "id": number, "method": method, "args": list(args)})
        return self._value(await future)

    @staticmethod
    def _value(reply: dict):
        if "error" in reply:
            raise_error(reply["error"])
        return reply.get("value")

    def answered(self, reply: dict) -> None:
        waiter, box = self.waiting.pop(reply["id"])
        if isinstance(waiter, threading.Event):
            box.append(reply)
            waiter.set()
        else:
            self.loop.call_soon_threadsafe(lambda: waiter.done() or waiter.set_result(reply))


class RemoteHost:
    """HostPort over the channel; the host ignores the plugin name and uses its own record."""

    def __init__(self, channel: Channel, bot_id: str):
        self.channel = channel
        self._bot_id = bot_id

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def now(self) -> float:
        return self.channel.call_sync("now")

    def scene_timezone(self, scene):
        return self.channel.call_sync("scene_timezone", scene)

    def scene_paused(self, scene):
        return self.channel.call_sync("scene_paused", scene)

    def require_owner(self, scene, requester_id):
        self.channel.call_sync("require_owner", scene, requester_id)

    def redact(self, plugin, text):
        return self.channel.call_sync("redact", text)

    def report_error(self, plugin, where, error):
        return self.channel.call_sync("report_error", where, f"{type(error).__name__}: {error}")

    def recent_messages(self, plugin, scene, limit):
        return [message_from(item) for item in self.channel.call_sync("recent_messages", scene, limit)]

    def messages_between(self, plugin, scene, after, before, offset, limit):
        return [message_from(item) for item in
                self.channel.call_sync("messages_between", scene, after, before, offset, limit)]

    def emit_event(self, plugin, scene, text):
        self.channel.call_sync("emit_event", scene, text)

    async def fetch_image(self, plugin, url, timeout_seconds):
        return base64.b64decode(await self.channel.call("fetch_image", url, timeout_seconds))

    async def send_text(self, plugin, scene, text, reply_to):
        return sent_from(await self.channel.call("send_text", scene, text, reply_to))

    async def send_parts(self, plugin, scene, parts, reply_to):
        return sent_from(await self.channel.call("send_parts", scene, [part_value(part) for part in parts], reply_to))

    async def get_kv(self, plugin, key, default):
        return await self.channel.call("get_kv", key, default)

    async def set_kv(self, plugin, key, value):
        await self.channel.call("set_kv", key, value)

    async def delete_kv(self, plugin, key):
        return await self.channel.call("delete_kv", key)

    async def memory(self, plugin, scene, arguments):
        return await self.channel.call("memory", scene, arguments)

    async def generate(self, plugin, scene, prompt, role, system):
        return await self.channel.call("generate", scene, prompt, role, system)

    async def delegate(self, plugin, scene, requester, goal, deliverable, context, materials):
        return await self.channel.call("delegate", scene, requester, goal, deliverable, context, list(materials))

    def cron(self, *args, **kwargs):
        raise RuntimeError("进程隔离的插件暂不支持定点任务")

    def start_task(self, plugin, name, coroutine):
        coroutine.close()
        raise RuntimeError("进程隔离的插件暂不支持自建后台任务，请使用 @background")


async def serve(channel: Channel, init: dict) -> None:
    channel.loop = asyncio.get_running_loop()
    cls = plugin_class(Path(init["directory"]), init["name"])
    context = PluginContext(name=init["name"], config=init["config"], data_dir=Path(init["data_dir"]),
                            enabled_scenes=tuple(init["scenes"]), host=RemoteHost(channel, init["bot_id"]))
    instance = cls(context)
    patterns = {entry["attribute"]: re.compile(entry["mark"][1]) for entry in describe(cls)
                if entry["mark"][0] == "regex"}
    finished = asyncio.Event()
    tasks: set[asyncio.Task] = set()

    async def run(request: dict) -> None:
        try:
            kind = request["type"]
            if kind == "start":
                value = await instance.start()
            elif kind == "stop":
                value = await instance.stop()
            elif kind == "migrate":
                value = await instance.migrate_data(request["from_version"])
            else:
                attribute, arguments = request["attribute"], list(request["args"])
                if request["scene"] is None:
                    target = context
                else:
                    target = Invocation(context, request["scene"], message_from(request["message"]))
                if attribute in patterns:
                    arguments = [patterns[attribute].fullmatch(arguments[0])]
                if request.get("notice") is not None:
                    arguments = [notice_from(request["notice"])]
                value = await getattr(instance, attribute)(target, *arguments)
            channel.write({"type": "result", "id": request["id"], "value": value})
        except Exception as error:
            channel.write({"type": "result", "id": request["id"], "error": error_value(error)})
        finally:
            if request["type"] == "stop":
                finished.set()

    def receive(request: dict) -> None:
        task = asyncio.create_task(run(request))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def read() -> None:
        for line in sys.stdin:
            message = json.loads(line)
            if message["type"] == "reply":
                channel.answered(message)
            else:
                channel.loop.call_soon_threadsafe(receive, message)
        channel.loop.call_soon_threadsafe(finished.set)

    channel.write({"type": "ready"})
    threading.Thread(target=read, daemon=True).start()
    await finished.wait()


def main() -> None:
    if sys.argv[1] == "describe":
        try:
            print(json.dumps({"entries": describe(plugin_class(Path(sys.argv[2]), sys.argv[3]))}, ensure_ascii=False))
        except Exception as error:
            print(json.dumps({"error": error_value(error)}, ensure_ascii=False))
        return
    channel = Channel()
    init = json.loads(sys.stdin.readline())
    try:
        asyncio.run(serve(channel, init))
    except Exception as error:
        channel.write({"type": "failed", "error": error_value(error)})
        raise


if __name__ == "__main__":
    main()
