"""Provider edits at the configuration API boundary, with isolated instance data."""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
import httpx
import pytest
import pytest_asyncio

from len_bot.next.config import load_host_config
from len_bot.next.panel.routes.settings import register_host_settings
from len_bot.next.panel.setup import FirstSetup, initialize
from len_bot.next.persona.profile import load_persona
from len_bot.next.memory.local import LocalMemory
from len_bot.next.memory.embeddings import EmbeddingClient, EmbeddingSettings
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_next_native_models import peer_server

SCENE = 'onebot:group:80001'


@pytest_asyncio.fixture
async def instance(tmp_path: Path):
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-key'},
        'mind': {'provider': 'primary', 'model': 'synthetic-mind', 'context_window_tokens': 128000},
        'scene': SCENE, 'panel_port': 11307, 'username': 'fixture', 'password': 'synthetic-password',
    })))
    path = tmp_path / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['providers']['vectors'] = {
        'api': 'openai-embeddings', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-vector-key',
    }
    source['memory'] = {'backend': 'local', 'local': {'directory': 'memory',
                        'embedding': {'provider': 'vectors', 'model': 'synthetic-vector', 'dimensions': 4}}}
    source['scenes'][SCENE]['learning'] = {'extract': False,
        'embedding': {'provider': 'vectors', 'model': 'synthetic-vector', 'dimensions': 4}}
    path.write_text(json.dumps(source))
    config = load_host_config(tmp_path)
    persona = load_persona(config.scenes[SCENE].persona)
    app = FastAPI()

    def user(request: Request) -> str:
        return 'fixture'

    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
            runtime = NetworkRuntime(config, [(config.scene_config(SCENE), persona)], store, mind, memory=memory)
            register_host_settings(app, root=tmp_path, running=config, runtime=runtime, personas=lambda: {SCENE: persona},
                                   user=user, write_lock=asyncio.Lock())
            yield tmp_path, app


async def models_body(client) -> dict:
    models = (await client.get('/api/host/settings')).json()['saved']['models']
    return {'providers': {alias: {**{key: value for key, value in provider.items() if key != 'api_key_configured'},
                                 'previous_alias': alias, 'api_key': None} for alias, provider in models['providers'].items()},
            'roles': models['roles']}


@pytest.mark.asyncio
async def test_provider_rename_preserves_key_and_updates_vector_references(instance):
    root, app = instance
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        body = await models_body(client)
        body['providers']['renamed'] = body['providers'].pop('vectors')
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 200, response.text
        source = json.loads((root / 'lenbot.config.json').read_text())
        assert source['models']['providers']['renamed']['api_key'] == 'synthetic-vector-key'
        assert source['memory']['local']['embedding']['provider'] == 'renamed'
        assert source['scenes'][SCENE]['learning']['embedding']['provider'] == 'renamed'
        assert 'previous_alias' not in source['models']['providers']['renamed']
        body = await models_body(client)
        body['providers']['renamed']['base_url'] += '/'
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_provider_address_change_requires_new_key_without_writing_config(instance):
    root, app = instance
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        body = await models_body(client)
        body['providers']['vectors']['base_url'] = 'http://127.0.0.1:10/v1'
        before = (root / 'lenbot.config.json').read_bytes()
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 422 and '重新填写' in response.text
        assert (root / 'lenbot.config.json').read_bytes() == before


@pytest.mark.asyncio
async def test_model_applies_live_and_vector_bindings_wait_for_reindex(instance):
    root, app = instance
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        body = await models_body(client)
        body['roles']['mind']['model'] = 'new-mind'
        body['memory_embedding'] = {'provider': 'vectors', 'model': 'new-vector', 'dimensions': 8}
        body['learning_embeddings'] = {SCENE: {'provider': 'vectors', 'model': 'new-vector', 'dimensions': 8}}
        response = await client.put('/api/host/settings/models', json=body)
        restart = response.json()['restart_required']
        # The mind model applies at once; changed vector bindings wait for the stopped reindex.
        assert response.status_code == 200 and not restart['models'] and restart['memory'], response.text
        saved = load_host_config(root)
        assert saved.models.roles.mind.model == 'new-mind'
        assert saved.memory.local.embedding.model == 'new-vector'
        assert saved.scenes[SCENE].learning.embedding.dimensions == 8
        assert response.json()['running']['models']['roles']['mind']['model'] == 'new-mind'


