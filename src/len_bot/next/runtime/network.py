"""Shared scene execution behind one chat platform adapter or explicit simulated stdin."""

from __future__ import annotations

import asyncio
from .signals import install_stop
from .events import EventHub
from .scenes import SceneService
from .settings import LiveSettings
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .scene_titles import SceneTitles
from ..chat.attention import SceneRunner
from ..media.audio import AudioService
from ..chat.session import Chat
from ..chat.commands import Commands
from ..chat.tools import task_data_tools, tool_catalog
from ..tools.skills import select_skills
from ..config import LabConfig, SharedConfig
from .logs import credentials, log_context, log_event
from .lifecycle import HostLifecycle
from ..platform.messages import ChatMessage, Notice, SendResult, UploadResult
from ..models.client import ChatModel
from ..models.slots import ModelSlots
from ..models.limits import ModelBudget
from .retention import Retention
from ..memory.service import MemoryService
from ..chat.upkeep import SessionUpkeep, UpkeepPart, runner_fork, upkeep_parts
from ..learning.sticker_collection import StickerCollector
from ..learning.expression_selection import ExpressionService
from ..platform.adapter import PlatformCallError, adapter_for, open_platform, platform_openers
from ..persona.profile import Persona
from ..plugins.host import PluginHost
from ..tools.mcp_host import MCPHost
from ..reference.library import open_library
from ..storage.store import Store
from ..work.service import WorkTasks

if TYPE_CHECKING:
    from .personas import PersonaService
    from .management import HostManagement

logger = logging.getLogger(__name__)


