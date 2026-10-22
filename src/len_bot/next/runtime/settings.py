"""Apply settings read by live scenes; connection and service bindings stay explicit."""

from __future__ import annotations

from copy import deepcopy
import asyncio
from typing import TYPE_CHECKING

from ..chat.proactive import ProactiveStore
from ..models.limits import apply_speech_limits

if TYPE_CHECKING:
    from ..config import HostConfig
    from .network import NetworkRuntime


class LiveSettings:
    def __init__(self, runtime: NetworkRuntime):
        self.runtime = runtime

    async def apply(self, saved: HostConfig) -> None:
        runtime, running = self.runtime, self.runtime.config
        for name in ('owners', 'permissions', 'timezone', 'max_steps', 'turn_timeout_seconds', 'text_delivery',
                     'compaction', 'images', 'audio', 'commands', 'web_read'):
            setattr(running, name, deepcopy(getattr(saved, name)))
        search = saved.web_search
        if (search is None or search.connection is None
                or running.models.providers.get(search.connection) == saved.models.providers[search.connection]):
            running.web_search = deepcopy(search)
        apply_speech_limits(running, saved)
        if runtime.slots is not None:
            if ((saved.limits.daily_tokens is not None or saved.limits.scene_daily_tokens)
                    and (saved.limits.daily_tokens, saved.limits.scene_daily_tokens)
                    != (running.limits.daily_tokens, running.limits.scene_daily_tokens)):
                await asyncio.to_thread(runtime.budget.validate_sources)
            running.limits.daily_tokens = saved.limits.daily_tokens
            running.limits.scene_daily_tokens = dict(saved.limits.scene_daily_tokens)
            running.max_model_requests = saved.max_model_requests
            runtime.slots.resize(saved.max_model_requests)
        if running.memory is not None and saved.memory is not None:
            for name in ('auto_recall', 'recall_budget_chars', 'recall_limit'):
                setattr(running.memory, name, getattr(saved.memory, name))
            if running.memory.ingest is not None and saved.memory.ingest is not None:
                running.memory.ingest = deepcopy(saved.memory.ingest)
                if runtime.ingestor is not None:
                    runtime.ingestor.settings = running.memory.ingest
        for scene, current in running.scenes.items():
            if scene not in saved.scenes:
                continue
            desired = saved.scenes[scene]
            chat, runner = runtime.chats[scene], runtime.runners[scene]
            learning = deepcopy(desired.learning)
            if learning is not None:
                learning.embedding = None if current.learning is None else current.learning.embedding
                for flag, service in (('extract', runtime.learning), ('jargon_extract', runtime.jargon),
                                      ('collect_stickers', runtime.sticker_collection), ('reply_effects', runtime.reply_effects)):
                    if service is None:
                        setattr(learning, flag, False)
            for service, flag in ((runtime.learning, 'extract'), (runtime.jargon, 'jargon_extract'),
                                  (runtime.sticker_collection, 'collect_stickers'), (runtime.reply_effects, 'reply_effects')):
                if service is not None and scene in service.scenes and (learning is None or not getattr(learning, flag)):
                    await service.remove_scene(scene)
            current.learning = learning
            for name in ('timezone', 'voice_mode', 'attention', 'schedules', 'permissions', 'chat_control_roles', 'simulated_delivery'):
                setattr(current, name, deepcopy(getattr(desired, name)))
            if desired.proactive is None or learning is not None and learning.reply_effects:
                current.proactive = deepcopy(desired.proactive)
            if runtime.tasks is not None or not desired.tasks.enabled:
                current.tasks = deepcopy(desired.tasks)
            if not desired.transcribe_audio or runtime.audio.platform is not None and running.models.roles.asr is not None:
                current.transcribe_audio = desired.transcribe_audio
            if desired.persona == current.persona:
                for name in ('persona_aliases', 'relationships', 'behavior_addendum', 'inactive_personas'):
                    setattr(current, name, deepcopy(getattr(desired, name)))
            fresh = running.scene_config(scene)
            for name in ('owners', 'permissions', 'timezone', 'max_steps', 'turn_timeout_seconds', 'text_delivery',
                         'compaction', 'images', 'audio', 'commands', 'web_read', 'web_search', 'attention', 'schedules',
                         'proactive', 'tasks', 'learning', 'transcribe_audio', 'persona_aliases', 'relationships',
                         'behavior_addendum', 'chat_control_roles', 'simulated_delivery', 'inactive_personas'):
                setattr(chat.config, name, deepcopy(getattr(fresh, name)))
            runner.settings = chat.config.attention
            runner.proactive = None if current.proactive is None else ProactiveStore(runtime.store)
            runner.adopt_persona(chat.persona, chat.skills, list(chat.toolset.external.values()))
            runner.apply_attention_settings()
            await runtime.audio.set_automatic(scene, current.transcribe_audio)
            for service, enabled in runtime.scene_service.backgrounds(scene):
                if service is not None and enabled and scene not in service.scenes:
                    service.add_scene(scene)
            if runtime.tasks is not None:
                from ..chat.tools import task_data_tools
                runtime.tasks.data_tools[scene] = task_data_tools(
                    chat.config, chat.persona, platform=running.delivery == 'onebot', memory=runtime.memory)
            runner.changed.set()
        runtime.events.publish('host.state')
        runtime.notify()