@pytest.mark.asyncio
@pytest.mark.parametrize('api', ['openai-audio', 'anthropic', 'gemini'])
async def test_learning_vector_rejects_non_embedding_protocol_at_configuration_boundary(instance, api):
    root, app = instance
    source = json.loads((root / 'lenbot.config.json').read_text())
    source['models']['providers']['wrong'] = {'api': api, 'base_url': 'http://127.0.0.1:10/v1', 'api_key': 'synthetic-wrong-key'}
    (root / 'lenbot.config.json').write_text(json.dumps(source))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        before = (root / 'lenbot.config.json').read_bytes()
        response = await client.put(f'/api/host/settings/scenes/{SCENE}/learning', json={
            'learning': {'extract': False, 'embedding': {'provider': 'wrong', 'model': 'vector', 'dimensions': 4}},
        })
        assert response.status_code == 422 and 'openai-embeddings' in response.text
        assert (root / 'lenbot.config.json').read_bytes() == before


@pytest.mark.asyncio
async def test_rename_reuses_existing_vectors_and_address_change_reports_maintenance(instance):
    root, app = instance
    response = {'data': [{'index': 0, 'embedding': [1.0, 0.0, 0.0, 1.0]}], 'usage': {'prompt_tokens': 7, 'total_tokens': 7}}
    received = []
    server = await peer_server([(200, 'application/json', json.dumps(response).encode()) for _ in range(2)], received)
    async with server:
        url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        path = root / 'lenbot.config.json'
        source = json.loads(path.read_text())
        source['models']['providers']['vectors']['base_url'] = url
        path.write_text(json.dumps(source))
        settings = EmbeddingSettings(provider='vectors', base_url=url, model='synthetic-vector', dimensions=4,
                                     api_key='synthetic-vector-key')
        async with EmbeddingClient(settings) as embeddings:
            backend = LocalMemory(load_host_config(root).memory.local, embedding=embeddings)
            await backend.write(SCENE, 'arrangement.md', '活动安排在周五。', '明确的合成安排')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
            body = await models_body(client)
            body['providers']['renamed'] = body['providers'].pop('vectors')
            result = await client.put('/api/host/settings/models', json=body)
            assert result.status_code == 200, result.text
            pending = (await client.get('/api/host/pending-restart')).json()
            assert pending['maintenance'] == []
            async with EmbeddingClient(settings.model_copy(update={'provider': 'renamed'})) as embeddings:
                backend = LocalMemory(load_host_config(root).memory.local, embedding=embeddings)
                assert (await backend.search(SCENE, '活动安排'))[0].path == 'arrangement.md'
            body = await models_body(client)
            body['providers']['renamed'].update(base_url='http://127.0.0.1:10/v1', api_key='synthetic-new-key')
            result = await client.put('/api/host/settings/models', json=body)
            assert result.status_code == 200, result.text
            pending = (await client.get('/api/host/pending-restart')).json()
            assert pending['maintenance'][0]['command'] == 'python -m len_bot.next.maintenance.memory_reindex'
    assert len(received) == 2


