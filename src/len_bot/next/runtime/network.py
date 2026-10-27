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
from uuid import uuid4

from .scene_titles import SceneTitles
from .send_hold import SendHold
from ..chat.attention import SceneRunner
from ..media.audio import AudioService
from ..chat.session import Chat
from ..chat.commands import Commands
from ..chat.tools import tool_catalog
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
from ..platform.adapter import PlatformCallError, open_platform
from ..persona.profile import Persona
from ..plugins.host import PluginHost
from ..tools.mcp_host import MCPHost
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
        self.reply_effects = reply_effects
        # Host time when the current OneBot connection began; None while disconnected.
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
        self.personas: PersonaService | None = None
        self.scene_titles = SceneTitles(self)
        self.send_hold = SendHold(config._instance_root)
        self.accepting = config.onebot is None
        self.storage_error: sqlite3.Error | None = None
        # Built-in scene commands (/help, /status ...); plugins keep priority for a name they register.
        self.commands = Commands()
        self.platform = open_platform(config, on_event=self._receive, on_error=self._platform_error,
                                      on_connection_change=self._connection_changed)
        self.audio = AudioService(store, {cfg.scene: cfg for cfg, _ in scene_configs},
                                  self.platform.call if config.delivery == "onebot" else None, slots,
                                  self.audio_updated)
        if tasks is not None:
            tasks.audio = self.audio
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

    def create_chat(self, scene_config: LabConfig, persona: Persona) -> Chat:
        scene = scene_config.scene
        return Chat(
            scene_config, persona, self.store, self.mind, vision=self.vision, slots=self.slots, memory=self.memory,
            tasks=self.tasks, expression_service=self.expression_service,
            on_compaction=lambda scene=scene: self.compacted(scene),
            on_reply_sample=(None if self.reply_effects is None else
                             lambda scene=scene: self.reply_effects.wake(scene)),
            send_message=self.send_message if self.config.delivery != "simulated" else None,
            upload_file=self.upload_file if self.config.delivery != "simulated" else None,
            platform_call=((lambda action, params, scene=scene: self.platform_call(action, params, scene=scene))
                           if self.config.delivery == "onebot" else None),
            external_tools=(([] if self.plugins is None else self.plugins.tools_for(scene, preparing=True))
                            + ([] if self.mcp is None else self.mcp.tools_for(scene))),
            audio_service=self.audio,
            plugin_recall=None if self.plugins is None else self.plugins.recall,
            plugin_compact=None if self.plugins is None else self.plugins.compact,
            on_update=self.notify,
            on_trace=lambda event, scene=scene: self.events.publish(scene=scene, **event),
        )

    def held(self, scene: str | None) -> bool:
        """The host-wide send hold, or a scene configured to simulate its delivery."""
        return self.send_hold.enabled or (scene in self.chats and self.chats[scene].config.simulated_delivery)

    # Scene outlets go through these, so the send hold also covers plugin sends and notices.
    async def send_message(self, message: ChatMessage, *, image_bytes: bytes | None = None) -> SendResult:
        if self.held(message.scene):
            return SendResult("simulated", f"simulated:{uuid4()}", None)
        return await self.platform.send_message(message, image_bytes=image_bytes)

    async def upload_file(self, scene: str, file: str, name: str) -> UploadResult:
        if self.held(scene):
            return UploadResult("simulated", None, None, None)
        return await self.platform.upload_file(scene, file, name)

    async def platform_call(self, action: str, params: dict, *, scene: str | None = None):
        # While held only reads reach OneBot; actions that change QQ state are answered here.
        if self.held(scene) and not action.startswith("get_"):
            return {"status": "ok", "retcode": 0, "data": None}
        return await self.platform.call(action, params)

    def bind_management(self, root: Path, lifecycle: HostLifecycle) -> None:
        from .management import HostManagement
        from .personas import PersonaService

        self.personas = PersonaService(root, self)
        self.management = HostManagement(root, self, lifecycle)
        for chat in self.chats.values():
            chat.toolset.host_management = self.management
            chat.set_external_tools(list(chat.toolset.external.values()))

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

    def _receive_message(self, message, raw: dict) -> None:
        if not self.accepting:
            self._emit({"type": "receipt", "scene": message.scene,
                        "status": "not_accepted", "reason": self.status})
            return
        runner = self.runners.get(message.scene)
        if runner is None or message.scene in self.scene_service.retiring:
            self._emit({"type": "receipt", "scene": message.scene, "status": "ignored",
                        "platform_message_id": message.platform_message_id})
            return
        blocked = message.sender.uid in runner.config.permissions.blacklist
        matched = (None if self.plugins is None or blocked or runner.state.paused else
                   self.plugins.match_message(message, tuple(runner.settings.other_bot_ids)))
        claim = (None if matched is None else
                 (matched.record.name, self.plugins.message_report(message, matched, "已接管，处理尚未结束。")))
        command = None if matched is not None or blocked else self.commands.match(self, runner, message)
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

    async def _ready(self, wait: bool) -> bool:
        if self.stopped.is_set():
            return False
        if self.platform is None:
            return True
        if self.platform.connected:
            return True
        if not wait:
            return False
        # Both transports come back on their own: forward dials again, reverse waits for the peer.
        connected = asyncio.create_task(self.platform.wait_connected(None))
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
        return self.platform.connected and not self.stopped.is_set()

    @property
    def can_connect(self) -> bool:
        return self.status == "connection_failed" and not self.stopped.is_set()

    @property
    def can_disconnect(self) -> bool:
        return (self.platform is not None and self.status in {"waiting_connection", "running"}
                and not self.stopped.is_set())

    async def disconnect(self) -> None:
        """Close the OneBot transport now; business stops and a restart reconnects."""
        if not self.can_disconnect:
            raise RuntimeError("只有等待连接或正在运行时可以断开 OneBot")
        self.disconnect_requested = True
        await self.platform.close()

    def request_connection(self) -> None:
        if not self.can_connect:
            raise RuntimeError("只有首次连接失败且业务尚未启动时可以手动连接；其他停止状态请重启宿主")
        self._status("starting")
        self.connection_requested.set()

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
