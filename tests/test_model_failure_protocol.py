"""Provider failures, recap budgets and explicit thinking options at the HTTP boundary."""
import json
import logging
from pathlib import Path

import httpx
import pytest

from len_bot.next.chat.session import Chat
from len_bot.next.config import load_host_config
from len_bot.next.models.client import (ChatModel, ModelConnectionError, ModelHTTPError, ModelOutputLimitError,
                                        ModelSettings)
from len_bot.next.models.providers import list_models
from len_bot.next.configuration.models import Provider
from len_bot.next.models.request import request_model
from len_bot.next.persona.profile import load_persona
from len_bot.next.storage.store import Store
from test_next_panel_acts_as_owner import SCENE, exercise, write_instance

FIXTURE = Path(__file__).parent / 'fixtures/next/model/response-text.json'


def instance(root, *, output=8192, compaction=None, thinking=None):
    write_instance(root, ['onebot:70001'])
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['roles']['mind'].update(max_output_tokens=output, context_window_tokens=100000,
                                            reasoning_effort='high', quick_reasoning_effort='low', thinking=thinking)
    source['compaction'] = {'input_tokens': 60000, 'keep_recent_tokens': 100, 'max_output_tokens': compaction}
    path.write_text(json.dumps(source))
    return load_host_config(root)


@pytest.mark.asyncio
@pytest.mark.parametrize('thinking', [None, 'enabled', 'disabled'])
async def test_explicit_thinking_wire_values(thinking):
    body = json.loads(FIXTURE.read_text())
    def respond(request):
        payload = json.loads(request.content)
        if thinking is None:
            assert 'thinking' not in payload
        else:
            assert payload['thinking'] == {'type': thinking}
        return httpx.Response(200, json=body)
    settings = ModelSettings(api='openai-chat', base_url='https://fixture.invalid/v1',
                             api_key='fixture', model='any-model', thinking=thinking)
    async with ChatModel(settings) as model:
        await model._client.aclose()
        model._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url=settings.base_url + '/')
        await model.complete([{'role': 'user', 'content': '连接测试'}], [])


@pytest.mark.asyncio
@pytest.mark.parametrize('output,override,thinking,expected,budget', [
    (8192, None, None, 8192, 4096),
    (8192, 4096, 'enabled', 4096, 2048),
    (4096, None, 'disabled', 4096, 4096),
])
async def test_manual_recap_uses_effective_allowance_and_quick_effort(tmp_path, output, override, thinking, expected, budget):
    config = instance(tmp_path, output=output, compaction=override, thinking=thinking)
    captured = []
    body = json.loads(FIXTURE.read_text())
    body['choices'][0]['message']['content'] = '大家约好明天讨论报告。'
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=body)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as model:
            await model._client.aclose()
            model._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='https://fixture.invalid/')
            chat = Chat(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona), store, model)
            for content in ['明天讨论报告。' * 100, '报告主题是连接恢复。' * 100, '好的。']:
                store.append(SCENE, {'role': 'user', 'content': content})
            result = await chat.compact_now()
            assert result['recap'] == body['choices'][0]['message']['content']
            call = store.db.execute("SELECT request FROM model_calls WHERE role='recap'").fetchone()
            assert json.loads(call[0])['settings']['reasoning_effort'] == 'low'
    assert len(captured) == 1
    assert captured[0]['max_completion_tokens'] == expected
    assert captured[0]['reasoning_effort'] == 'low'
    assert f'{budget} token' in captured[0]['messages'][0]['content']


@pytest.mark.parametrize('status,hint', [(401, 'API Key'), (429, '额度'), (502, '服务商或中转')])
def test_provider_failures_in_logs_overview_and_call_detail(tmp_path, caplog, status, hint):
    config = instance(tmp_path)
    caplog.set_level(logging.WARNING)
    raw = {'error': {'message': 'all service attempts failed (request id: fixture-request-42)'}}
    async def fail_twice():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                await model._client.aclose()
                model._client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(status, json=raw)), base_url='https://fixture.invalid/')
                for _ in range(2):
                    with pytest.raises(ModelHTTPError, match=hint):
                        await request_model(config, store, model, [{'role': 'user', 'content': '测试'}], [],
                                            scene=SCENE, role='mind')
                await model._client.aclose()
                model._client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=json.loads(FIXTURE.read_text()))),
                    base_url='https://fixture.invalid/')
                await request_model(config, store, model, [{'role': 'user', 'content': '测试'}], [],
                                    scene=SCENE, role='recap')
    import asyncio
    asyncio.run(fail_twice())
    assert hint in caplog.text and 'fixture-request-42' in caplog.text
    async def check(client):
        overview = (await client.get('/api/host/overview')).json()
        assert len(overview['model_errors']) == 1
        error = overview['model_errors'][0]
        assert error['count'] == 2 and hint in error['error']
        health = {item['purpose']: item for item in overview['model_health']}
        assert set(health) == {'mind', 'recap'}
        assert health['mind']['success'] is None
        assert health['mind']['failure']['id'] == error['id'] and hint in health['mind']['failure']['error']
        assert health['mind']['failure']['provider'] == 'local'
        assert health['recap']['failure'] is None and health['recap']['success']['scene'] == SCENE
        result = await client.get(f"/api/host/model-calls/{error['id']}")
        assert result.status_code == 200
        assert result.json()['response']['request_id'] == 'fixture-request-42'
        assert json.loads(result.json()['response']['detail']) == raw
        assert (await client.get('/api/host/model-calls/9999')).status_code == 404
        await client.post('/api/auth/logout')
        assert (await client.get(f"/api/host/model-calls/{error['id']}")).status_code == 401
    exercise(tmp_path, check)


