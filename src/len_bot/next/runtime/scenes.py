"""Scene admission and per-scene workers owned by a running host."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import TYPE_CHECKING

from ..chat.attention import SceneRunner
from ..chat.tools import task_data_tools
from ..config import HostConfig
from ..persona.profile import load_persona
from ..tools.skills import load_catalog, select_skills
from ..platform.platform_tools import joined_groups

if TYPE_CHECKING:
    from .network import NetworkRuntime


class SceneService:
    def __init__(self, runtime: NetworkRuntime):
        self.runtime = runtime
        self.group: asyncio.TaskGroup | None = None
        self.tasks: dict[str, asyncio.Task] = {}
        self.changed = asyncio.Event()
        self.retiring: set[str] = set()

    async def ready(self, scene: str, wait: bool) -> bool:
        return scene not in self.retiring and await self.runtime._ready(wait)

    def start_scene(self, scene: str) -> None:
        async def run():
            try:
                await self.runtime.runners[scene].run()
            finally:
                self.changed.set()
        self.tasks[scene] = self.group.create_task(run(), name=f'chat:{scene}')

    def start(self, group: asyncio.TaskGroup) -> None:
        self.group = group
        for scene in self.runtime.runners:
            self.start_scene(scene)

    async def wait_stopped(self) -> None:
        while True:
            self.changed.clear()
            if any(task.done() and scene not in self.retiring for scene, task in self.tasks.items()):
                return
            await self.changed.wait()

    async def join(self) -> None:
        await asyncio.gather(*self.tasks.values())

    async def available(self) -> list[dict]:
        runtime = self.runtime
        if runtime.config.onebot is None:
            return []
        if not runtime.platform.connected:
            raise ValueError('平台尚未连接，无法读取已加入的群')
        groups = await joined_groups(runtime.platform.call)
        return [item for item in groups if item['scene'] not in runtime.chats]

    async def apply(self, saved: HostConfig) -> None:
        for scene in list(self.runtime.config.scenes):
            if scene not in saved.scenes:
                await self.remove(scene)
        for scene, settings in saved.scenes.items():
            if scene not in self.runtime.config.scenes:
                await self.add(scene, settings)

    def backgrounds(self, scene: str):
        runtime = self.runtime
        learning = runtime.config.scenes[scene].learning
        return [(runtime.ingestor, runtime.config.scenes[scene].memory_plugin is None),
                (runtime.learning, learning is not None and learning.extract),
                (runtime.jargon, learning is not None and learning.jargon_extract),
                (runtime.sticker_collection, learning is not None and learning.collect_stickers),
                (runtime.reply_effects, learning is not None and learning.reply_effects)]

    async def add(self, scene: str, settings) -> None:
        runtime = self.runtime
        if runtime.status not in {'created', 'running'}:
            raise ValueError('宿主正在启动或停止，暂时不能接入群聊')
        settings = deepcopy(settings)
        prospective = runtime.config.model_copy(update={'scenes': {**runtime.config.scenes, scene: settings}})
        config = prospective.scene_config(scene)
        persona = await asyncio.to_thread(load_persona, config.persona)
        if runtime.tasks is not None:
            worker = runtime.config.worker
            catalog = await asyncio.to_thread(load_catalog, worker.skills_directory, scene, public_browser=worker.public_browser)
            catalog += () if runtime.plugins is None else runtime.plugins.skills_for(scene)
            runtime.tasks.skills[scene] = select_skills(catalog, persona.skills)
            runtime.tasks.skill_permissions[scene] = persona.skills
            runtime.tasks.tool_permissions[scene] = persona.tools
            runtime.tasks.data_tools[scene] = task_data_tools(config, persona, platform=runtime.config.delivery == 'onebot',
                                                              memory=runtime.memory, plugins=runtime.plugins)
        try:
            chat = runtime.create_chat(config, persona)
            if runtime.management is not None:
                chat.toolset.host_management = runtime.management
                chat.set_external_tools(list(chat.toolset.external.values()))
            runner = SceneRunner(chat, lambda result: runtime._emit({'type': 'turn', **result, 'scene': scene}),
                                 ready_for_turn=lambda wait: self.ready(scene, wait),
                                 connected_since=lambda: runtime.connected_since)
        except Exception:
            if runtime.tasks is not None:
                for mapping in (runtime.tasks.skills, runtime.tasks.skill_permissions, runtime.tasks.tool_permissions, runtime.tasks.data_tools):
                    mapping.pop(scene, None)
            raise
        runtime.config.scenes[scene] = settings
        runtime.chats[scene], runtime.runners[scene] = chat, runner
        runtime.audio.add_scene(config)
        if runtime.memory is not None:
            runtime.memory.jobs.remember_personas(scene, {persona.id})
            runtime.memory.active_personas[scene] = persona.id
        for service, enabled in self.backgrounds(scene):
            if service is not None and enabled:
                service.add_scene(scene)
        if self.group is not None:
            self.start_scene(scene)
        runtime.refresh_external_tools()
        runtime.events.publish('host.state', scene=scene)

    async def remove(self, scene: str) -> None:
        runtime = self.runtime
        if runtime.status not in {'created', 'running'}:
            raise ValueError('宿主正在启动或停止，暂时不能移除群聊')
        self.retiring.add(scene)
        runner = runtime.runners[scene]
        runner.close_input()
        runtime.events.publish('host.state', scene=scene)
        task = self.tasks.get(scene)
        if task is not None:
            await task
        else:
            async with runner.execution:
                pass
        for service, _ in self.backgrounds(scene):
            if service is not None and scene in service.scenes:
                await service.remove_scene(scene)
        await runtime.audio.remove_scene(scene)
        if runtime.tasks is not None:
            await runtime.tasks.remove_scene(scene)
        affected = [] if runtime.plugins is None else [name for name, record in runtime.plugins.plugins.items() if scene in record.scenes]
        runtime.config.scenes.pop(scene)
        runtime.chats.pop(scene)
        runtime.runners.pop(scene)
        self.tasks.pop(scene, None)
        if runtime.memory is not None:
            runtime.memory.active_personas.pop(scene, None)
        if runtime.expression_service is not None:
            runtime.expression_service.clients.pop(scene, None)
        for name, service in runtime.config.mcp.items():
            if scene in service.scenes:
                service.scenes.remove(scene)
                if not service.scenes:
                    service.enabled = False
                    if runtime.mcp is not None:
                        await runtime.mcp.disconnect(name)
        if runtime.config.task_archive is not None and scene in runtime.config.task_archive.scenes:
            runtime.config.task_archive.scenes.remove(scene)
            if not runtime.config.task_archive.scenes:
                runtime.config.task_archive = None
        for name in affected:
            await runtime.plugins.reload(name, runtime.config)
        self.retiring.remove(scene)
        runtime.refresh_external_tools()
        runtime.events.publish('host.state', scene=scene)
