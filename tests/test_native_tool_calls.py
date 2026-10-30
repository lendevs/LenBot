"""Model → host boundary of native privileged tools: the requester is read from a chosen real message."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from len_bot.next.chat.host_manage import HOST_MANAGE_TOOL
from len_bot.next.chat.scene_control import SCENE_CONTROL_TOOL
from len_bot.next.chat.schedule import SCHEDULE_TOOLS
from len_bot.next.chat.session import Chat
from len_bot.next.config import load_config
from len_bot.next.models.client import ChatModel, ToolCall
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store
from len_bot.next.work.tools import DELEGATE_TOOL, TASK_TOOL

SCENE = 'onebot:group:80001'


def _instance(root: Path):
    role = root / 'role'
    role.mkdir(parents=True)
    (role / 'persona.yaml').write_text(json.dumps({
        'id': 'synthetic', 'name': '合成角色', 'brief': '仅用于工具边界。', 'behavior': '正常对话。',
        'self_reference': ['我'], 'aliases': [], 'tools': 'all', 'skills': [], 'styles': []}, ensure_ascii=False))
    for name, body in [('voice.md', '简短。'), ('boundaries.md', '合成。'), ('examples.yaml', '[]\n')]:
        (role / name).write_text(body, encoding='utf-8')
    (root / 'lenbot.config.json').write_text(json.dumps({
        'compaction': {'input_tokens': 2000}, 'mode': 'isolated', 'scene': SCENE, 'bot_id': 'onebot:90001',
        'owners': ['onebot:70001'], 'permissions': {'blacklist': ['onebot:70005']}, 'timezone': 'UTC',
        'database': 'state.sqlite3', 'persona': str(role), 'voice_mode': 'direct',
        'models': {'providers': {'synthetic': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1',
                                               'api_key': 'synthetic-unused-key'}},
                   'roles': {'mind': {'provider': 'synthetic', 'model': 'synthetic-mind', 'context_window_tokens': 8192}}},
    }, ensure_ascii=False), encoding='utf-8')
    return load_config(root), load_persona(role)


def _receive(store: Store, user: int, message_id: int, text: str = '合成请求', at: int = 1790000000) -> None:
    raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
           'user_id': user, 'message_id': message_id, 'time': at,
           'sender': {'nickname': '合成成员', 'role': 'member'}, 'message': [{'type': 'text', 'data': {'text': text}}]}
    store.enqueue(parse_message(raw, own_message_ids=set()), raw, at)


async def _unused_wait(_: float) -> str:
    return 'unused'


@pytest.mark.asyncio
@pytest.mark.parametrize('index_mode', ['missing', 'changed'])
async def test_restored_chat_requests_keep_host_state_separate_with_unavailable_learning_index(tmp_path, index_mode):
    import struct
    from test_next_native_models import peer_server
    from len_bot.next.learning.store import LearningStore
    from len_bot.next.learning.expression_selection import ExpressionService
    from len_bot.next.memory.embeddings import EmbeddingClient, EmbeddingSettings

    config, persona = _instance(tmp_path)
    received = []
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '合成结束'},
                                   'finish_reason': 'stop'}],
                       'usage': {'prompt_tokens': 100, 'completion_tokens': 4}}).encode()
    server = await peer_server([(200, 'application/json', body)], received)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            records = LearningStore(store)
            records.initialize(SCENE, 0)
            batch = records.begin(SCENE, 0, 1, {})
            vector = None if index_mode == 'missing' else {
                ('开心', '好耶'): (struct.pack('<4f', 1, 0, 0, 1), json.dumps({
                    'provider': 'vectors', 'base_url': 'http://old.invalid/v1', 'model': 'old', 'dimensions': 4}), 4)}
            records.complete(batch, [('开心', '好耶', [])], auto_adopt=True, vectors=vector)
            for _ in range(3):
                store.append(SCENE, {'role': 'user', 'content': '宿主启动状态：群会话已恢复，上次保存聊天时间：旧时间。'})
            _receive(store, 70001, 50001, '在吗')
            settings = EmbeddingSettings(provider='vectors', model='new', dimensions=4,
                                         base_url='http://127.0.0.1:1/v1', api_key='synthetic-unused')
            async with ChatModel(config.model_settings('mind')) as mind, EmbeddingClient(settings) as client:
                expressions = ExpressionService(store, {SCENE: client})
                chat = Chat(config, persona, store, mind, expression_service=expressions)
                before = store.active_history(SCENE)
                chat.restore()
                chat.restore()
                assert store.active_history(SCENE) == before
                assert expressions.index_status(SCENE)['needs_rebuild']
                pending = store.pending_messages(SCENE)
                result = await chat.run_turn(batch=(pending[-1][0], [chat.context.batch([pending[-1][1]])]),
                    append_new=lambda *args: _no_new_messages(), wait_for_messages=_unused_wait,
                    attention_state={}, direct=True)
                assert result['status'] == 'settled' and result['error'] is None, result['error']
    messages = received[0][2]['messages']
    assert not any(isinstance(message.get('content'), str) and message['content'].startswith('宿主启动状态：')
                   for message in messages)
    assert '在吗' in messages[-2]['content'] and '<宿主恢复状态>' in messages[-1]['content']


async def _no_new_messages():
    return False


@pytest.mark.asyncio
async def test_say_sticker_uses_the_existing_role_sticker_permission(tmp_path):
    config, persona = _instance(tmp_path)
    persona.tools = ['say']
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind:
            chat = Chat(config, persona, store, mind)
            schema = next(tool['function']['parameters'] for tool in chat.toolset.tools
                          if tool['function']['name'] == 'say')
            assert 'sticker' not in schema['properties']
            with pytest.raises(ValueError, match='没有开放表情能力'):
                await chat.toolset.execute('turn', ToolCall('combined', 'say', {
                    'content': '合成回复', 'sticker': {'query': '开心'}, 'end_turn': True}), _unused_wait)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['text', 'sticker', 'combined'])
@pytest.mark.parametrize('dimension', [8, 1024])
async def test_model_expression_sends_text_and_sticker_in_one_onebot_message(tmp_path, kind, dimension):
    import base64
    from io import BytesIO
    from PIL import Image
    from websockets.asyncio.server import serve
    from test_next_native_models import peer_server
    from len_bot.next.configuration.onebot import OneBotForward
    from len_bot.next.platform.onebot import OneBot

    config, _ = _instance(tmp_path)
    directory = tmp_path / 'role' / 'stickers'
    directory.mkdir()
    images = [Image.new('RGB', (dimension, dimension), color) for color in ('red', 'blue')]
    images[0].save(directory / 'angry.gif', save_all=True, append_images=images[1:], duration=100, loop=0)
    (directory / 'index.yaml').write_text(json.dumps([{'file': 'angry.gif', 'description': '生气的表情',
                                                     'emotions': ['生气'], 'tags': []}], ensure_ascii=False))
    persona = load_persona(tmp_path / 'role')
    model_requests, wire_requests = [], []
    arguments = ({'file': 'angry.gif', 'end_turn': True} if kind == 'sticker' else
                 {'content': '这都能拿错，真服了', 'end_turn': True,
                  **({'sticker': {'file': 'angry.gif'}} if kind == 'combined' else {})})
    tool = 'react' if kind == 'sticker' else 'say'
    body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': None,
        'tool_calls': [{'id': 'fixture-expression', 'type': 'function', 'function': {
            'name': tool, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]}, 'finish_reason': 'tool_calls'}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 7}}).encode()

    async def onebot_peer(websocket):
        async for frame in websocket:
            request = json.loads(frame)
            wire_requests.append(request)
            data = {'user_id': 90001, 'nickname': '合成 Bot'} if request['action'] == 'get_login_info' else {'message_id': 12345}
            await websocket.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': data, 'echo': request['echo']}))

    model_server = await peer_server([(200, 'application/json', body)], model_requests)
    async with model_server, serve(onebot_peer, '127.0.0.1', 0) as wire_server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{model_server.sockets[0].getsockname()[1]}/v1'
        config.compaction.input_tokens = 20000
        config.models.roles.mind.context_window_tokens = 64000
        config.onebot = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{wire_server.sockets[0].getsockname()[1]}')
        config.delivery = 'onebot'
        with Store(config.database) as store:
            _receive(store, 70001, 50001, '外卖被别人拿错了')
            async with ChatModel(config.model_settings('mind')) as mind, OneBot(config.onebot,
                bot_id=config.bot_id, on_event=lambda _: None, on_error=lambda _: None) as bot:
                chat = Chat(config, persona, store, mind, send_message=bot.send_message, platform_call=bot.call)
                pending = store.pending_messages(SCENE)
                result = await chat.run_turn(batch=(pending[-1][0], [chat.context.batch([pending[-1][1]])]),
                    append_new=lambda *args: _no_new_messages(), wait_for_messages=_unused_wait,
                    attention_state={}, direct=True)
                assert result['status'] == 'settled' and result['error'] is None, result['error']
                assert len(store.recent(SCENE, 20)) == 2
    sends = [request for request in wire_requests if request['action'] == 'send_group_msg']
    assert len(sends) == 1 and len(model_requests) == 1
    segments = sends[0]['params']['message']
    assert [segment['type'] for segment in segments] == {
        'text': ['text'], 'sticker': ['image'], 'combined': ['text', 'image']}[kind]
    if kind != 'text':
        assert segments[-1]['data']['sub_type'] == 1
        sent = base64.b64decode(segments[-1]['data']['file'].removeprefix('base64://'))
        with Image.open(BytesIO(sent)) as image:
            assert image.size == (min(dimension, 320), min(dimension, 320))
            assert image.n_frames == 2
            assert image.info['duration'] == 100 and image.info['loop'] == 0
        with Image.open(directory / 'angry.gif') as original:
            assert original.size == (dimension, dimension)
        if dimension == 8:
            assert sent == (directory / 'angry.gif').read_bytes()


def _discover(chat: Chat, *names: str) -> None:
    chat.store.save_discovered_tools(SCENE, list(names))
    chat.toolset.discovered_tools = set(chat.store.load_discovered_tools(SCENE))


@pytest.mark.parametrize('tool', [HOST_MANAGE_TOOL, SCENE_CONTROL_TOOL, *SCHEDULE_TOOLS[::2], DELEGATE_TOOL, TASK_TOOL],
                         ids=lambda tool: tool['function']['name'])
def test_model_facing_schemas_ask_for_a_message_not_an_account(tool):
    properties = tool['function']['parameters']['properties']
    assert 'requester' not in properties and 'source_message_id' in properties


def _tool_reply(*calls: tuple[str, dict]) -> tuple[int, str, bytes]:
    message = {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': f'fixture-{index}-{name}', 'type': 'function',
         'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}
        for index, (name, arguments) in enumerate(calls)]}
    return 200, 'application/json', json.dumps({'choices': [{'message': message, 'finish_reason': 'tool_calls'}],
                                                 'usage': {'prompt_tokens': 100, 'completion_tokens': 7}}).encode()


def _final_reply() -> tuple[int, str, bytes]:
    return 200, 'application/json', json.dumps({
        'choices': [{'message': {'role': 'assistant', 'content': '合成结束'}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 4}}).encode()


class _Management:
    """Stands in for the host management service and records what was actually executed."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, str]] = []

    async def execute(self, scene, arguments):
        self.executed.append((arguments.action, arguments.requester))
        return {'action': arguments.action}


