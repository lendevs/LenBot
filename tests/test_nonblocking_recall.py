"""Turn-start retrieval keeps local results and releases model slots on timeout."""

import asyncio
import json

import httpx
import pytest

from len_bot.next.learning.expression_selection import ExpressionService
from len_bot.next.learning.store import LearningStore
from len_bot.next.memory import embeddings
from len_bot.next.memory.embeddings import EmbeddingBinding, EmbeddingClient, EmbeddingSettings
from len_bot.next.memory.local import LocalMemorySettings
from len_bot.next.memory.service import LocalMemoryConfig, open_memory
from len_bot.next.models.slots import ModelSlots
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store
from test_native_tool_calls import SCENE, _instance


@pytest.fixture
def embedding_peer(monkeypatch):
    slow_models = set()
    cancelled_models = []
    slow_started = asyncio.Event()

    async def respond(request):
        body = json.loads(request.content)
        model = body['model']
        if model in slow_models:
            slow_started.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled_models.append(model)
                raise
        return httpx.Response(200, json={'data': [
            {'index': index, 'embedding': [1.0, 0.0]} for index, _ in enumerate(body['input'])
        ]})

    monkeypatch.setattr(embeddings, '_embedding_client', lambda _: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    return slow_models, cancelled_models, slow_started


def message(uid, text, *, card='', seq=1):
    return parse_message({
        'post_type': 'message', 'message_type': 'group', 'group_id': 80001,
        'user_id': uid, 'self_id': 90001, 'message_id': seq, 'time': 1791060000 + seq,
        'sender': {'nickname': f'成员{uid}', 'card': card, 'role': 'member'},
        'message': [{'type': 'text', 'data': {'text': text}}],
    }, own_message_ids=set())


@pytest.mark.asyncio
async def test_recall_keeps_target_profiles_and_literal_topic_during_vector_timeout(tmp_path, embedding_peer):
    slow_models, cancelled_models, _ = embedding_peer
    config, _ = _instance(tmp_path)
    config.memory = LocalMemoryConfig(backend='local', local=LocalMemorySettings(
        directory=tmp_path / 'memory', embedding=EmbeddingBinding(provider='synthetic', model='memory', dimensions=2)))
    slots = ModelSlots(1)

    with Store(config.database) as store:
        async with open_memory(config, store, slots=slots) as memory:
            for uid in range(70001, 70006):
                await memory.write(SCENE, f'people/onebot:{uid}/profile.md', f'# 成员 {uid}\n', '合成档案')
            for uid, nickname in [(70001, '阿青'), (70002, '老周')]:
                await memory.write(SCENE, f'people/onebot:{uid}/preferences.md',
                                   f'## 相处偏好\n喜欢被叫{nickname}。\n', '合成偏好')
            await memory.write(SCENE, 'events/camp.md', '植物园露营记得带双人帐篷。', '合成话题')
            slow_models.add('memory')

            for uid, card, expected, other in [(70001, '陈青山', '阿青', '老周'), (70002, '周文', '老周', '阿青')]:
                async with asyncio.timeout(0.4):
                    result = await memory.recall(SCENE, [message(uid, '早', card=card)], vector_timeout_seconds=0.1)
                assert [item['path'] for item in result['items']] == [
                    f'people/onebot:{uid}/profile.md', f'people/onebot:{uid}/preferences.md',
                ]
                content = '\n'.join(item['content'] for item in result['items'])
                assert f'喜欢被叫{expected}' in content
                assert other not in content

            batch = [message(70001, '早', card='陈青山')]
            batch.extend(message(uid, '今天天气真好', seq=uid - 70000) for uid in range(70002, 70006))
            result = await memory.recall(SCENE, batch, target_uids=['onebot:70001'], vector_timeout_seconds=0.1)
            assert result['items'][0]['path'] == 'people/onebot:70001/profile.md'
            assert [item['path'] for item in result['items'] if item['path'].endswith('/profile.md')] == [
                f'people/onebot:{uid}/profile.md' for uid in [70001, 70005, 70004, 70003]
            ]

            result = await memory.recall(SCENE, [message(70001, '植物园露营', card='陈青山')], vector_timeout_seconds=0.1)
            assert any(item['path'] == 'events/camp.md' and '双人帐篷' in item['content'] for item in result['items'])
            async with asyncio.timeout(0.1), slots.slot(scene=SCENE):
                assert cancelled_models == ['memory'] * 4


@pytest.mark.asyncio
async def test_recall_excludes_other_members_from_chat_and_cue_hits_during_vector_timeout(tmp_path, embedding_peer):
    slow_models, _, _ = embedding_peer
    config, _ = _instance(tmp_path)
    config.memory = LocalMemoryConfig(backend='local', local=LocalMemorySettings(
        directory=tmp_path / 'memory', embedding=EmbeddingBinding(provider='synthetic', model='memory', dimensions=2)))

    with Store(config.database) as store:
        async with open_memory(config, store) as memory:
            await memory.write(SCENE, 'people/onebot:70001/profile.md', '早安时喜欢被叫阿青。', '合成档案')
            await memory.write(SCENE, 'people/onebot:70001/preferences.md', '打招呼时喜欢被叫阿青。', '合成偏好')
            slow_models.add('memory')

            result = await memory.recall(SCENE, [message(70002, '早')], '打招呼', vector_timeout_seconds=0.1)

            assert result['items'] == []


@pytest.mark.asyncio
async def test_recall_reads_local_preferences_while_panel_search_is_waiting(tmp_path, embedding_peer):
    slow_models, _, slow_started = embedding_peer
    config, _ = _instance(tmp_path)
    config.memory = LocalMemoryConfig(backend='local', local=LocalMemorySettings(
        directory=tmp_path / 'memory', embedding=EmbeddingBinding(provider='synthetic', model='memory', dimensions=2)))

    with Store(config.database) as store:
        async with open_memory(config, store, slots=ModelSlots(1)) as memory:
            path = 'people/onebot:70002/preferences.md'
            await memory.write(SCENE, path, '喜欢被叫老周。', '合成偏好')
            slow_models.add('memory')
            panel_search = asyncio.create_task(memory.search(SCENE, '面板搜索', 5))
            try:
                await asyncio.wait_for(slow_started.wait(), timeout=0.4)
                async with asyncio.timeout(0.05):
                    result = await memory.recall(SCENE, [message(70002, '早')], vector_timeout_seconds=0.01)

                assert not panel_search.done()
                [preference] = result['items']
                assert preference['path'] == path and '喜欢被叫老周' in preference['content']
            finally:
                panel_search.cancel()
                await asyncio.gather(panel_search, return_exceptions=True)


@pytest.mark.asyncio
async def test_expression_timeout_settles_call_and_releases_scene_lock_and_model_slot(tmp_path, embedding_peer):
    slow_models, cancelled_models, _ = embedding_peer
    settings = EmbeddingSettings(provider='synthetic', model='expression', dimensions=2,
                                 base_url='http://embeddings.invalid/v1', api_key='synthetic')
    with Store(tmp_path / 'chat.sqlite3') as store:
        async with EmbeddingClient(settings) as client:
            service = ExpressionService(store, {SCENE: client}, slots=ModelSlots(1))
            records = LearningStore(store)
            records.initialize(SCENE, 0)
            batch = records.begin(SCENE, 0, 1, {})
            await service.complete(SCENE, batch, [('有人约去植物园露营', '走起走起', [])], auto_adopt=True)
            slow_models.add('expression')

            async with asyncio.timeout(0.4):
                with pytest.raises(TimeoutError):
                    await service.select(SCENE, '植物园露营', turn_id='slow', direct=True, timeout_seconds=0.1)

            call = records.embedding_calls(SCENE, limit=1, offset=0)['items'][0]
            assert call['turn_id'] == 'slow' and call['purpose'] == 'query'
            assert call['ended'] is not None and call['error'].startswith('CancelledError')
            assert cancelled_models == ['expression']

            slow_models.remove('expression')
            async with asyncio.timeout(0.1):
                selected = await service.select(SCENE, '植物园露营', turn_id='fast', direct=True)
            assert [item['style'] for item in selected] == ['走起走起']
