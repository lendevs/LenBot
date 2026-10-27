"""Panel endpoints for isolated chat sessions."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Literal
import yaml
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import responses
from ...chat.tools import tool_catalog, tool_unavailable_reasons
from ...config import HostConfig, LabConfig, load_host_config
from .persona import finish_role_write
from .timeline import TurnDetail, read_turn
from ...instance_lock import InstanceBusyError, instance_lock
from ...runtime.logs import LoggingSettings
from ...memory.service import LocalMemoryConfig, open_memory
from ...models.client import ChatModel
from ...runtime.identity import IdentitySettings
from ...runtime.network import NetworkRuntime
from ...runtime.personas import roles
from ...trials.panel import PanelSession, TestMessage, stored_image
from ..auth import changes_socket, cookie_name
from ...persona.profile import PERSONA_FILES, Persona, PersonaTarget, parse_persona_files
from ...storage.store import Store
from len_bot.web.auth import session_user
from ...prompt_files import read_prompt


class PersonaDraft(PersonaTarget):
    model_config = ConfigDict(strict=True, extra='forbid')
    files: dict[str, str]

    @field_validator('files')
    @classmethod
    def four_files(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != set(PERSONA_FILES):
            raise ValueError(f'Role draft requires exactly {PERSONA_FILES!r}; got={list(value)!r}')
        return value


class TrialStart(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    scene: str
    acknowledge_model_cost: bool
    context_messages: int = Field(default=0, ge=0, le=100)
    persona_draft: PersonaDraft | None = None


@dataclass
class Trial:
    id: str
    scene: str
    root: Path
    created: float
    config: LabConfig
    session: PanelSession
    resources: AsyncExitStack
    excluded: list[str]
    context: list[str]
    persona_source: Literal['running', 'draft'] = 'running'
    # The role library directory a draft trial was made from.
    draft_source: str | None = None
    stopped: float | None = None
    final_state: dict | None = None

    def info(self) -> dict:
        return {'id': self.id, 'scene': self.scene, 'created': self.created, 'stopped': self.stopped,
                'context': self.context, 'active': self.stopped is None, 'root': str(self.root), 'excluded_tools': self.excluded,
                'memory': '独立空白本地记忆' if self.config.memory is not None else '本次不装配记忆',
                'persona': self.session.chat.persona.name,
                'persona_source': self.persona_source,
                'draft_path': str(self.root / 'persona-draft') if self.persona_source == 'draft' else None,
                'draft_source': self.draft_source,
                'models': {'mind': self.config.models.roles.mind.model}}

    def snapshot(self) -> dict:
        return self.session.snapshot() if self.final_state is None else self.final_state

    async def stop(self) -> None:
        if self.stopped is not None:
            return
        self.session.closing = True
        self.session.task.cancel()
        await asyncio.gather(self.session.task, return_exceptions=True)
        self.final_state = self.session.snapshot()
        # An explicit stop is not a scene-runner failure; interrupted calls remain in the timeline.
        if self.session.task.cancelled():
            self.final_state['error'] = None
        self.stopped = time.time()
        self.session.notify()
        try:
            await self.resources.aclose()
        except Exception as error:
            self.final_state['error'] = f'试聊轮次已停止，但资源释放失败：{type(error).__name__}: {error}'
            self.session.notify()
            raise


def write_trial_files(config: LabConfig, persona: Persona, draft: PersonaDraft | None = None) -> None:
    root = config.database.parent
    # Derived runtime parameters still live in this test root's sole config file, not env/CLI.
    config_path = root / 'lenbot.config.json'
    with config_path.open('x', encoding='utf-8') as stream:
        config_path.chmod(0o600)
        stream.write(config.model_dump_json(indent=2))
    # The active session uses this in-memory snapshot; no editor receives the production role path.
    snapshot_dir = config.persona
    snapshot_dir.mkdir(mode=0o700)
    if draft is not None:
        draft_dir = root / 'persona-draft'
        draft_dir.mkdir(mode=0o700)
        for filename, content in draft.files.items():
            (draft_dir / filename).write_bytes(content.encode('utf-8'))
    metadata = persona.model_dump(exclude={'voice','boundaries','examples'})
    (snapshot_dir / 'persona.yaml').write_text(yaml.safe_dump(metadata, allow_unicode=True), encoding='utf-8')
    (snapshot_dir / 'voice.md').write_text(persona.voice, encoding='utf-8')
    (snapshot_dir / 'boundaries.md').write_text(persona.boundaries, encoding='utf-8')
    (snapshot_dir / 'examples.yaml').write_text(yaml.safe_dump([example.model_dump() for example in persona.examples], allow_unicode=True), encoding='utf-8')
    for filename, content in persona.expression.items():
        (snapshot_dir / filename).write_text(content, encoding='utf-8')
    if persona.avatar is not None:
        (snapshot_dir / 'avatar.png').write_bytes(persona.avatar.data)
    for filename, document in persona.knowledge.items():
        path = snapshot_dir / 'knowledge' / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document.content, encoding='utf-8')
    if persona.stickers:
        entries = []
        for sticker in persona.stickers.values():
            path = snapshot_dir / 'stickers' / sticker.file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(sticker.data)
            entries.append({'file':sticker.file, 'description':sticker.description,
                            'emotions':list(sticker.emotions), 'tags':list(sticker.tags)})
        (snapshot_dir / 'stickers' / 'index.yaml').write_text(yaml.safe_dump(entries, allow_unicode=True), encoding='utf-8')


def load_draft_persona(root: Path, scene: str, draft: PersonaDraft) -> Persona:
    """A draft of any role in the library may be tried against this scene's recent chat."""
    saved = load_host_config(root)
    if scene not in saved.scenes:
        raise ValueError('场景已从保存配置移除，不能读取其角色资料用于新草稿试聊')
    path = next((role.path for role in roles(root, saved) if str(role.path) == draft.directory), None)
    if path is None:
        raise ValueError(f'试聊草稿须来自角色库中的角色；directory={draft.directory!r}')
    return parse_persona_files(path, draft.files)


