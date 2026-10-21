"""Turn pacing: the last step of a lookup speaks, and requests after expressions think briefly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from len_bot.next.chat.session import Chat
from len_bot.next.config import load_config
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store

from test_next_native_models import peer_server

SCENE = 'onebot:group:80001'


def _instance(root: Path, **mind):
    role = root / 'role'
    role.mkdir(parents=True)
    (role / 'persona.yaml').write_text(json.dumps({
        'id': 'synthetic', 'name': '合成角色', 'brief': '合成。', 'behavior': '正常对话。',
        'self_reference': ['我'], 'aliases': [], 'tools': 'all', 'skills': [], 'styles': []}, ensure_ascii=False))
    for name, body in [('voice.md', '简短。'), ('boundaries.md', '合成。'), ('examples.yaml', '[]\n')]:
        (role / name).write_text(body, encoding='utf-8')
    (root / 'lenbot.config.json').write_text(json.dumps({
        'compaction': {'input_tokens': 20000}, 'mode': 'isolated', 'scene': SCENE, 'bot_id': 'onebot:90001',
        'owners': ['onebot:70001'], 'timezone': 'UTC', 'database': 'state.sqlite3', 'persona': str(role),
        'voice_mode': 'direct', 'max_steps': 2,
        'models': {'providers': {'synthetic': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1',
                                               'api_key': 'synthetic-unused-key'}},
                   'roles': {'mind': {'provider': 'synthetic', 'model': 'synthetic-mind',
                                      'context_window_tokens': 64000, **mind}}},
    }, ensure_ascii=False), encoding='utf-8')
    return load_config(root), load_persona(role)


def _receive(store: Store, text: str, user: int = 70001, message_id: int = 50001) -> None:
    raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
           'user_id': user, 'message_id': message_id, 'time': 1790000000,
           'sender': {'nickname': '合成成员', 'role': 'member'}, 'message': [{'type': 'text', 'data': {'text': text}}]}
    store.enqueue(parse_message(raw, own_message_ids=set()), raw, 1790000000)


def _calls(*calls: tuple[str, dict]) -> tuple[int, str, bytes]:
    return 200, 'application/json', json.dumps({
        'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': f'call-{index}', 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}
            for index, (name, arguments) in enumerate(calls)]}, 'finish_reason': 'tool_calls'}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 4}}).encode()


async def _no_new(*_):
    return False


async def _unused_wait(_: float) -> str:
    return 'unused'


async def _turn(config, persona, replies, later: list[tuple[int, str]] = (), wrap=None):
    """One direct turn; ``later`` messages arrive after the turn's input was taken."""
    received = []
    server = await peer_server(replies, received)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            _receive(store, '帮我查一下刚才说的')
            async with ChatModel(config.model_settings('mind')) as mind:
                chat = Chat(config, persona, store, mind)
                if wrap is not None:
                    chat.toolset.execute = wrap(chat.toolset.execute)
                pending = store.pending_messages(SCENE)
                batch = (pending[-1][0], [chat.context.batch([pending[-1][1]])])
                for index, (user, text) in enumerate(later):
                    _receive(store, text, user, 50002 + index)

                async def append_new(_continuing, turn_id):
                    arrived = store.pending_messages(SCENE)
                    if not arrived:
                        return False
                    store.append_batch(SCENE, arrived[-1][0], [chat.context.batch([item[1] for item in arrived])],
                                       turn_id=turn_id)
                    return True

                result = await chat.run_turn(batch=batch, append_new=append_new, wait_for_messages=_unused_wait,
                                             attention_state={}, direct=True)
    return result, [body for _, _, body in received]


@pytest.mark.asyncio
async def test_last_step_after_a_lookup_offers_only_speech(tmp_path):
    config, persona = _instance(tmp_path)
    result, bodies = await _turn(config, persona, [
        _calls(('recall_chat', {'action': 'recent'})),
        _calls(('say', {'content': '没找到', 'end_turn': True})),
    ])
    assert result['status'] == 'settled', result['error']
    first, last = ({tool['function']['name'] for tool in body['tools']} for body in bodies)
    assert 'recall_chat' in first and last <= {'say', 'react'} and 'say' in last
    assert '这是本轮最后一步' in bodies[1]['messages'][-1]['content']
    assert '这是本轮最后一步' not in bodies[0]['messages'][-1]['content']