@pytest.mark.asyncio
async def test_search_connection_rename_delete_and_independent_chat_binding(instance):
    root, app = instance
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        body = await models_body(client)
        body['providers']['search'] = {'api': 'deepseek-search', 'base_url': 'http://127.0.0.1:9/v1',
                                       'api_key': 'synthetic-search-key'}
        assert (await client.put('/api/host/settings/models', json=body)).status_code == 200
        response = await client.put('/api/host/settings/web-search', json={'web_search': {
            'provider': 'deepseek', 'connection': 'search'}})
        assert response.status_code == 200, response.text
        body = await models_body(client)
        body['providers']['renamed'] = body['providers'].pop('search')
        body['roles']['mind']['model'] = 'another-chat-model'
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 200, response.text
        source = json.loads((root / 'lenbot.config.json').read_text())
        assert source['web_search']['connection'] == 'renamed'
        assert source['models']['providers']['renamed']['api_key'] == 'synthetic-search-key'
        assert 'synthetic-search-key' not in response.text
        body = await models_body(client)
        del body['providers']['renamed']
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 422 and 'web_search.connection' in response.text
        assert json.loads((root / 'lenbot.config.json').read_text()) == source
        response = await client.put('/api/host/settings/web-search', json={'web_search': {
            'provider': 'deepseek', 'connection': 'missing'}})
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_web_read_connection_rename_updates_reference_without_422(instance):
    root, app = instance
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        body = await models_body(client)
        body['providers']['reader'] = {'api': 'jina-reader', 'base_url': 'http://127.0.0.1:9',
                                       'api_key': 'synthetic-reader-key'}
        assert (await client.put('/api/host/settings/models', json=body)).status_code == 200
        response = await client.put('/api/host/settings/web-read', json={'web_read': {
            'provider': 'jina', 'connection': 'reader'}})
        assert response.status_code == 200, response.text
        body = await models_body(client)
        body['providers']['reader_v2'] = body['providers'].pop('reader')
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 200, response.text
        source = json.loads((root / 'lenbot.config.json').read_text())
        assert source['web_read']['connection'] == 'reader_v2'
        assert source['models']['providers']['reader_v2']['api_key'] == 'synthetic-reader-key'
        body = await models_body(client)
        del body['providers']['reader_v2']
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 422 and 'web_read.connection' in response.text
        assert json.loads((root / 'lenbot.config.json').read_text()) == source


@pytest.mark.asyncio
async def test_turning_transcription_off_turns_it_off_in_every_group(instance):
    root, app = instance
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['providers']['speech'] = {'api': 'openai-audio', 'base_url': 'http://127.0.0.1:9/v1',
                                               'api_key': 'synthetic-speech-key'}
    source['models']['roles']['asr'] = {'api': 'openai-audio', 'provider': 'speech', 'model': 'synthetic-asr'}
    source['scenes'][SCENE]['transcribe_audio'] = True
    source['onebot']['max_frame_bytes'] = 32 * 1024 * 1024
    path.write_text(json.dumps(source))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        body = await models_body(client)
        body['roles']['asr'] = None
        result = await client.put('/api/host/settings/models', json=body)
        assert result.status_code == 200, result.text
    saved = json.loads(path.read_text())
    assert saved['models']['roles']['asr'] is None
    assert saved['scenes'][SCENE]['transcribe_audio'] is False


@pytest.mark.asyncio
async def test_anti_bagu_switch_applies_live_to_turn_tail_without_changing_prefix(instance):
    from len_bot.next.chat.context import turn_state

    root, app = instance
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        initial = (await client.get('/api/host/settings')).json()
        assert initial['saved']['models']['roles']['mind']['anti_bagu'] is False

        body = await models_body(client)
        body['roles']['mind']['model'] = 'deepseek-v4.1-flash'
        body['roles']['mind']['anti_bagu'] = True
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['restart_required']['models'] is False
        assert payload['running']['models']['roles']['mind']['anti_bagu'] is True

        saved = load_host_config(root)
        assert saved.models.roles.mind.anti_bagu is True
        persona = load_persona(saved.scenes[SCENE].persona)
        with Store(saved.database) as store:
            from len_bot.next.chat.context import ChatContext

            on_ctx = ChatContext(saved.scene_config(SCENE), persona, store, platform=False, memory=None)
            on_ctx.configure_tools([], [], skills=())
            state = turn_state(saved.scene_config(SCENE), store, now=1_700_000_000.0)
            on_messages = await on_ctx.project(None, [], state)
            assert '<去鱼八股与口语表达要求>' in on_messages[-1]['content']
            assert '<去鱼八股与口语表达要求>' not in on_messages[0]['content']

            off_cfg = saved.scene_config(SCENE)
            off_cfg.models.roles.mind.anti_bagu = False
            off_ctx = ChatContext(off_cfg, persona, store, platform=False, memory=None)
            off_ctx.configure_tools([], [], skills=())
            off_messages = await off_ctx.project(None, [], state)
            assert '<去鱼八股与口语表达要求>' not in off_messages[-1]['content']
            assert on_messages[:-1] == off_messages[:-1]
