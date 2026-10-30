"""Session upkeep continues the chat request and fills the memory and learning records in one chain."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json

import pytest

from len_bot.next.chat.session import Chat
from len_bot.next.chat import upkeep as upkeep_module
from len_bot.next.chat.upkeep import Plan, SessionUpkeep, parse_results
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
        _text({'meanings': [{'term': 'yyds', 'meaning': '夸东西很厉害', 'ordinary_meaning': '永远的神', 'same_meaning': False, 'confidence': 0.8}]}),
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
async def test_an_unreadable_reply_is_asked_once_more(tmp_path):
    replies = [_text('不是 JSON'), _text({'expressions': [], 'terms': []})]
    async with _upkeep(tmp_path, replies) as (upkeep, store, memory, forks, bodies):
        _group_messages(store)
        upkeep.request(SCENE, 'expressions')
        assert await upkeep._step(SCENE)
        assert '没法解析' in bodies()[1]['messages'][-1]['content']
        assert memory.jobs.latest(SCENE)['status'] == 'complete'
        assert LearningStore(store).latest(SCENE)['status'] == 'complete'


@pytest.mark.asyncio
async def test_a_failed_pass_runs_again_by_itself(tmp_path, monkeypatch):
    replies = [_text('不是 JSON'), _text('还不是'), _text({'expressions': [], 'terms': []})]
    async with _upkeep(tmp_path, replies) as (upkeep, store, memory, forks, bodies):
        _group_messages(store)
        upkeep.request(SCENE, 'expressions')
        assert await upkeep._step(SCENE)
        assert memory.jobs.latest(SCENE)['status'] == 'failed'
        assert LearningStore(store).latest(SCENE)['status'] == 'failed'
        with pytest.raises(ValueError, match='请先重试'):
            upkeep.request(SCENE, 'memory')
        # Too soon after the failure.
        assert not await upkeep._step(SCENE)

        monkeypatch.setattr(upkeep_module, 'RETRY_DELAY_SECONDS', 0)
        assert await upkeep._step(SCENE)
        assert bodies()[2]['messages'][-1] == bodies()[0]['messages'][-1]
        assert memory.jobs.latest(SCENE)['status'] == 'complete'
        assert LearningStore(store).latest(SCENE)['status'] == 'complete'
        assert not await upkeep._step(SCENE)


@pytest.mark.asyncio
async def test_items_that_fail_a_check_are_dropped_and_the_pass_completes(tmp_path):
    replies = [_text({'expressions': [{'situation': '有人约周末打游戏', 'style': '冲冲冲', 'sources': ['40001', '99999']},
                                      {'situation': '', 'style': '空情境', 'sources': ['40001']}],
                      'terms': [{'term': 'yyds', 'sources': ['40001']}, {'term': '不存在的词', 'sources': ['40002']}]})]
    async with _upkeep(tmp_path, replies) as (upkeep, store, memory, forks, bodies):
        _group_messages(store)
        upkeep.request(SCENE, 'expressions')
        assert await upkeep._step(SCENE)
        assert memory.jobs.latest(SCENE)['status'] == 'complete'
        learning = LearningStore(store)
        assert learning.latest(SCENE)['status'] == 'complete'
        assert [item['style'] for item in learning.adopted(SCENE)] == ['冲冲冲']
        assert [item['term'] for item in JargonStore(store).items(SCENE, None, 10, 0)['items']] == ['yyds']


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


def test_results_keep_only_items_citing_member_messages_of_the_pass():
    humans = {'1', '2'}
    texts = {'1': '今天 yyds', '2': '好耶'}
    results, dropped = parse_results(_reply('```json\n{"terms": [{"term": "yyds", "sources": ["1", "2"]}]}\n```'),
                                     humans, texts, set())
    assert results['terms'] == [{'term': 'yyds', 'sources': ['1']}] and results['expressions'] == [] and not dropped
    results, dropped = parse_results(_reply(json.dumps({
        'expressions': [{'situation': 'a', 'style': 'b', 'sources': ['9']}],
        'effects': [{'entry_seq': 5, 'reaction': 'agree', 'reason': '接话了'},
                    {'entry_seq': 6, 'reaction': 'agree', 'reason': '不在本批'}]})), humans, texts, {5})
    assert results['expressions'] == [] and results['effects'] == {5: ('agree', '接话了')}
    assert len(dropped) == 2
    with pytest.raises(ValueError, match='Invalid upkeep result'):
        parse_results(_reply('[]'), humans, texts, set())


@pytest.mark.parametrize('ingest', [True, False])
def test_memory_stays_loaded_while_upkeep_writes_with_it(tmp_path, ingest):
    write_instance(tmp_path, ['onebot:70001'])
    path = tmp_path / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['memory'] = {'backend': 'local', 'local': {'directory': 'memory'}, **({'ingest': {}} if ingest else {})}
    path.write_text(json.dumps(source, ensure_ascii=False))
    persona = tmp_path / 'persona/persona.yaml'
    persona.write_text(persona.read_text().replace(
        'tools: [tool_search, schedule, schedule_list, schedule_cancel]', 'tools: [tool_search, say, memory]'))
    config = load_host_config(tmp_path)

    async def tools():
        with Store(config.database) as store:
            async with (ChatModel(config.model_settings('mind')) as mind,
                        open_memory(config, store, active_personas={SCENE: 'synthetic-owner'}) as memory):
                chat = Chat(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona), store, mind,
                            memory=memory)
                return {tool['function']['name'] for tool in chat.toolset.tools}, chat.context.system
    names, system = asyncio.run(tools())
    assert ('memory' in names) is ingest
    assert ('长期记忆用 memory 工具读写' in system) is ingest
    assert ('用 tool_search 加载 memory 后按 path read' in system) is not ingest


@pytest.mark.asyncio
async def test_used_up_tool_rounds_ask_for_the_result(tmp_path):
    replies = [turns._calls(('memory', {'action': 'search', 'query': '游戏'})),
               _text({'expressions': [], 'terms': []})]
    async with _upkeep(tmp_path, replies) as (upkeep, store, memory, forks, bodies):
        upkeep.config.memory.ingest.max_steps = 1
        _group_messages(store)
        upkeep.request(SCENE, 'memory')
        assert await upkeep._step(SCENE)
        last = bodies()[1]['messages']
        assert last[-2]['content'] == '整理的工具次数用完了，这次没有执行。' and '工具次数用完了' in last[-1]['content']
        assert memory.jobs.latest(SCENE)['status'] == 'complete'


@pytest.mark.asyncio
async def test_the_worker_keeps_running_after_an_unexpected_error(tmp_path, monkeypatch):
    monkeypatch.setattr(upkeep_module, 'ERROR_BACKOFF_SECONDS', 0)
    async with _upkeep(tmp_path, [_text({'expressions': [], 'terms': []})]) as (upkeep, store, memory, forks, bodies):
        _group_messages(store)
        working = upkeep.fork
        calls = []
        recovered = asyncio.Event()

        def updated():
            if calls and SCENE not in upkeep.errors:
                recovered.set()

        async def flaky(scene):
            calls.append(scene)
            if len(calls) == 1:
                raise OSError('synthetic database hiccup')
            return await working(scene)
        upkeep.fork = flaky
        upkeep.on_update = updated
        upkeep.request(SCENE, 'memory')
        upkeep.start()
        try:
            # Memory completes before learning; wait for the worker's recovery notification.
            await asyncio.wait_for(recovered.wait(), timeout=3)
            assert upkeep.running(SCENE)
            assert memory.jobs.latest(SCENE)['status'] == 'complete'
            assert LearningStore(store).latest(SCENE)['status'] == 'complete'
            assert JargonStore(store).latest(SCENE)['status'] == 'complete'
        finally:
            await upkeep.close()
        assert len(calls) == 2 and SCENE not in upkeep.errors


@pytest.mark.asyncio
async def test_meaning_protocol_rejects_ordinary_usage_and_keeps_adopted_decisions(tmp_path):
    result = {'meanings': [
        {'term': '早餐', 'meaning': '早晨吃的一餐', 'ordinary_meaning': '早晨吃的一餐',
         'same_meaning': True, 'confidence': 0.99},
        {'term': '洗锅', 'meaning': '本群指清理构建缓存', 'ordinary_meaning': '清洗炊具',
         'same_meaning': False, 'confidence': 0.95},
        {'term': 'yyds', 'meaning': '模型返回的新解释', 'ordinary_meaning': '永远的神',
         'same_meaning': True, 'confidence': 0.9},
    ]}
    async with _upkeep(tmp_path, [_text(result)]) as (upkeep, store, memory, forks, bodies):
        records = JargonStore(store)
        proposals = []
        for index, term in enumerate(['早餐', '洗锅', 'yyds']):
            for repeat in range(4):
                ident = 52000 + index * 10 + repeat
                _receive(store, f'{term} 今天也提到一次', 70002, ident)
                if repeat == 0:
                    proposals.append((term, store.max_message_seq(SCENE)))
        call = records.begin_discovery(SCENE, 0, store.max_message_seq(SCENE), {})
        records.complete_discovery(call, proposals, exclude_uids=[])
        by_term = {item['term']: item for item in records.items(SCENE, None, 100, 0)['items']}
        adopted = records.update(SCENE, by_term['yyds']['id'], '人工固定含义', 'adopted')
        changed = asyncio.Event()
        upkeep.on_update = changed.set
        upkeep.start()
        try:
            upkeep.request(SCENE, 'jargon')
            async with asyncio.timeout(5):
                while records.pending(SCENE):
                    await changed.wait()
                    changed.clear()
        finally:
            await upkeep.close()
        ordinary = records.item(SCENE, by_term['早餐']['id'])
        special = records.item(SCENE, by_term['洗锅']['id'])
        assert (ordinary['status'], ordinary['latest_meaning']) == ('rejected', '早晨吃的一餐')
        assert (ordinary['ordinary_meaning'], ordinary['same_meaning']) == ('早晨吃的一餐', True)
        assert (special['status'], special['latest_meaning']) == ('pending', '本群指清理构建缓存')
        assert (special['ordinary_meaning'], special['same_meaning']) == ('清洗炊具', False)
        rejected = records.items(SCENE, 'rejected', 20, 0)['items']
        assert [(item['term'], item['same_meaning']) for item in rejected] == [('早餐', True)]
        # An adopted term keeps its decision and fixed meaning; only the latest inference changes.
        relearned = records.item(SCENE, adopted['id'])
        assert (relearned['status'], relearned['meaning']) == ('adopted', '人工固定含义')
        assert (relearned['latest_meaning'], relearned['same_meaning']) == ('模型返回的新解释', True)
        assert store.db.execute("SELECT count(*) FROM jargon_calls WHERE term_id=?", (adopted['id'],)).fetchone()[0] == 1
        assert len(bodies()) == 1
        raw = records.call(SCENE, records.latest(SCENE)['id'])
        assert 'ordinary_meaning' in str(raw) and 'same_meaning' in str(raw)


def test_adoption_during_meaning_request_preserves_manual_record(tmp_path):
    from len_bot.next.platform.onebot_messages import parse_message

    with Store(tmp_path / 'chat.db') as store:
        records = JargonStore(store)
        records.initialize(SCENE, 0)
        for index in range(4):
            raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
                   'user_id': 70002, 'message_id': f'usage-{index}', 'time': 1790000000,
                   'sender': {'nickname': '成员', 'role': 'member'},
                   'message': [{'type': 'text', 'data': {'text': '洗锅表示清缓存'}}]}
            store.enqueue(parse_message(raw, own_message_ids=set()), raw, 1790000000)
        discovery = records.begin_discovery(SCENE, 0, store.max_message_seq(SCENE), {})
        records.complete_discovery(discovery, [('洗锅', 1)], exclude_uids=[])
        term = records.pending(SCENE)[0]
        call = records.begin_meaning(SCENE, term['id'], term['count'], {})
        records.update(SCENE, term['id'], '人工确认：清缓存', 'adopted')
        records.complete_meaning(call, '异步返回的另一种解释', 0.7, ordinary_meaning='清洗炊具', same_meaning=True)
        item = records.item(SCENE, term['id'])
        assert (item['status'], item['meaning'], item['latest_meaning']) == ('adopted', '人工确认：清缓存', '异步返回的另一种解释')
        assert records.pending(SCENE) == []
        assert records.call(SCENE, call)['status'] == 'complete'