class HostTrials:
    def __init__(self, config: HostConfig, runtime: NetworkRuntime, root: Path, *, write_lock: asyncio.Lock):
        self.config, self.runtime, self.root = config, runtime, root
        self.records: dict[str, Trial] = {}
        self.lock = asyncio.Lock()
        self.write_lock = write_lock
        self.closing = False

    def notify(self):
        for trial in self.records.values():
            trial.session.notify()

    def get(self, trial_id: str) -> Trial:
        if trial_id not in self.records:
            raise HTTPException(404, '本次运行中找不到此试聊，请新建试聊')
        return self.records[trial_id]

    async def start(self, scene: str, context_messages: int = 0,
                    persona_draft: PersonaDraft | None = None) -> Trial:
        async with self.lock:
            if self.closing:
                raise HTTPException(503, '宿主正在停止，不再新建试聊')
            if scene not in self.config.scenes:
                raise HTTPException(404, '未配置此场景')
            if any(trial.stopped is None for trial in self.records.values()):
                raise HTTPException(409, '已有活动试聊，请先停止再新建')
            if persona_draft is None:
                persona = self.runtime.chats[scene].persona.model_copy(deep=True)
            else:
                async with self.write_lock:
                    persona = await asyncio.to_thread(load_draft_persona, self.root, scene, persona_draft)
            root = self.root / '.runtime' / 'chat-tests' / str(uuid4())
            if root.resolve(strict=False) != root:
                raise ValueError(f'试聊根不能通过符号链接创建到其他目录：{root}')
            root.mkdir(parents=True, mode=0o700)
            stack = AsyncExitStack()
            try:
                stack.enter_context(instance_lock(root))
                source_chat = self.runtime.chats[scene]
                context = [source_chat.context.render(message) for message in
                           self.runtime.store.recent(scene, context_messages)] if context_messages else []
                source = self.config.scene_config(scene)
                memory = None
                if isinstance(source.memory, LocalMemoryConfig):
                    memory = source.memory.model_copy(update={
                        'local': source.memory.local.model_copy(update={'directory': root / 'memory'}),
                        'ingest': None, 'summaries': False})
                # A trial runs inside the host and logs through it; its own setting must not name the host's
                # log directory, which lies outside the trial root that offline migrations reload it from.
                candidate = source.model_copy(update={'mode':'isolated', 'onebot':None, 'delivery':'simulated', 'logging':LoggingSettings(directory=root / 'logs'),
                    'database':root / 'state.db', 'persona':root / 'persona-snapshot', 'owners':[],
                    'permissions': IdentitySettings(), 'panel':None, 'plugins':[], 'worker':None, 'tasks':source.tasks.model_copy(update={'enabled':False}),
                    'learning':None, 'proactive':None, 'transcribe_audio':False, 'memory':memory,
                    'web_read':None, 'web_search':None})
                config = LabConfig.model_validate_json(candidate.model_dump_json())
                if persona_draft is None:
                    original = self.runtime.chats[scene].toolset.allowed_tool_names
                elif persona.tools == 'all':
                    original = {item['function']['name'] for item in tool_catalog(platform=False)}
                else:
                    original = set(persona.tools)
                allowed = [item['function']['name'] for item in tool_catalog(platform=False)
                           if item['function']['name'] in original
                           and not tool_unavailable_reasons(config, persona, item['function']['name'])]
                excluded = sorted(original - set(allowed))
                persona = persona.model_copy(update={'tools':allowed, 'skills':[]})
                await finish_role_write(write_trial_files, config, persona, persona_draft)
                store = stack.enter_context(Store(config.database))
                if context:
                    intro = read_prompt('next_trial_context.md')
                    store.append(scene, {'role': 'user', 'content': intro + '\n\n' + '\n'.join(context)})
                mind = await stack.enter_async_context(ChatModel(config.model_settings('mind')))
                vision = (None if config.models.roles.vision is None else
                          await stack.enter_async_context(ChatModel(config.model_settings('vision'))))
                local_memory = await stack.enter_async_context(open_memory(config, store,
                    active_personas={scene: persona.id}, slots=self.runtime.chats[scene].slots))
                session = PanelSession(config, store, mind, vision=vision, memory=local_memory,
                                       persona=persona, slots=self.runtime.chats[scene].slots)
                trial = Trial(root.name, scene, root, time.time(), config, session, stack, excluded, context,
                              persona_source='running' if persona_draft is None else 'draft',
                              draft_source=None if persona_draft is None else persona_draft.directory)
                self.records[trial.id] = trial
                return trial
            except BaseException as error:
                try:
                    await stack.aclose()
                except BaseException as cleanup_error:
                    error.add_note(f'Trial resource cleanup also failed: {type(cleanup_error).__name__}: {cleanup_error}')
                raise

    async def close(self):
        async with self.lock:
            self.closing = True
            for trial in self.records.values():
                await trial.stop()