class NetworkRuntime:
    def __init__(self, config: SharedConfig, scene_configs: list[tuple[LabConfig, Persona]],
                 store: Store, mind: ChatModel, *,
                 vision: ChatModel | None = None, slots: ModelSlots | None = None,
                 memory: MemoryService | None = None,
                 budget: ModelBudget | None = None,
                 ingestor: UpkeepPart | None = None,
                 tasks: WorkTasks | None = None,
                 learning: UpkeepPart | None = None,
                 jargon: UpkeepPart | None = None,
                 sticker_collection: StickerCollector | None = None,
                 reply_effects: UpkeepPart | None = None,
                 expression_service: ExpressionService | None = None,
                 plugins: PluginHost | None = None,
                 mcp: MCPHost | None = None,
                 lifecycle: HostLifecycle | None = None,
                 on_update: Callable[[], None] | None = None):
        self.config, self.store = config, store
        self.mind, self.vision = mind, vision
        self.events = EventHub()
        self.log_secrets = credentials(config)
        self.memory = memory
        self.budget = ModelBudget(config, store, root=config._instance_root) if budget is None else budget
        if slots is None and (config.limits.daily_tokens is not None or config.limits.scene_daily_tokens):
            raise ValueError("配置每日 token 上限时必须装配共享 ModelSlots")
        if slots is not None:
            slots.admit = self.budget.check
        self.slots = slots
        self.ingestor = ingestor
        self.learning = learning
        self.jargon = jargon
        self.sticker_collection = sticker_collection
        if sticker_collection is not None:
            sticker_collection.on_update = self.notify
            sticker_collection.fetch_media = self.fetch_media
        self.reply_effects = reply_effects
        # Host time when the current platform connection began; None while disconnected.
        self.connected_since: float | None = None
        if reply_effects is not None:
            reply_effects.on_update = self.notify
            reply_effects.connected_since = lambda: self.connected_since
        if jargon is not None:
            jargon.on_update = self.notify
        self.upkeep = next((part.upkeep for part in (ingestor, learning, jargon, reply_effects)
                            if isinstance(part, UpkeepPart)), None)
        if self.upkeep is not None:
            self.upkeep.fork = self.upkeep_fork
        self.expression_service = expression_service
        if expression_service is not None:
            expression_service.on_update = self.notify
        if learning is not None:
            learning.on_update = self.notify
        self.tasks = tasks
        self.plugins = plugins
        self.mcp = mcp
        if plugins is not None:
            plugins.on_update = self.notify
        self.on_update = on_update
        self.status = "created"
        self.last_platform_error: str | None = None
        self.last_runtime_error: str | None = None
        self.stopped = asyncio.Event()
        self.connection_requested = asyncio.Event()
        self.disconnect_requested = False
        self.retention = Retention(self)
        self.config_write_lock = asyncio.Lock()
        self.management: HostManagement | None = None
        # Owners' private scenes being opened, with the messages that arrive meanwhile.
        self.opening_private: dict[str, list[tuple]] = {}
        self.background: set[asyncio.Task] = set()
        self.personas: PersonaService | None = None
        self.scene_titles = SceneTitles(self)
        self.reference = open_library(config._instance_root, memory, store, slots)
        self.accepting = not config.platform_names
        self.storage_error: sqlite3.Error | None = None
        # Built-in scene commands (/help, /status ...); plugins keep priority for a name they register.
        self.commands = Commands()
        self.platform = open_platform(config, on_event=self._receive, on_error=self._platform_error,
                                      on_connection_change=self._connection_changed)
        self.audio = AudioService(store, {cfg.scene: cfg for cfg, _ in scene_configs}, None, slots, self.audio_updated)
        self.bind_audio()
        if tasks is not None:
            tasks.audio = self.audio
            tasks.memory_call = lambda scene, arguments: self.chats[scene].toolset.run_memory(arguments)
            tasks.data_call = lambda scene, name, arguments: self.chats[scene].toolset.run_data_tool(name, arguments)
        self.chats: dict[str, Chat] = {}
        for scene_config, persona in scene_configs:
            scene = scene_config.scene
            if scene in self.chats:
                raise ValueError(f"Duplicate network scene {scene}")
            self.chats[scene] = self.create_chat(scene_config, persona)
        if lifecycle is not None:
            self.bind_management(config._instance_root, lifecycle)
        self.scene_service = SceneService(self)
        self.settings = LiveSettings(self)
        self.runners: dict[str, SceneRunner] = {}
        for scene, chat in self.chats.items():
            self.runners[scene] = SceneRunner(
                chat, lambda result, scene=scene: self._emit({"type": "turn", **result, "scene": scene}),
                ready_for_turn=lambda wait, scene=scene: self.scene_service.ready(scene, wait),
                connected_since=lambda: self.connected_since,
            )
        if plugins is not None:
            plugins.bind(self)
        if mcp is not None:
            mcp.on_update = self.refresh_external_tools

    def bind_audio(self) -> None:
        """OneBot converts voice with get_record; Telegram and Feishu voice is downloaded as sent."""
        live = self.config.delivery == "live"
        onebot = live and "onebot" in self.config.platform_names
        self.audio.platform = (lambda action, params: adapter_for(self.platform, "onebot").call(action, params)) if onebot else None
        self.audio.download = self.fetch_media if live else None

    def delivery(self, scene: str) -> tuple:
        """The send, upload and platform-call bindings a scene's chat uses under the current delivery."""
        live = self.config.delivery == "live"
        sending = self.config.delivery != "simulated"
        return (self.send_message if sending else None, self.upload_file if sending else None,
                (lambda action, params: self.platform_call(action, params, scene=scene)) if live else None)

    def create_chat(self, scene_config: LabConfig, persona: Persona) -> Chat:
        scene = scene_config.scene
        send_message, upload_file, platform_call = self.delivery(scene)
        return Chat(
            scene_config, persona, self.store, self.mind, vision=self.vision, slots=self.slots, memory=self.memory,
            tasks=self.tasks, expression_service=self.expression_service,
            on_compaction=lambda scene=scene: self.compacted(scene),
            on_reply_sample=(None if self.reply_effects is None else
                             lambda scene=scene: self.reply_effects.wake(scene)),
            send_message=send_message, upload_file=upload_file, platform_call=platform_call,
            fetch_media=lambda data, max_bytes, scene=scene: self.fetch_media(scene, data, max_bytes),
            external_tools=(([] if self.plugins is None else self.plugins.tools_for(scene, preparing=True))
                            + ([] if self.mcp is None else self.mcp.tools_for(scene))),
            audio_service=self.audio,
            plugins=self.plugins,
            reference=self.reference,
            on_update=self.notify,
            on_trace=lambda event, scene=scene: self.events.publish(scene=scene, **event),
        )

    # Scene outlets, plugin sends and notices all go through these.
    async def send_message(self, message: ChatMessage, *, image_bytes: bytes | None = None) -> SendResult:
        return await self.platform.send_message(message, image_bytes=image_bytes)

    async def upload_file(self, scene: str, file: str, name: str) -> UploadResult:
        return await self.platform.upload_file(scene, file, name)

    async def platform_call(self, action: str, params: dict, *, scene: str | None = None):
        adapter = self.platform if scene is None else adapter_for(self.platform, scene)
        if adapter is None:
            raise PlatformCallError(f"no platform adapter serves {scene!r}", submitted=False)
        return await adapter.call(action, params)

    async def fetch_media(self, scene: str, data: dict, max_bytes: int) -> bytes:
        """An inbound file named by a platform reference, through the adapter of the scene's platform."""
        adapter = adapter_for(self.platform, scene)
        if adapter is None:
            raise ValueError(f"no platform adapter serves {scene!r}; the file cannot be downloaded")
        return await adapter.download(data, max_bytes)

    def bind_management(self, root: Path, lifecycle: HostLifecycle) -> None:
        from .management import HostManagement
        from .personas import PersonaService

        self.personas = PersonaService(root, self)
        self.management = HostManagement(root, self, lifecycle)
        for chat in self.chats.values():
            chat.toolset.host_management = self.management
            chat.set_external_tools(list(chat.toolset.external.values()))

    async def save_plugin_config(self, name: str, values: dict) -> None:
        """A plugin's own settings change, written like a panel save; plugins call it through update_config."""
        if self.management is None:
            raise RuntimeError("当前宿主没有根配置写入，插件不能修改自己的配置")
        await self.management.plugins.save_values(name, values)

    def refresh_external_tools(self) -> None:
        if self.mcp is not None:
            self.mcp.reserved = {tool['function']['name'] for tool in tool_catalog(platform=True)} | (
                set() if self.plugins is None else set(self.plugins.tool_owner))
        for scene, chat in self.chats.items():
            if self.tasks is not None:
                catalog = tuple(skill for skill in chat.skills if skill.source != 'plugin') + (
                    () if self.plugins is None else self.plugins.skills_for(scene))
                chat.skills = select_skills(catalog, chat.persona.skills)
                self.tasks.skills[scene] = chat.skills
                # A memory plugin's tool comes and goes with the plugin.
                self.tasks.data_tools[scene] = task_data_tools(chat.config, chat.persona,
                                                               platform=self.config.delivery == 'live',
                                                               memory=self.memory, plugins=self.plugins)
            chat.set_external_tools(([] if self.plugins is None else self.plugins.tools_for(scene, preparing=self.status != "running"))
                                    + ([] if self.mcp is None else self.mcp.tools_for(scene)))
        self.notify()

    def audio_updated(self, scene: str) -> None:
        self.runners[scene].changed.set()
        self.notify()

    def compacted(self, scene: str) -> None:
        if self.upkeep is not None:
            self.upkeep.compacted(scene)

    async def upkeep_fork(self, scene: str) -> tuple[list[dict], list[dict]] | None:
        """The scene's chat request without turn state, taken only while no turn is open."""
        runner = self.runners.get(scene)
        return None if runner is None else await runner_fork(runner, self.store)(scene)

    def notify(self) -> None:
        self.events.publish("host.changed")
        if self.on_update is not None:
            self.on_update()

    def _connection_changed(self) -> None:
        self.connected_since = self.store.now() if self.platform.connected else None
        self.accepting = self.status == "running" and self.platform.connected
        if not self.missing_platforms and all(adapter.connected for adapter in self.platform.adapters.values()):
            self.last_platform_error = None
        self.events.publish("host.state")
        self.notify()

    def _status(self, status: str) -> None:
        if self.status != status:
            self.status = status
            self.events.publish("host.state")
            self.notify()

    def _emit(self, result: dict, *, error: BaseException | None = None) -> None:
        """One runtime event in the host log; the panel reads it back from the log file.

        ``error`` text in the result and a passed exception both become the record's ``error`` object.
        """
        if self.platform is None:
            result = {**result, 'input_source': 'stdin' if self.config.panel is None else 'panel'}
        fields = {key: value for key, value in result.items() if key not in {'type', 'error'}}
        failed = error if error is not None else result.get('error')
        log_event(logger, result['type'], level=logging.ERROR if failed else logging.INFO, error=failed, **fields)
        self.events.publish(result['type'], **fields, error=None if failed is None else str(failed))
        if result['type'] == 'turn' and self.upkeep is not None:
            # Upkeep skips a scene while it is in a turn; the turn's end lets it look again.
            self.upkeep.wake(result['scene'])
        self.notify()

    def _platform_error(self, error: str) -> None:
        self.last_platform_error = error
        self._emit({"type": "platform_error", "error": error})

    def stop(self) -> None:
        self.accepting = False
        if self.tasks is not None:
            self.tasks.stop()
        self.stopped.set()
        for runner in self.runners.values():
            runner.close_input()
        if self.status != "stopped":
            self._status("stopping")

    def _receive(self, raw: dict) -> None:
        message = self.platform.parse(raw)
        if message is None:
            return
        if isinstance(message, Notice):
            if not self.accepting:
                self._emit({"type": "receipt", "status": "not_accepted", "reason": self.status})
                return
            if message.scene not in self.runners:
                return
            try:
                self.store.save_notice(message)
                handled = 0 if self.plugins is None else self.plugins.handle_notice(message)
            except sqlite3.Error as error:
                self.storage_error = error
                self.stop()
                raise
            self._emit({"type": "platform_event", "notice_type": message.notice_type,
                        "plugin_handlers": handled})
            self.events.publish('notice.received', scene=message.scene, kind=message.notice_type)
            return
        with log_context(scene=message.scene, platform_message_id=message.platform_message_id):
            self._receive_message(message, raw)

    def _owner_private(self, message) -> bool:
        return (message.scene.split(":", 2)[1] == "private" and not message.is_self
                and getattr(self.config, "owner_private_chat", False) and message.sender.uid in self.config.owners
                and self.management is not None and message.scene not in self.scene_service.retiring)

    async def _open_private(self, scene: str) -> None:
        """An owner's first private message: save the private scene, then take what they sent meanwhile."""
        try:
            await self.management.open_private(scene)
        except Exception as error:
            self.opening_private.pop(scene, None)
            log_event(logger, "private_scene_failed", "没有为主人开启私聊", level=logging.ERROR, scene=scene,
                      error=error)
            return
        log_event(logger, "private_scene_opened", scene=scene)
        for message, raw in self.opening_private.pop(scene, []):
            with log_context(scene=message.scene, platform_message_id=message.platform_message_id):
                self._receive_message(message, raw)

    def _receive_message(self, message, raw: dict) -> None:
        if not self.accepting:
            self._emit({"type": "receipt", "scene": message.scene,
                        "status": "not_accepted", "reason": self.status})
            return
        runner = self.runners.get(message.scene)
        if runner is None and self._owner_private(message):
            waiting = self.opening_private.get(message.scene)
            if waiting is None:
                self.opening_private[message.scene] = [(message, raw)]
                task = asyncio.create_task(self._open_private(message.scene))
                self.background.add(task)
                task.add_done_callback(self.background.discard)
            else:
                waiting.append((message, raw))
            return
        if runner is None or message.scene in self.scene_service.retiring:
            self._emit({"type": "receipt", "scene": message.scene, "status": "ignored",
                        "platform_message_id": message.platform_message_id})
            return
        blocked = message.sender.uid in runner.config.permissions.blacklist
        # A paused chat only stops waking the model; plugin rules and commands keep answering.
        # A closed scene answers neither; its messages are still stored.
        silent = blocked or runner.state.closed
        matched = (None if self.plugins is None or silent else
                   self.plugins.match_message(message, tuple(runner.settings.other_bot_ids)))
        claim = (None if matched is None else
                 (matched.record.name, self.plugins.message_report(message, matched, "已接管，处理尚未结束。")))
        command = None if matched is not None or silent else self.commands.match(self, runner, message)
        if command is not None:
            claim = ("/" + command.command.name, self.commands.report(command))
        try:
            receipt = runner.receive_message(message, raw, wake=matched is None and command is None, plugin_claim=claim)
        except sqlite3.Error as error:
            self.storage_error = error
            self.stop()
            raise
        if (self.reply_effects is not None and receipt["status"] != "duplicate" and not message.is_self):
            self.reply_effects.wake(message.scene)
        if (self.sticker_collection is not None and message.scene in self.sticker_collection.scenes
                and message.scene not in self.sticker_collection.errors
                and receipt["status"] != "duplicate" and not message.is_self and not blocked
                and any(segment.type == "image" for segment in message.segments)):
            self.sticker_collection.request(message.scene)
        if matched is not None and receipt["status"] != "duplicate":
            self.plugins.dispatch_message(message, matched)
            receipt["plugin_handler"] = f"{matched.record.name} {matched.label}"
        if command is not None and receipt["status"] != "duplicate":
            self.commands.dispatch(command)
            receipt["command"] = "/" + command.command.name
        if receipt["status"] != "duplicate":
            self.audio.request(message.scene)
            self.events.publish('message.received', scene=message.scene, message_seq=receipt['message_seq'],
                                verdict=receipt['wake_verdict'])
        self._emit({"type": "receipt", **receipt, "scene": message.scene})

    async def _ready(self, wait: bool, scene: str | None = None) -> bool:
        if self.stopped.is_set():
            return False
        if self.platform is None:
            return True
        # A scene waits for its own platform; one that dropped does not hold the others.
        platform = self.platform if scene is None else adapter_for(self.platform, scene)
        if platform is not None and platform.connected:
            return True
        if not wait:
            return False
        # Both transports come back on their own: forward dials again, reverse waits for the peer.
        connected = asyncio.create_task(self.platform.wait_connected(None, scene=scene))
        stopping = asyncio.create_task(self.stopped.wait())
        try:
            await asyncio.wait({connected, stopping}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            connected.cancel()
            stopping.cancel()
            # wait_connected reports a transport closed by the panel or by shutdown; that ends admission.
            for result in await asyncio.gather(connected, stopping, return_exceptions=True):
                if isinstance(result, BaseException) and not isinstance(result, (PlatformCallError, asyncio.CancelledError)):
                    raise result
        platform = self.platform if scene is None else adapter_for(self.platform, scene)
        return platform is not None and platform.connected and not self.stopped.is_set()

    @property
    def can_connect(self) -> bool:
        return not self.stopped.is_set() and (
            self.status == "connection_failed" or self.status == "running" and bool(self.missing_platforms))

    @property
    def missing_platforms(self) -> list[str]:
        """Configured platforms with no running member: disconnected from the panel or failed to start."""
        if self.platform is None:
            return []
        return [name for name in self.config.platform_names if name not in self.platform.adapters]

    @property
    def can_disconnect(self) -> bool:
        return (self.platform is not None and self.status in {"waiting_connection", "running"}
                and not self.disconnect_requested and not self.stopped.is_set())

    async def disconnect(self) -> None:
        """Close the platform transports now. While running, scenes wait until the panel connects again."""
        if not self.can_disconnect:
            raise RuntimeError("只有等待连接或正在运行时可以断开平台连接")
        self.disconnect_requested = True
        if self.status == "running":
            await self.platform.apply({})
            self.notify()
        else:
            await self.platform.close()

    def request_connection(self) -> None:
        if not self.can_connect:
            raise RuntimeError("当前状态不能手动连接")
        if self.status == "running":
            self.disconnect_requested = False
            task = asyncio.create_task(self._reconnect())
            self.background.add(task)
            task.add_done_callback(self.background.discard)
            return
        self._status("starting")
        self.connection_requested.set()

    async def _reconnect(self) -> None:
        try:
            missing = self.missing_platforms
            await self.platform.apply({**{name: None for name in self.platform.adapters},
                                       **platform_openers(self.config, missing)})
            self.last_platform_error = None
        except PlatformCallError as error:
            self._platform_error(f"{type(error).__name__}: {error}")
        self.notify()

    async def _start_platform(self, *, manual_connection: bool) -> bool:
        """Before starting business services, permit only explicit connection attempts."""
        while not self.stopped.is_set():
            self._status("starting")
            starting = asyncio.create_task(self.platform.start())
            stopping = asyncio.create_task(self.stopped.wait())
            requested: asyncio.Task | None = None
            observed = False
            try:
                done, _ = await asyncio.wait({starting, stopping}, return_when=asyncio.FIRST_COMPLETED)
                if stopping in done:
                    return False
                try:
                    observed = True
                    await starting
                except PlatformCallError as error:
                    self._platform_error(f"{type(error).__name__}: {error}")
                    if not manual_connection:
                        raise
                    self._status("connection_failed")
                    requested = asyncio.create_task(self.connection_requested.wait())
                    await asyncio.wait({requested, stopping}, return_when=asyncio.FIRST_COMPLETED)
                    self.connection_requested.clear()
                else:
                    self.last_platform_error = None
                    self.notify()
                    return True
            finally:
                waiting = [starting, stopping] + ([] if requested is None else [requested])
                for task in waiting:
                    task.cancel()
                results = await asyncio.gather(*waiting, return_exceptions=True)
                # Cancellation can itself fail while OneBot releases a partial
                # connection. Do not turn that unobserved cleanup failure into
                # a clean stop or a reconnectable transport.
                if (not observed and isinstance(results[0], BaseException)
                        and not isinstance(results[0], asyncio.CancelledError)):
                    raise results[0]
        return False

    async def run(self, *, manage_signals: bool = True, manual_connection: bool = False) -> None:
        if self.platform is None:
            from .stdin_host import run_stdin
            await run_stdin(self, manage_signals=manage_signals)
            return
        if self.stopped.is_set():
            self._status("stopped")
            return
        self._status("starting")
        try:
            if manage_signals:
                remove_signals = install_stop(self.stop)
            if self.tasks is not None:
                await self.tasks.recover()
            if not await self._start_platform(manual_connection=manual_connection):
                return
            async with asyncio.TaskGroup() as group:
                pending: list[asyncio.Task] = []
                try:
                    stopping = group.create_task(self.stopped.wait())
                    pending.append(stopping)
                    self._status("waiting_connection")
                    self._emit({"type": "runtime", "status": "started", "input": self.platform.name,
                                "delivery": self.config.delivery, "addresses": self.platform.addresses})
                    terminated = group.create_task(self.platform.wait_terminated())
                    connected = group.create_task(self.platform.wait_connected(None))
                    pending.extend([terminated, connected])
                    done, _ = await asyncio.wait({connected, stopping, terminated}, return_when=asyncio.FIRST_COMPLETED)
                    if connected not in done or stopping in done or terminated in done:
                        return
                    await connected
                    if self.tasks is not None:
                        await self.tasks.start()
                        pending.append(group.create_task(self.tasks.wait_failure()))
                    if self.upkeep is not None:
                        self.upkeep.start()
                    self.audio.start()
                    if self.sticker_collection is not None:
                        self.sticker_collection.start()
                    if self.plugins is not None:
                        await self.plugins.start()
                    self.refresh_external_tools()
                    self.accepting = self.platform.connected
                    self._status("running")
                    self._emit({"type": "runtime", "status": "ready", "input": self.platform.name,
                                "delivery": self.config.delivery})
                    pending.append(group.create_task(self.retention.run()))
                    self.scene_service.start(group)
                    scenes_ended = group.create_task(self.scene_service.wait_stopped())
                    pending.append(scenes_ended)
                    done, _ = await asyncio.wait({scenes_ended, stopping, terminated}, return_when=asyncio.FIRST_COMPLETED)
                    self.accepting = False
                    reason = ("storage_error" if self.storage_error is not None else
                              "signal" if stopping in done
                              else "panel_disconnect" if terminated in done and self.disconnect_requested
                              else "transport_closed" if terminated in done
                              else "scene_stopped")
                    self._status("stopping")
                    self._emit({"type": "runtime", "status": "stopping", "reason": reason})
                    self.stopped.set()
                    if self.plugins is not None:
                        await self.plugins.close()
                    await self.audio.close()
                    if self.sticker_collection is not None:
                        await self.sticker_collection.close()
                    if self.upkeep is not None:
                        await self.upkeep.close()
                    if self.tasks is not None:
                        await self.tasks.close()
                    for runner in self.runners.values():
                        runner.close_input()
                    await self.scene_service.join()
                finally:
                    self.accepting = False
                    self.scene_service.group = None
                    for task in pending:
                        task.cancel()
        finally:
            try:
                try:
                    if self.plugins is not None:
                        await self.plugins.close()
                    if self.tasks is not None:
                        await self.tasks.close()
                finally:
                    try:
                        if self.upkeep is not None:
                            await self.upkeep.close()
                    finally:
                        try:
                            if self.sticker_collection is not None:
                                await self.sticker_collection.close()
                        finally:
                            try:
                                if self.mcp is not None:
                                    await self.mcp.close()
                            finally:
                                try:
                                    await self.audio.close()
                                    await self.reference.close()
                                finally:
                                    await self.platform.close()
                    self._status("stopped")
                    self._emit({"type": "runtime", "status": "stopped"})
            finally:
                if manage_signals:
                    remove_signals()
            if self.storage_error is not None:
                raise self.storage_error


async def run_network(config: SharedConfig, scene_configs: list[tuple[LabConfig, Persona]],
                      store: Store, mind: ChatModel, *,
                      vision: ChatModel | None = None, slots: ModelSlots | None = None,
                      memory: MemoryService | None = None, upkeep: SessionUpkeep | None = None,
                      expression_service: ExpressionService | None = None, budget: ModelBudget | None = None) -> None:
    runtime = NetworkRuntime(config, scene_configs, store, mind, vision=vision, slots=slots, memory=memory,
                             **({} if upkeep is None else upkeep_parts(upkeep)),
                             expression_service=expression_service, budget=budget)
    await runtime.run()
