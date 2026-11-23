"""The usage anchor of a chat request comes from the scene's last chat call, found by index, never for plugins."""
from contextlib import closing
import asyncio
import json
import sqlite3

import pytest

from len_bot.next.models.client import ChatModel
from len_bot.next.models.request import request_estimate, request_model
from len_bot.next.models.slots import ModelSlots
from len_bot.next.storage.schema import business_script
from len_bot.next.storage.store import Store
from test_next_model import recorded_text_response
from test_next_native_models import peer_server
from test_next_persona_permissions import _config, _package

LAST_MIND_USAGE = ("SELECT request,usage,error,ended FROM model_calls WHERE scene=? AND role='mind' "
                   "AND plugin IS NULL ORDER BY id DESC LIMIT 1")


@pytest.mark.asyncio
async def test_plugin_request_skips_the_chat_usage_anchor(tmp_path, monkeypatch):
    config = _config(tmp_path / 'instance', _package(tmp_path, 'plain', tools=[], documents={}))
    config.models.roles.mind.quick_reasoning_effort = 'low'
    body = json.dumps(recorded_text_response()).encode()
    server = await peer_server([(200, 'application/json', body)] * 3, [])
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            lookups = []
            original = store.last_mind_usage

            def counted(scene):
                lookups.append(scene)
                return original(scene)

            monkeypatch.setattr(store, 'last_mind_usage', counted)
            chat = [{'role': 'user', 'content': 'hello'}]
            async with ChatModel(config.model_settings('mind')) as model:
                first = await request_model(config, store, model, chat, [], scene=config.scene, role='mind',
                                            quick=True, output_tokens=128)
                await request_model(config, store, model, [{'role': 'user', 'content': 'hourly notes'}], [],
                                    scene=config.scene, role='mind', plugin='fixture')
                await request_model(config, store, model, [*chat, first.message, {'role': 'user', 'content': 'again'}],
                                    [], scene=config.scene, role='mind')
            records = list(store.db.execute('SELECT plugin, request FROM model_calls ORDER BY id'))
            plugins = [row['plugin'] for row in records]
            methods = [json.loads(row['request'])['estimate_method'] for row in records]
    assert plugins == [None, 'fixture', None]
    assert methods == ['utf8_bytes_estimate', 'utf8_bytes_estimate', 'usage_assisted']
    # Only the two chat requests look up the anchor; the plugin request in between does not.
    assert lookups == [config.scene, config.scene]


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('provider', 'other'), ('api', 'gemini'), ('model', 'other'),
                                         ('base_url', 'https://other.invalid'), ('history_policy', 'omit-reasoning')])
async def test_chat_usage_anchor_requires_same_encoding_binding(tmp_path, field, value):
    config = _config(tmp_path / 'instance', _package(tmp_path, 'plain', tools=[], documents={}))
    chat = [{'role': 'user', 'content': 'hello'}]
    async with ChatModel(config.model_settings('mind')) as model:
        request = {'settings': model.settings.model_dump(exclude={'api_key'}), 'messages': chat,
                   'tools': [], 'provider': 'synthetic', 'history_policy': 'native'}
        (request if field in {'provider', 'history_policy'} else request['settings'])[field] = value
        with Store(config.database) as store:
            call_id = store.start_scene_call(config.scene, 'mind', request)
            store.end_call(call_id, None, {'prompt_tokens': 100}, model=('synthetic', 'fixture'))
            _, method = request_estimate(config, store, model, scene=config.scene, role='mind',
                                         messages=chat, tools=[], output_tokens=100)
    assert method == 'utf8_bytes_estimate'


@pytest.mark.asyncio
async def test_chat_and_direct_upkeep_run_ahead_of_background_upkeep(tmp_path):
    config = _config(tmp_path / 'instance', _package(tmp_path, 'plain', tools=[], documents={}))
    body = json.dumps(recorded_text_response()).encode()
    received = []
    server = await peer_server([(200, 'application/json', body)] * 3, received)
    slots = ModelSlots(1)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                def call(role, direct=False):
                    return request_model(config, store, model, [{'role': 'user', 'content': f'{role}-{direct}'}], [],
                                         scene=config.scene, role=role, slots=slots, direct=direct)

                async with slots.slot():
                    queued = [asyncio.create_task(coro) for coro in
                              (call('upkeep'), call('mind'), call('upkeep', direct=True))]
                    await asyncio.sleep(0)
                await asyncio.gather(*queued)
    assert [payload['messages'][0]['content'] for _, _, payload in received] == ['upkeep-True', 'mind-False', 'upkeep-False']


def test_last_mind_usage_searches_its_index():
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(business_script())
        plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + LAST_MIND_USAGE, ('onebot:group:80001',))]
    assert any('USING INDEX model_call_mind_usage' in step for step in plan), plan
    assert not any(step.startswith('SCAN') or 'TEMP B-TREE' in step for step in plan), plan
