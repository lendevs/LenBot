"""Resends of one model request are counted in its call record; connection probes never resend."""

import json

import httpx
import pytest

from len_bot.next.configuration.models import Binding, Provider
from len_bot.next.models.client import ModelHTTPError
from len_bot.next.panel.app import create_app
from len_bot.next.panel.model_access import probe_model
from len_bot.next.platform.onebot_messages import parse_message
from test_next_host_manage_permissions_config import instance, running
from test_next_message_reaction import incoming
from test_next_model import recorded_response, recorded_text_response
from test_next_native_models import peer_server

SCENE = 'onebot:group:80001'


@pytest.mark.asyncio
async def test_turn_steps_show_how_often_a_request_was_resent(tmp_path):
    first = recorded_response()
    first['choices'][0]['message']['tool_calls'][0]['function'] = {'name': 'say', 'arguments': json.dumps({'content': '好'})}
    replies = [(503, 'application/json', b'{"error":"busy"}'),
               *[(200, 'application/json', json.dumps(body).encode()) for body in [first, recorded_text_response()]]]
    received = []
    server = await peer_server(replies, received)
    async with server:
        source = instance(tmp_path)
        source['compaction']['input_tokens'] = 6000
        source['models']['roles']['mind']['retry_delays_seconds'] = [0]
        source['models']['providers']['fixture']['base_url'] = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        (tmp_path / 'lenbot.config.json').write_text(json.dumps(source))
        async with running(tmp_path) as runtime:
            store, chat = runtime.store, runtime.chats[SCENE]
            raw = incoming()
            seq = store.enqueue(parse_message(raw, own_message_ids=set()), raw, store.now())

            async def append_new(called, turn):
                return False

            async def wait_for_messages(seconds):
                return '没有新消息'

            result = await chat.run_turn(batch=(seq, ['接个梗']), append_new=append_new,
                                         wait_for_messages=wait_for_messages, attention_state={})
            assert result['status'] == 'settled', result
            assert len(received) == 3 and received[0][2] == received[1][2]
            runtime.accepting = True
            app = create_app(runtime.config, runtime, root=tmp_path)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                login = await client.post('/api/auth/login', json={'username': 'operator', 'password': 'fixture-password'})
                assert login.status_code == 200
                detail = (await client.get(f"/api/host/scenes/{SCENE}/turns/{result['turn_id']}")).json()
            assert [model['retries'] for step in detail['steps'] for model in step['models']] == [1, 0]


@pytest.mark.asyncio
async def test_connection_probe_reports_the_first_failure_without_resending(tmp_path):
    received = []
    server = await peer_server([(502, 'application/json', b'{"error":"upstream"}'),
                                (200, 'application/json', json.dumps(recorded_text_response()).encode())], received)
    async with server:
        provider = Provider(api='openai-chat', base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
                            api_key='synthetic-secret')
        binding = Binding(provider='primary', model='fixture', context_window_tokens=8192, retry_delays_seconds=[2, 5])
        with pytest.raises(ModelHTTPError, match='502'):
            await probe_model(provider, binding, 'text')
    assert len(received) == 1
