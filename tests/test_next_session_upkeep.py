"""Session upkeep continues the chat request and fills the memory and learning records in one chain."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json

import pytest

from len_bot.next.chat.session import Chat
from len_bot.next.chat.upkeep import Plan, SessionUpkeep, effect_results, parse_results
from len_bot.next.config import load_host_config
from len_bot.next.learning.jargon_store import JargonStore
from len_bot.next.learning.store import LearningStore
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel, ModelReply
from len_bot.next.persona.profile import load_persona
from len_bot.next.storage.store import Store

from test_next_native_models import peer_server
from test_next_panel_acts_as_owner import SCENE, write_instance
import test_next_turn_speed as turns


def _text(value) -> tuple[int, str, bytes]:
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return 200, 'application/json', json.dumps({
        'choices': [{'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}).encode()


def _receive(store: Store, text: str, user: int, message_id: int) -> None:
    raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
           'user_id': user, 'message_id': message_id, 'time': 1790000000,
           'sender': {'nickname': f'成员{user}', 'role': 'member'},
           'message': [{'type': 'text', 'data': {'text': text}}]}
    from len_bot.next.platform.onebot_messages import parse_message
    store.enqueue(parse_message(raw, own_message_ids=set()), raw, 1790000000)


@asynccontextmanager
async def _upkeep(root, replies):
    write_instance(root, ['onebot:70001'])
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['roles']['mind']['context_window_tokens'] = 64000
    source['compaction']['input_tokens'] = 30000
    source['memory'] = {'backend': 'local', 'local': {'directory': 'memory'}, 'ingest': {}}
    source['scenes'][SCENE]['learning'] = {'extract': True, 'jargon_extract': True, 'auto_adopt': True}
    received = []
    server = await peer_server(replies, received)
    async with server:
        source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        path.write_text(json.dumps(source, ensure_ascii=False))
        persona = root / 'persona/persona.yaml'
        persona.write_text(persona.read_text().replace(
            'tools: [tool_search, schedule, schedule_list, schedule_cancel]', 'tools: [say, memory]'))
        config = load_host_config(root)
        with Store(config.database) as store:
            async with (ChatModel(config.model_settings('mind')) as mind,
                        open_memory(config, store, active_personas={SCENE: 'synthetic-owner'}) as memory):
                chat = Chat(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona), store, mind,
                            memory=memory)
                upkeep = SessionUpkeep(config, store, mind, memory=memory)
                forks = []

                async def fork(_scene):
                    forks.append(await chat.upkeep_fork())
                    return forks[-1]
                upkeep.fork = fork
                yield upkeep, store, memory, forks, lambda: [body for _, _, body in received]


def _group_messages(store: Store) -> None:
    for index, (user, text) in enumerate([(70002, '周末打游戏冲冲冲 yyds'), (70003, 'yyds 今天也是'),
                                          (70002, 'yyds yyds'), (70003, '真的 yyds')]):
        _receive(store, text, user, 40001 + index)


@pytest.mark.asyncio
async def test_one_pass_writes_memory_learns_and_records_one_upkeep_call(tmp_path):
    replies = [
        turns._calls(('memory', {'action': 'write', 'path': 'people/70002.md', 'content': '喜欢周末打游戏。',
                                 'reason': '40001 自己说的'}),
                     ('say', {'content': '我也想玩', 'end_turn': True})),
        _text({'expressions': [{'situation': '有人约周末打游戏', 'style': '冲冲冲', 'sources': ['40001']}],
               'terms': [{'term': 'yyds', 'sources': ['40001', '40002']}]}),
        _text({'meanings': [{'term': 'yyds', 'meaning': '夸东西很厉害', 'confidence': 0.8}]}),
    ]
    async with _upkeep(tmp_path, replies) as (upkeep, store, memory, forks, bodies):
        _group_messages(store)
        upkeep.request(SCENE, 'memory')
        assert await upkeep._step(SCENE)

        history, tools = forks[0]
        first = bodies()[0]
        assert first['tools'] == tools and first['messages'][:-1] == history
        instruction = first['messages'][-1]['content']
        assert instruction.startswith('<整理>') and '周末打游戏冲冲冲' in instruction
        results = [message['content'] for message in bodies()[1]['messages'] if message['role'] == 'tool']
        assert results[1] == '整理时只能用 memory 工具，say 没有执行。'

        job = memory.jobs.latest(SCENE)
        assert job['status'] == 'complete', job
        assert [write['path'] for write in job['details']['writes']] == ['people/70002.md']
        assert '喜欢周末打游戏' in (await memory.backend.read(SCENE, 'people/70002.md')).content
        learning = LearningStore(store)
        assert learning.latest(SCENE)['status'] == 'complete'
        assert [(item['situation'], item['style']) for item in learning.adopted(SCENE)] == [('有人约周末打游戏', '冲冲冲')]
        jargon = JargonStore(store)
        assert [(item['term'], item['count']) for item in jargon.pending(SCENE)] == [('yyds', 4)]
        calls = store.db.execute('SELECT role, turn_id FROM model_calls').fetchall()
        assert [tuple(row) for row in calls] == [('upkeep', None), ('upkeep', None)]

        # The discovered term reached a threshold; the next pass asks only for its meaning.
        upkeep.request(SCENE, 'jargon')
        assert await upkeep._step(SCENE)
        assert 'yyds' in bodies()[2]['messages'][-1]['content']
        assert jargon.pending(SCENE) == []
        assert store.db.execute("SELECT latest_meaning FROM jargon WHERE term='yyds'").fetchone()[0] == '夸东西很厉害'
        assert not await upkeep._step(SCENE)


@pytest.mark.asyncio
async def test_a_failed_pass_keeps_the_range_until_retried(tmp_path):
    replies = [_text('不是 JSON'), _text({'expressions': [], 'terms': []})]
    async with _upkeep(tmp_path, replies) as (upkeep, store, memory, forks, bodies):
        _group_messages(store)
        upkeep.request(SCENE, 'expressions')
        assert await upkeep._step(SCENE)
        assert memory.jobs.latest(SCENE)['status'] == 'failed'
        assert LearningStore(store).latest(SCENE)['status'] == 'failed'
        assert not await upkeep._step(SCENE)
        with pytest.raises(ValueError, match='请先重试'):
            upkeep.request(SCENE, 'memory')

        upkeep.retry(SCENE, 'expressions')
        assert await upkeep._step(SCENE)
        assert bodies()[1]['messages'][-1] == bodies()[0]['messages'][-1]
        assert memory.jobs.latest(SCENE)['status'] == 'complete'
        assert LearningStore(store).latest(SCENE)['status'] == 'complete'


@pytest.mark.asyncio
async def test_messages_already_in_the_session_are_named_by_id(tmp_path):
    async with _upkeep(tmp_path, []) as (upkeep, store, memory, forks, bodies):
        _group_messages(store)
        rows = store.memory_messages(SCENE, 0, limit=10)
        plan = Plan(rows=rows, memory_after=0, expressions_after=0)
        history = [{'role': 'user', 'content': '<msg id="40001" from="成员70002">周末打游戏冲冲冲 yyds</msg>'}]
        tools = [{'type': 'function', 'function': {'name': 'memory', 'parameters': {}}}]
        instruction, keys, humans, writes_memory = await upkeep._instruction(SCENE, plan, history, tools)
        assert writes_memory and set(keys) == humans == {'40001', '40002', '40003', '40004'}
        assert 'id 为 40001 的消息' in instruction
        assert '周末打游戏冲冲冲' not in instruction and 'yyds 今天也是' in instruction


def _reply(text: str) -> ModelReply:
    return ModelReply(message={'role': 'assistant', 'content': text}, text=text, tool_calls=[], finish_reason='stop',
                      usage=None, token_usage=None)


def test_results_must_cite_member_messages_of_the_pass():
    humans = {'1', '2'}
    texts = {'1': '今天 yyds', '2': '好耶'}
    good = parse_results(_reply('```json\n{"terms": [{"term": "yyds", "sources": ["1"]}]}\n```'), humans, humans, texts)
    assert good['terms'] == [{'term': 'yyds', 'sources': ['1']}] and good['expressions'] == []
    with pytest.raises(ValueError, match='not group members'):
        parse_results(_reply('{"expressions": [{"situation": "a", "style": "b", "sources": ["9"]}]}'), humans, humans, texts)
    with pytest.raises(ValueError, match='does not occur'):
        parse_results(_reply('{"terms": [{"term": "yyds", "sources": ["2"]}]}'), humans, humans, texts)
    assert effect_results([{'entry_seq': 5, 'reaction': 'agree', 'reason': '接话了'}], {5}) == {5: ('agree', '接话了')}
    with pytest.raises(ValueError, match='missing reply effect'):
        effect_results([], {5})
