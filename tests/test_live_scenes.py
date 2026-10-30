"""Add/remove scenes over HTTP while real local OneBot and model peers keep running."""

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from test_attention_protocol import message, response
from test_host_stream import login, panel, receive
from test_next_panel_acts_as_owner import SCENE

NEW = 'onebot:group:80002'


@pytest.mark.asyncio
async def test_live_scene_add_remove_drains_current_turn_without_stopping_other_scenes(tmp_path):
    peers, requests = asyncio.Queue(), []
    first_request, release_first = asyncio.Event(), asyncio.Event()
    sent = []

    async def model_peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.lower().split(':', 1) for line in header.split('\r\n')[1:] if ':' in line)
        requests.append(json.loads(await reader.readexactly(int(fields['content-length']))))
        if len(requests) == 1:
            first_request.set()
            await release_first.wait()
        _, content_type, body = response('say', {'content': '合成回答', 'end_turn': True}, f'call-{len(requests)}')
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def platform_peer(ws):
        await peers.put(ws)
        async for frame in ws:
            request = json.loads(frame)
            if request['action'] == 'get_login_info':
                data = {'user_id': 90001, 'nickname': '合成 Bot'}
            elif request['action'] == 'get_group_list':
                data = [{'group_id': 80001, 'group_name': '原有群', 'member_count': 10},
                        {'group_id': 80002, 'group_name': '待接入群', 'member_count': 20}]
            else:
                assert request['action'] == 'send_group_msg'
                sent.append(request['params'])
                data = {'message_id': 1000 + len(sent)}
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
            source['models']['roles']['memory'] = dict(source['models']['roles']['mind'])
            source['memory'] = {'backend': 'local', 'local': {'directory': 'memory'}, 'ingest': {}}
            source['compaction']['input_tokens'] = 30000
            source['scenes'][SCENE]['attention'] = {'activity': 0, 'direct_idle_seconds': 0}
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
                    endpoint = '/api/host/settings/scenes'
                    available = await client.get(endpoint + '/available')
                    assert available.json()['items'][0]['scene'] == NEW
                    added = await client.post(endpoint, json={'scene': NEW, 'persona': 'persona',
                                                              'attention': {'only_direct': False, 'activity': 0.5}})
                    assert added.status_code == 200, added.text
                    attention = runtime.chats[NEW].config.attention
                    assert (attention.only_direct, attention.activity) == (False, 0.5)
                    assert not added.json()['restart_required']['scenes'][NEW]
                    assert NEW in runtime.ingestor.scenes
                    incoming = message(70001, 1, '新群请求', direct=True)
                    incoming['group_id'] = 80002
                    await wire.send(json.dumps(incoming))
                    await asyncio.wait_for(first_request.wait(), 3)
                    removing = asyncio.create_task(client.delete(endpoint + '/' + NEW))
                    async with asyncio.timeout(3):
                        while NEW not in runtime.scene_service.retiring:
                            await asyncio.sleep(.01)
                    assert not removing.done()
                    late = message(70001, 2, '移除中不再接收', direct=True)
                    late['group_id'] = 80002
                    await wire.send(json.dumps(late))
                    await wire.send(json.dumps(message(70001, 3, '原有群继续', direct=True)))
                    while True:
                        event = await receive(ws)
                        if event['type'] == 'turn.ended' and event['scene'] == SCENE:
                            break
                    assert not removing.done() and len(requests) == 2
                    release_first.set()
                    removed = await asyncio.wait_for(removing, 3)
                    assert removed.status_code == 200, removed.text
                    assert NEW not in runtime.runners and runtime.status == 'running'
                    assert NEW not in runtime.ingestor.scenes and SCENE in runtime.ingestor.scenes
                    assert runtime.store.db.execute('SELECT COUNT(*) FROM messages WHERE scene=?', (NEW,)).fetchone()[0] == 2
                    late['message_id'] = 4
                    await wire.send(json.dumps(late))
                    while True:
                        event = await receive(ws)
                        if (event['type'] == 'receipt' and event['scene'] == NEW and event['status'] == 'ignored'
                                and event['platform_message_id'] == '4'):
                            break
                    assert len(requests) == 2
                    available = (await client.get(endpoint + '/available')).json()['items']
                    assert available[0]['scene'] == NEW
                    assert (await client.post(endpoint, json={'scene': NEW, 'persona': 'persona'})).status_code == 200
                    assert NEW in runtime.runners
                    assert NEW in runtime.ingestor.scenes
                    assert (await client.delete(endpoint + '/' + NEW)).status_code == 200
                    assert (await client.delete(endpoint + '/' + SCENE)).status_code == 200
                    assert runtime.runners == {} and runtime.status == 'running' and runtime.platform.connected
                    assert len((await client.get(endpoint + '/available')).json()['items']) == 2
                finally:
                    release_first.set()
                    runtime.stop()
                    await asyncio.wait_for(running, 3)
