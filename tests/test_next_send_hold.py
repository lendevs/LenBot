"""Host-wide send hold and the all-scene chat switch, without a platform connection."""

import json

import httpx
import pytest

from len_bot.next.panel.app import create_app
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.runtime.send_hold import SendHold
from test_next_host_manage_permissions_config import instance, running
from test_next_message_reaction import incoming
from test_next_model import recorded_response, recorded_text_response
from test_next_native_models import peer_server

SCENE = 'onebot:group:80001'


def test_hold_survives_restart_and_unreadable_file_counts_as_on(tmp_path):
    assert SendHold(tmp_path).enabled is False
    SendHold(tmp_path).set(True, at=1.0)
    assert SendHold(tmp_path).enabled is True
    SendHold(tmp_path).set(False, at=2.0)
    assert SendHold(tmp_path).enabled is False
    (tmp_path / 'state' / 'send-hold.json').write_text('{"enabled": "yes"}')
    assert SendHold(tmp_path).enabled is True


@pytest.mark.asyncio
async def test_held_turn_is_recorded_as_simulated_and_counts_speech(tmp_path):
    models = []
    first = recorded_response()
    first['choices'][0]['message']['tool_calls'][0]['function'] = {
        'name': 'say', 'arguments': json.dumps({'content': '第一段说得长一点点。第二段也要长一点点'})}
    server = await peer_server([(200, 'application/json', json.dumps(body).encode())
                                for body in [first, recorded_text_response()]], models)
    async with server:
        source = instance(tmp_path)
        source['delivery'] = 'onebot'
        source['compaction']['input_tokens'] = 6000
        source['text_delivery'] = {'max_chars': 10, 'min_interval_seconds': 0, 'max_interval_seconds': 0}
        source['models']['providers']['fixture']['base_url'] = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        (tmp_path / 'lenbot.config.json').write_text(json.dumps(source))
        async with running(tmp_path) as runtime:
            store, chat = runtime.store, runtime.chats[SCENE]
            runtime.send_hold.set(True, at=store.now())
            raw = incoming()
            seq = store.enqueue(parse_message(raw, own_message_ids=set()), raw, store.now())

            async def append_new(called, turn):
                return False

            async def wait_for_messages(seconds):
                return '没有新消息'

            # The OneBot transport is never started: any real send would fail instead of being simulated.
            result = await chat.run_turn(batch=(seq, ['接个梗']), append_new=append_new,
                                         wait_for_messages=wait_for_messages, attention_state={})
            assert result['status'] == 'settled', result
            own = [message for message in store.recent(SCENE, 20) if message.is_self]
            assert len(own) >= 2 and {message.send_status for message in own} == {'simulated'}
            turn = store.turn_detail(SCENE, result['turn_id'])['turn']
            assert turn['first_expression_delivery'] == 'simulated'
            assert store.db.execute('SELECT COUNT(*) FROM speech WHERE scene=?', (SCENE,)).fetchone()[0] == 1
            reaction = await runtime.platform_call('set_msg_emoji_like', {'message_id': 1, 'emoji_id': '66', 'set': True})
            assert reaction == {'status': 'ok', 'retcode': 0, 'data': None}
            upload = await runtime.upload_file(SCENE, 'file', 'name')
            assert upload.status == 'failed'


@pytest.mark.asyncio
async def test_panel_switches_all_scenes_and_send_hold(tmp_path):
    instance(tmp_path)
    async with running(tmp_path) as runtime:
        runtime.accepting = True
        app = create_app(runtime.config, runtime, root=tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            login = await client.post('/api/auth/login', json={'username': 'operator', 'password': 'fixture-password'})
            assert login.status_code == 200
            response = await client.put('/api/host/control/chat', json={'enabled': False})
            assert response.status_code == 200 and response.json() == {'enabled': False, 'scenes': 2}
            assert all(runner.state.paused for runner in runtime.runners.values())
            response = await client.put('/api/host/control/send-hold', json={'enabled': True})
            assert response.json() == {'enabled': True}
            state = (await client.get('/api/host/state')).json()
            assert state['send_hold'] is True and not any(item['chat_enabled'] for item in state['scenes'])
            await client.put('/api/host/control/chat', json={'enabled': True})
            assert not any(runner.state.paused for runner in runtime.runners.values())
        assert SendHold(tmp_path).enabled is True