@pytest.mark.parametrize('status,body,expected', [
    (404, {'error': {'message': 'The model `gpt-x` does not exist', 'code': 'model_not_found'}}, '模型名或接口地址不存在'),
    (400, {'error': {'message': 'Model Not Exist', 'type': 'invalid_request_error'}}, '模型名或接口地址不存在'),
    (400, {'error': {'message': 'temperature must be at most 2'}}, '核对模型参数'),
    (403, {'error': {'message': 'model_not_found for this key'}}, 'API Key'),
    (400, {'error': {'message': "This model's maximum context length is 65536 tokens", 'code': 'context_length_exceeded'}},
     '上下文长度'),
    (400, {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'prompt is too long: 210000 tokens > 200000 maximum'}},
     '上下文长度'),
])
def test_missing_model_and_context_overflow_are_named_apart(status, body, expected):
    error = ModelHTTPError(status, json.dumps(body))
    assert expected in str(error) and f'HTTP {status}' in str(error)


def fixture_settings(**changes):
    return ModelSettings(api='openai-chat', base_url='https://fixture.invalid/v1', api_key='fixture-key',
                         model='any-model', **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,expected', [
    (httpx.ConnectError('[Errno 61] Connection refused'), '无法连接服务商地址'),
    (httpx.ProxyError('407 Proxy Authentication Required'), '代理连接失败'),
    (httpx.ReadTimeout('timed out'), '响应超时'),
])
async def test_unreachable_provider_names_address_after_retries(failure, expected):
    attempts = []
    def respond(request):
        attempts.append(request)
        raise failure
    settings = fixture_settings(retry_delays_seconds=[0.01])
    async with ChatModel(settings) as model:
        await model._client.aclose()
        model._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url=settings.base_url + '/')
        with pytest.raises(ModelConnectionError, match=expected) as caught:
            await model.complete([{'role': 'user', 'content': '连接测试'}], [])
    assert len(attempts) == 2
    assert 'https://fixture.invalid/v1' in str(caught.value) and type(failure).__name__ in str(caught.value)


@pytest.mark.asyncio
async def test_model_deadline_keeps_timeout_type_and_says_what_to_change():
    import asyncio
    async def respond(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})
    settings = fixture_settings(timeout_seconds=0.05)
    async with ChatModel(settings) as model:
        await model._client.aclose()
        model._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url=settings.base_url + '/')
        with pytest.raises(TimeoutError, match='超过 0.05 秒未完成.*调大超时'):
            await model.complete([{'role': 'user', 'content': '连接测试'}], [])


@pytest.mark.asyncio
async def test_model_list_reports_unreachable_address(monkeypatch):
    def respond(request):
        raise httpx.ConnectError('[Errno 8] nodename nor servname provided')
    from len_bot.next.models import providers
    original = providers.http_client
    def client(**options):
        made = original(**options)
        made._transport = httpx.MockTransport(respond)
        return made
    monkeypatch.setattr(providers, 'http_client', client)
    provider = Provider(api='openai-chat', base_url='https://fixture.invalid/v1', api_key='fixture-key')
    with pytest.raises(ModelConnectionError, match='无法连接服务商地址'):
        await list_models(provider)


@pytest.mark.asyncio
@pytest.mark.parametrize('role,entry', [('mind', '最长输出'), ('recap', '回想最大长度')])
async def test_output_limit_retains_usage_and_purpose(tmp_path, caplog, role, entry):
    config = instance(tmp_path)
    body = json.loads(FIXTURE.read_text())
    body['choices'][0]['finish_reason'] = 'length'
    body['choices'][0]['message']['content'] = ''
    caplog.set_level(logging.WARNING)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as model:
            await model._client.aclose()
            model._client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body)), base_url='https://fixture.invalid/')
            with pytest.raises(ModelOutputLimitError, match=entry) as failure:
                await request_model(config, store, model, [{'role': 'user', 'content': '测试'}], [],
                                    scene=SCENE, role=role, output_tokens=2048)
        assert '2048' in str(failure.value)
        assert str(body['usage']['completion_tokens']) in str(failure.value)
        call_id = store.model_errors([SCENE], 0, 1e20)[0]['id']
        detail = store.model_call(call_id)
        assert detail['response'] == body and detail['usage'] == body['usage']
        assert entry in detail['error'] and entry in caplog.text