def register_host_trials(app: FastAPI, trials: HostTrials, user):
    @app.get('/api/host/trials', response_model=responses.TrialList, response_model_exclude_unset=True)
    async def listing(_: str = Depends(user)):
        return {'items':[trial.info() for trial in trials.records.values()]}

    @app.post('/api/host/trials', response_model=responses.TrialInfo, response_model_exclude_unset=True)
    async def start(item: TrialStart, _: str = Depends(user)):
        if not item.acknowledge_model_cost:
            raise HTTPException(422, '开始前须确认模型请求照常计费；平台发送始终为模拟')
        try:
            return (await trials.start(item.scene, item.context_messages, item.persona_draft)).info()
        except InstanceBusyError as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, OSError) as error:
            raise HTTPException(422, f'{type(error).__name__}: {error}') from error

    @app.post('/api/host/trials/{trial_id}/stop', response_model=responses.TrialInfo, response_model_exclude_unset=True)
    async def stop(trial_id: str, _: str = Depends(user)):
        async with trials.lock:
            trial = trials.get(trial_id)
            await trial.stop()
            return trial.info()

    @app.get('/api/host/trials/{trial_id}/state', response_model=responses.TrialState, response_model_exclude_unset=True)
    async def state(trial_id: str, _: str = Depends(user)):
        return trials.get(trial_id).snapshot()

    @app.post('/api/host/trials/{trial_id}/messages', response_model=responses.MessageReceipt, response_model_exclude_unset=True)
    async def message(trial_id: str, item: TestMessage, _: str = Depends(user)):
        trial = trials.get(trial_id)
        if trial.stopped is not None:
            raise HTTPException(409, '此试聊已停止，不接收消息')
        return trial.session.receive(item)

    @app.get('/api/host/trials/{trial_id}/messages/{seq}/images/{image_index}')
    async def image(trial_id: str, seq: int, image_index: int, _: str = Depends(user)):
        trial = trials.get(trial_id)
        if trial.stopped is None:
            return stored_image(trial.session.store, trial.scene, seq, image_index)
        with Store(trial.config.database) as store:
            return stored_image(store, trial.scene, seq, image_index)

    @app.get('/api/host/trials/{trial_id}/avatar')
    async def avatar(trial_id: str, _: str = Depends(user)):
        return trials.get(trial_id).session.avatar()

    @app.get('/api/host/trials/{trial_id}/turns/{turn_id}', response_model=responses.StoredTurn, response_model_exclude_unset=True)
    async def turn(trial_id: str, turn_id: str, _: str = Depends(user)):
        trial = trials.get(trial_id)
        def read():
            with Store(trial.config.database, readonly=True) as store:
                return store.turn_detail(trial.scene, turn_id)
        result = await asyncio.to_thread(read)
        if result is None:
            raise HTTPException(404, '此回合不属于当前试聊')
        return result

    @app.get('/api/host/trials/{trial_id}/turns/{turn_id}/steps', response_model=TurnDetail)
    async def turn_steps(trial_id: str, turn_id: str, _: str = Depends(user)):
        """The same step view as a group's live timeline, read from the trial's own database."""
        trial = trials.get(trial_id)
        def read():
            with Store(trial.config.database, readonly=True) as store:
                return read_turn(store, trial.scene, turn_id)
        result = await asyncio.to_thread(read)
        if result is None:
            raise HTTPException(404, '此回合不属于当前试聊')
        return result

    @app.websocket('/api/host/trials/{trial_id}/events')
    async def events(websocket: WebSocket, trial_id: str):
        try:
            session_user(websocket.cookies.get(cookie_name(websocket)))
            trial = trials.get(trial_id)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await changes_socket(websocket, trial.session.listeners)
