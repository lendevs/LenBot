"""HTTP settings change live OneBot wake decisions and background model calls."""

import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from len_bot.next.chat.host_manage import HostManageArguments
from test_attention_protocol import message, response
from test_host_stream import login, panel, receive
from test_next_panel_acts_as_owner import SCENE


@pytest.mark.asyncio
async def test_settings_apply_to_wake_learning_permissions_and_preserve_cold_bindings(tmp_path):
    peers, requests = asyncio.Queue(), []

    async def model_peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.lower().split(':', 1) for line in header.split('\r\n')[1:] if ':' in line)
        request = json.loads(await reader.readexactly(int(fields['content-length'])))
        requests.append(request)
        if '<整理>' in str(request['messages'][-1]['content']):
            body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '{"expressions": []}'},
                                           'finish_reason': 'stop'}],
                               'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}).encode()
        else:
            _, _, body = response('say', {'content': '合成回答', 'end_turn': True}, f'call-{len(requests)}')
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def platform_peer(ws):
        await peers.put(ws)
        async for frame in ws:
            request = json.loads(frame)
            data = ({'user_id': 90001, 'nickname': '合成 Bot'} if request['action'] == 'get_login_info'
                    else {'message_id': 1000 + len(requests)})
            await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'echo': request['echo'], 'data': data}))

    model = await asyncio.start_server(model_peer, '127.0.0.1', 0)
    async with model, serve(platform_peer, '127.0.0.1', 0) as platform:
        def configure(root):
            path = root / 'lenbot.config.json'
            source = json.loads(path.read_text())
            source['onebot'] = {'mode': 'forward_ws', 'ws_url': f'ws://127.0.0.1:{platform.sockets[0].getsockname()[1]}'}
            source['delivery'] = 'onebot'
            source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{model.sockets[0].getsockname()[1]}/v1'
            source['models']['roles']['mind']['context_window_tokens'] = 64000
            source['compaction']['input_tokens'] = 30000
            source['scenes'][SCENE]['attention'] = {'only_direct': True, 'keywords': ['合成角色'],
                                                    'activity': 0, 'direct_idle_seconds': 0, 'named_idle_seconds': 0}
            path.write_text(json.dumps(source))
            path = root / 'persona/persona.yaml'
            path.write_text(path.read_text().replace('tools: [tool_search, schedule, schedule_list, schedule_cancel]', 'tools: [say]'))

        async with panel(tmp_path, configure) as (runtime, client, url):
            async with connect(url, additional_headers=await login(client), proxy=None) as ws:
                await receive(ws)
                running = asyncio.create_task(runtime.run(manage_signals=False))
                try:
                    wire = await asyncio.wait_for(peers.get(), 3)
                    async with asyncio.timeout(3):
                        while runtime.status != 'running':
                            await asyncio.sleep(.01)

                    async def incoming(ident, *, direct=False):
                        await wire.send(json.dumps(message(70001, ident, '合成角色，如何解释这件事？', direct=direct)))
                        while True:
                            event = await receive(ws)
                            if event['type'] == 'message.received' and event['message_seq'] == runtime.store.max_message_seq(SCENE):
                                return event['verdict']

                    async def ended():
                        while (await receive(ws))['type'] != 'turn.ended':
                            pass

                    assert (await incoming(1))['reason'] == '只回应直接联系'
                    assert requests == []
                    settings_url = f'/api/host/settings/scenes/{SCENE}'
                    saved = runtime.config.scenes[SCENE].model_dump(mode='json')
                    body = {key: saved[key] for key in ('timezone', 'voice_mode', 'attention', 'schedules', 'proactive',
                                                      'transcribe_audio', 'persona_aliases', 'relationships', 'behavior_addendum')}
                    body['schedules'] = {key: body['schedules'][key] for key in ('enabled', 'max_pending', 'autonomous')}
                    body['attention']['only_direct'] = False
                    updated = await client.put(settings_url, json=body)
                    assert updated.status_code == 200, updated.text
                    assert not updated.json()['restart_required']['scenes'][SCENE]
                    assert (await incoming(2))['channel'] == 'named'
                    await ended()
                    assert len(requests) == 1

                    now = datetime.now(timezone.utc)
                    body['attention']['quiet_hours'] = {'start': (now - timedelta(hours=1)).strftime('%H:%M'),
                                                        'end': (now + timedelta(hours=1)).strftime('%H:%M'), 'direct': 'defer'}
                    assert (await client.put(settings_url, json=body)).status_code == 200
                    assert not (await incoming(3, direct=True))['woke']
                    assert len(requests) == 1
                    body['attention']['quiet_hours'] = None
                    body['attention']['only_direct'] = True
                    assert (await client.put(settings_url, json=body)).status_code == 200
                    assert (await incoming(4, direct=True))['channel'] == 'direct'
                    await ended()

                    learning_url = settings_url + '/learning'
                    enabled = await client.put(learning_url, json={'learning': {'extract': True}})
                    assert enabled.status_code == 200, enabled.text
                    assert not enabled.json()['restart_required']
                    assert runtime.learning.state(SCENE)['running']
                    assert (await incoming(5))['reason'] == '只回应直接联系'
                    trigger = await client.post(f'/api/host/scenes/{SCENE}/learning/request')
                    assert trigger.status_code == 200, trigger.text
                    async with asyncio.timeout(3):
                        while (latest := runtime.learning.state(SCENE)['latest']) is None or latest['status'] == 'running':
                            await asyncio.sleep(.01)
                    assert latest['status'] == 'complete'
                    # The upkeep request continues the chat request: same tools, an instruction appended.
                    assert requests[-1]['tools'] == requests[-2]['tools']
                    chat = requests[-2]['messages'][:-1]
                    assert requests[-1]['messages'][:len(chat)] == chat
                    disabled = await client.put(learning_url, json={'learning': None})
                    assert disabled.status_code == 200 and not disabled.json()['restart_required']
                    assert SCENE not in runtime.learning.scenes

                    permissions_url = f'/api/host/permissions?scene={SCENE}'
                    permission = (await client.get(permissions_url)).json()['saved']
                    permission['global_identities']['admins'] = ['onebot:70002']
                    assert (await client.put(permissions_url, json=permission)).status_code == 200
                    status = HostManageArguments.model_validate({'action': 'status', 'requester': 'onebot:70002'})
                    assert (await runtime.management.execute(SCENE, status))['scenes'][0]['scene'] == SCENE
                    permission['global_identities']['admins'] = []
                    assert (await client.put(permissions_url, json=permission)).status_code == 200
                    with pytest.raises(PermissionError):
                        await runtime.management.execute(SCENE, status)

                    connection = (await client.get('/api/host/settings')).json()['saved']['connection']
                    connection.pop('bot_id')
                    connection['onebot'].pop('access_token_configured')
                    original_url = runtime.config.onebot.ws_url
                    connection['onebot']['ws_url'] = 'ws://127.0.0.1:9'
                    connection['access_token'] = 'synthetic-new-token'
                    connection['max_steps'] = 9
                    cold = await client.put('/api/host/settings/connection', json=connection)
                    assert cold.status_code == 200, cold.text
                    assert cold.json()['restart_required']['connection']
                    assert runtime.config.onebot.ws_url == original_url and runtime.platform.connected
                    assert runtime.chats[SCENE].config.max_steps == 9
                    pending = (await client.get('/api/host/pending-restart')).json()
                    assert pending['sections'] == ['onebot'] and pending['scenes'] == []
                finally:
                    runtime.stop()
                    await asyncio.wait_for(running, 3)