@pytest.mark.asyncio
async def test_last_step_keeps_all_tools_once_the_turn_has_spoken(tmp_path):
    config, persona = _instance(tmp_path)
    result, bodies = await _turn(config, persona, [
        _calls(('say', {'content': '我查查', 'end_turn': False}), ('recall_chat', {'action': 'recent'})),
        _calls(('say', {'content': '没找到', 'end_turn': True})),
    ])
    assert result['status'] == 'settled', result['error']
    assert 'recall_chat' in {tool['function']['name'] for tool in bodies[1]['tools']}
    assert '这是本轮最后一步' not in bodies[1]['messages'][-1]['content']


@pytest.mark.asyncio
async def test_a_followup_from_the_same_person_continues_the_turn(tmp_path):
    config, persona = _instance(tmp_path)
    config.max_steps = 4
    result, bodies = await _turn(config, persona, [
        _calls(('say', {'content': '好', 'end_turn': True})),
        _calls(('say', {'content': '这个也行', 'end_turn': True})),
    ], later=[(70001, '还有第二件事')])
    assert result['status'] == 'settled' and len(bodies) == 2, result
    assert '还有第二件事' in json.dumps(bodies[1]['messages'], ensure_ascii=False)
    assert result['extensions'] == 1


@pytest.mark.asyncio
async def test_other_people_talking_does_not_hold_the_turn_open(tmp_path):
    config, persona = _instance(tmp_path)
    config.max_steps = 4
    result, bodies = await _turn(config, persona, [
        _calls(('say', {'content': '好', 'end_turn': True})),
    ], later=[(70002, '别人在聊别的')])
    assert result['status'] == 'settled' and len(bodies) == 1 and result['extensions'] == 0


@pytest.mark.asyncio
async def test_new_messages_use_the_quick_effort_and_tool_results_the_full_one(tmp_path):
    config, persona = _instance(tmp_path, reasoning_effort='high', quick_reasoning_effort='low')
    config.max_steps = 4
    result, bodies = await _turn(config, persona, [
        _calls(('recall_chat', {'action': 'recent'})),
        _calls(('say', {'content': '找到了', 'end_turn': True})),
    ])
    assert result['status'] == 'settled', result['error']
    assert [body['reasoning_effort'] for body in bodies] == ['low', 'high']
    with Store(config.database) as store:
        recorded = [json.loads(row[0])['settings']['reasoning_effort'] for row in
                    store.db.execute("SELECT request FROM model_calls WHERE role='mind' ORDER BY id")]
    assert recorded == ['low', 'high']


def test_quick_effort_is_checked_against_the_provider_at_load(tmp_path):
    from len_bot.next.configuration.models import Models
    source = {'providers': {'a': {'api': 'anthropic', 'base_url': 'https://example.invalid/v1', 'api_key': 'k'}},
              'roles': {'mind': {'provider': 'a', 'model': 'm', 'context_window_tokens': 8000,
                                 'quick_reasoning_effort': 'low'}}}
    with pytest.raises(ValueError, match='温度'):
        Models.model_validate(source)
    source['roles']['mind']['temperature'] = None
    assert Models.model_validate(source).roles.mind.quick_reasoning_effort == 'low'


@pytest.mark.asyncio
async def test_read_only_calls_of_one_reply_run_together_and_keep_their_order(tmp_path):
    import asyncio
    config, persona = _instance(tmp_path)
    config.max_steps = 4
    events = []

    def wrap(execute):
        async def slow(turn_id, call, *args, **kwargs):
            if call.name == 'recall_chat':
                events.append(('start', call.id))
                await asyncio.sleep(0.1 if call.id == 'call-0' else 0.01)
                events.append(('end', call.id))
            return await execute(turn_id, call, *args, **kwargs)
        return slow

    result, bodies = await _turn(config, persona, [
        _calls(('recall_chat', {'action': 'recent'}), ('recall_chat', {'action': 'search', 'query': '刚才'})),
        _calls(('say', {'content': '好', 'end_turn': True})),
    ], wrap=wrap)
    assert result['status'] == 'settled', result['error']
    assert events[:2] == [('start', 'call-0'), ('start', 'call-1')]
    tools = [message for message in bodies[1]['messages'] if message['role'] == 'tool']
    assert [message['tool_call_id'] for message in tools] == ['call-0', 'call-1']
