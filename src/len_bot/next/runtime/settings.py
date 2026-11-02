"""Apply a saved root configuration to the running host without a restart."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import logging
from logging.handlers import TimedRotatingFileHandler

from ..chat.proactive import ProactiveStore
from ..models.limits import apply_speech_limits
from ..platform.adapter import PlatformCallError, platform_changes
from .logs import SECRETS, credentials
from len_bot.web.auth import revoke_all_sessions

# Panel fields read when the host starts: the listening socket and the proxies Uvicorn trusts.
PANEL_AT_START = ('host', 'port', 'trusted_proxies', 'assets_dir')

if TYPE_CHECKING:
    from ..config import HostConfig
    from .network import NetworkRuntime


class LiveSettings:
    def __init__(self, runtime: NetworkRuntime):
        self.runtime = runtime

    async def apply_models(self, saved: HostConfig) -> None:
        """Rebind the long-lived model clients; requests already sent finish on their old connection."""
        runtime, running = self.runtime, self.runtime.config
        if running.models == saved.models:
            return
        running.models = deepcopy(saved.models)
        await runtime.mind.rebind(running.model_settings('mind'))
        if runtime.vision is not None:
            await runtime.vision.rebind(running.model_settings('vision'))
        embeddings = [] if runtime.expression_service is None else list(runtime.expression_service.clients.values())
        if runtime.memory is not None and runtime.memory.backend.embedding is not None:
            embeddings.append(runtime.memory.backend.embedding)
        for client in embeddings:
            provider = running.models.providers.get(client.settings.provider)
            if provider is not None and provider.base_url == client.settings.base_url:
                await client.reconnect(provider.base_url, provider.api_key, provider.proxy)

    async def apply_connection(self, saved: HostConfig) -> None:
        """Reopen changed platforms and switch the delivery; unchanged platforms keep their connection.

        A host started without any platform (stdin simulation) keeps that until its next start.
        """
        runtime, running = self.runtime, self.runtime.config
        if runtime.platform is None:
            return
        changes = platform_changes(running, saved)
        delivery = running.delivery != saved.delivery
        for name in ('bot_id', 'onebot', 'telegram', 'feishu', 'delivery'):
            setattr(running, name, deepcopy(getattr(saved, name)))
        if delivery:
            runtime.bind_audio()
            for scene, chat in runtime.chats.items():
                chat.config.delivery = running.delivery
                chat.bind_delivery(*runtime.delivery(scene))
        if changes is not None:
            try:
                await runtime.platform.apply(changes)
            except PlatformCallError as error:
                # The platform status on the panel shows it; the rest of the save still applies.
                runtime._platform_error(f'{type(error).__name__}: {error}')
            else:
                runtime.last_platform_error = None
            runtime.bind_audio()

    @staticmethod
    def apply_logging(running: HostConfig, saved: HostConfig) -> None:
        running.logging.level, running.logging.retention_days = saved.logging.level, saved.logging.retention_days
        root = logging.getLogger()
        root.setLevel(saved.logging.level)
        for handler in root.handlers:
            if isinstance(handler, TimedRotatingFileHandler):
                handler.backupCount = saved.logging.retention_days

    def refresh_scenes(self) -> None:
        """Rebuild every scene's system prompt and tool descriptions for its next turn."""
        for scene, runner in self.runtime.runners.items():
            chat = self.runtime.chats[scene]
            runner.adopt_persona(chat.persona, chat.skills, list(chat.toolset.external.values()))
        self.runtime.notify()

    async def apply(self, saved: HostConfig) -> None:
        runtime, running = self.runtime, self.runtime.config
        await self.apply_models(saved)
        await self.apply_connection(saved)
        for name in ('owners', 'owner_private_chat', 'permissions', 'timezone', 'max_steps', 'turn_timeout_seconds',
                     'text_delivery', 'compaction', 'images', 'audio', 'commands', 'network', 'web_read', 'web_search',
                     'task_archive', 'plugin_catalog'):
            setattr(running, name, deepcopy(getattr(saved, name)))
        self.apply_logging(running, saved)
        runtime.log_secrets = credentials(saved)
        SECRETS.add(runtime.log_secrets)
        if running.panel is not None and saved.panel is not None:
            credentials_changed = (running.panel.password_hash != saved.panel.password_hash
                                   or running.panel.username != saved.panel.username)
            # The sign-in handlers hold this object, so its fields change in place.
            for name in type(saved.panel).model_fields:
                if name not in PANEL_AT_START:
                    setattr(running.panel, name, getattr(saved.panel, name))
            if credentials_changed:
                revoke_all_sessions()
        if running.retention != saved.retention:
            running.retention = deepcopy(saved.retention)
            runtime.retention.wake()
        apply_speech_limits(running, saved)
        if runtime.slots is not None:
            running.limits.daily_tokens = saved.limits.daily_tokens
            running.limits.scene_daily_tokens = dict(saved.limits.scene_daily_tokens)
            running.max_model_requests = saved.max_model_requests
            runtime.slots.resize(saved.max_model_requests)
        if running.memory is not None and saved.memory is not None:
            for name in ('auto_recall', 'recall_budget_chars', 'recall_limit'):
                setattr(running.memory, name, getattr(saved.memory, name))
            if running.memory.ingest is not None and saved.memory.ingest is not None:
                running.memory.ingest = deepcopy(saved.memory.ingest)
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
            for name in ('timezone', 'voice_mode', 'attention', 'schedules', 'permissions', 'chat_control_roles'):
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
                         'compaction', 'images', 'audio', 'commands', 'models', 'network', 'logging', 'bot_id', 'delivery',
                         'web_read', 'web_search', 'attention', 'schedules',
                         'proactive', 'tasks', 'learning', 'transcribe_audio', 'persona_aliases', 'relationships',
                         'behavior_addendum', 'chat_control_roles', 'inactive_personas'):
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
                    chat.config, chat.persona, platform=running.delivery == 'live', memory=runtime.memory,
                    plugins=runtime.plugins)
            runner.changed.set()
        runtime.events.publish('host.state')
        runtime.notify()