def _tool_results(requests: list) -> list[str]:
    """Tool outputs the model saw in its last request, in call order."""
    return [message['content'] for message in requests[-1][2]['messages'] if message.get('role') == 'tool']


async def _drive(tmp_path, replies, turns, *, append=None):
    """Run scripted turns through ``Chat.run_turn``; ``turns`` are (prepare, run_arguments) pairs."""
    from test_next_native_models import peer_server

    config, persona = _instance(tmp_path)
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    requests: list = []
    management = _Management()
    server = await peer_server(list(replies), requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                chat = Chat(config, persona, store, mind)
                chat.toolset.host_management = management
                chat.set_external_tools([])
                _discover(chat, 'host_manage', 'schedule', 'scene_control')
                for prepare, arguments in turns:
                    batch = prepare(store)
                    async def append_new(called, turn_id, batch=batch):
                        return await append(store, turn_id) if append is not None else False
                    result = await chat.run_turn(
                        batch=None if batch is None else (batch[0], ['合成批次']), append_new=append_new,
                        wait_for_messages=_unused_wait, attention_state={}, **arguments)
                    assert result['status'] == 'settled' and result['error'] is None, result['error']
    return management, requests


@pytest.mark.asyncio
async def test_a_request_may_cite_a_message_from_the_running_turns_batch(tmp_path):
    create = {'when': '2099-01-01T00:00:00+00:00', 'note': '合成提醒', 'for': 'self'}
    replies = [_tool_reply(
        ('host_manage', {'action': 'status', 'source_message_id': '50001'}),
        ('schedule', {**create, 'source_message_id': '50001'}),
        ('schedule', {**create, 'source_message_id': '50005'}),
        ('schedule', {**create, 'source_message_id': '59999'}),
        ('schedule', {**create, 'source_message_id': None}),
        ('schedule', {**create, 'requester': 'onebot:70001', 'source_message_id': '50001'})), _final_reply()]

    def prepare(store):
        _receive(store, 70001, 50001)
        _receive(store, 70005, 50005)
        _receive(store, 70002, 50006)
        return store.pending_messages(SCENE)[-1]

    management, requests = await _drive(tmp_path, replies, [(prepare, {'direct': True})])
    assert management.executed == [('status', 'onebot:70001')]
    results = _tool_results(requests)
    assert '账号 onebot:70001' in results[1]
    assert '黑名单' in results[2]
    assert '真实请求消息' in results[3]
    assert 'Bot 自主' in results[4]
    assert 'requester' in results[5]


@pytest.mark.asyncio
async def test_an_earlier_turns_owner_message_cannot_authorise_a_later_turn(tmp_path):
    """A long-past owner message stays in history; a member's new message cannot borrow it."""
    replies = [_final_reply(), _tool_reply(
        ('host_manage', {'action': 'restart', 'source_message_id': '50001'}),
        ('schedule', {'when': '2099-01-01T00:00:00+00:00', 'note': '合成提醒', 'for': 'self',
                      'source_message_id': '50001'}),
        ('host_manage', {'action': 'status', 'source_message_id': '50002'})), _final_reply()]

    def first(store):
        _receive(store, 70001, 50001, '三年前主人说过的话', at=1690000000)
        return store.pending_messages(SCENE)[-1]

    def second(store):
        _receive(store, 70002, 50002, '成员现在说的话')
        return store.pending_messages(SCENE)[-1]

    management, requests = await _drive(tmp_path, replies, [(first, {'direct': True}), (second, {'direct': True})])
    assert management.executed == [('status', 'onebot:70002')]
    results = _tool_results(requests)
    assert all('本轮收到' in result for result in results[:2])
    assert '本轮收到' not in results[2]


@pytest.mark.asyncio
async def test_a_stored_message_counts_once_the_session_takes_it_in_during_the_turn(tmp_path):
    replies = [_tool_reply(('host_manage', {'action': 'status', 'source_message_id': '50001'})),
               _tool_reply(('host_manage', {'action': 'status', 'source_message_id': '50001'})), _final_reply()]
    joined = []

    def prepare(store):
        _receive(store, 70002, 50002, '成员先说话')
        batch = store.pending_messages(SCENE)[-1]
        _receive(store, 70001, 50001, '主人随后说话，还在队列里')
        joined.append(store.pending_messages(SCENE)[-1][0])
        return batch

    async def append(store, turn_id):
        if len(joined) == 1:
            joined.append(None)
            store.append_batch(SCENE, joined[0], ['[这一轮进行中收到] 主人随后说话'], turn_id=turn_id)
            return True
        return False

    management, requests = await _drive(tmp_path, replies, [(prepare, {'direct': True})], append=append)
    assert management.executed == [('status', 'onebot:70001')]
    results = _tool_results(requests)
    assert '本轮收到' in results[0] and '本轮收到' not in results[1]


@pytest.mark.asyncio
async def test_a_turn_without_new_messages_only_accepts_an_autonomous_schedule(tmp_path):
    replies = [_tool_reply(
        ('host_manage', {'action': 'restart', 'source_message_id': '50001'}),
        ('schedule', {'when': '2099-01-01T00:00:00+00:00', 'note': '合成提醒', 'for': 'self',
                      'source_message_id': '50001'}),
        ('schedule', {'when': '2099-01-01T00:00:00+00:00', 'note': '合成提醒', 'for': 'self',
                      'source_message_id': None})), _final_reply()]

    def earlier(store):
        _receive(store, 70001, 50001, '很早之前主人说的话')
        return store.pending_messages(SCENE)[-1]

    # The earlier turn consumed the owner's message; the later one has no new batch at all.
    management, requests = await _drive(tmp_path, [_final_reply(), *replies],
                                        [(earlier, {'direct': True}), (lambda store: None, {})])
    assert management.executed == []
    results = _tool_results(requests)
    assert '本轮收到' in results[0] and '本轮收到' in results[1] and 'Bot 自主' in results[2]


@pytest.mark.asyncio
async def test_control_and_management_receive_the_host_read_requester(tmp_path):
    seen = []
    replies = [_tool_reply(
        ('scene_control', {'action': 'quiet', 'seconds': 60, 'source_message_id': '50002'}),
        ('host_manage', {'action': 'status', 'source_message_id': '50002'}),
        ('host_manage', {'action': 'status'}),
        ('scene_control', {'action': 'resume'})), _final_reply()]

    def prepare(store):
        _receive(store, 70002, 50002)
        return store.pending_messages(SCENE)[-1]

    from test_next_native_models import peer_server
    config, persona = _instance(tmp_path)
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    requests = []
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                chat = Chat(config, persona, store, mind)
                chat.toolset.scene_control = lambda arguments: seen.append(('scene_control', arguments.requester)) or {}
                chat.toolset.host_management = management = _Management()
                chat.set_external_tools([])
                _discover(chat, 'scene_control', 'host_manage')
                batch = prepare(store)
                result = await chat.run_turn(batch=(batch[0], ['合成批次']), append_new=lambda *args: _no_new_messages(),
                                             wait_for_messages=_unused_wait, attention_state={}, direct=True)
                assert result['status'] == 'settled' and result['error'] is None, result['error']
    assert seen == [('scene_control', 'onebot:70002')]
    assert management.executed == [('status', 'onebot:70002')]
    # Without a chosen message there is no requester; the error names the missing field.
    results = _tool_results(requests)
    assert 'requester' in results[2] and 'source_message_id' in results[3]
