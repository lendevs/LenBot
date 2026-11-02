"""An owner's first private message opens a private scene; other accounts' private messages stay out."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from len_bot.next.config import load_host_config
from test_attention_protocol import message, response
from test_host_stream import panel
from test_next_panel_acts_as_owner import SCENE

OWNER_CHAT = 'onebot:private:70001'


def private(user, ident, text):
    raw = message(user, ident, text)
    raw.pop('group_id')
    raw['message_type'] = 'private'
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [True, False])
async def test_an_owners_private_message_opens_a_private_chat_with_the_groups_role(tmp_path, enabled):
    peers, requests, sent = asyncio.Queue(), [], []

    async def model_peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.lower().split(':', 1) for line in header.split('\r\n')[1:] if ':' in line)
        requests.append(json.loads(await reader.readexactly(int(fields['content-length']))))
        _, content_type, body = response('say', {'content': '在的', 'end_turn': True}, f'call-{len(requests)}')
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
            else:
                sent.append((request['action'], request['params']))
                data = {'message_id': 1000 + len(sent)}
            await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'echo': request['echo'], 'data': data}))

    model = await asyncio.start_server(model_peer, '127.0.0.1', 0)
    async with model, serve(platform_peer, '127.0.0.1', 0) as platform:
        def configure(root):
            path = root / 'lenbot.config.json'
            source = json.loads(path.read_text())
            source['onebot'] = {'mode': 'forward_ws', 'ws_url': f'ws://127.0.0.1:{platform.sockets[0].getsockname()[1]}'}
            source['delivery'] = 'live'
            source['owner_private_chat'] = enabled
            source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{model.sockets[0].getsockname()[1]}/v1'
            source['models']['roles']['mind']['context_window_tokens'] = 64000
            source['compaction']['input_tokens'] = 30000
            source['scenes'][SCENE]['attention'] = {'activity': 0, 'direct_idle_seconds': 0}
            path.write_text(json.dumps(source))
            path = root / 'persona/persona.yaml'
            path.write_text(path.read_text().replace('tools: [tool_search, schedule, schedule_list, schedule_cancel]', 'tools: [say]'))

        async with panel(tmp_path, configure) as (runtime, client, url):
            running = asyncio.create_task(runtime.run(manage_signals=False))
            try:
                wire = await asyncio.wait_for(peers.get(), 3)
                async with asyncio.timeout(3):
                    while runtime.status != 'running':
                        await asyncio.sleep(.01)
                await wire.send(json.dumps(private(70002, 1, '陌生人私聊')))
                await wire.send(json.dumps(private(70001, 2, '在吗')))
                await wire.send(json.dumps(private(70001, 3, '问你个事')))
                if enabled:
                    async with asyncio.timeout(5):
                        while not any(action == 'send_private_msg' for action, _ in sent):
                            await asyncio.sleep(.01)
                    saved = load_host_config(tmp_path)
                    assert set(saved.scenes) == {SCENE, OWNER_CHAT}
                    assert saved.scenes[OWNER_CHAT].persona == saved.scenes[SCENE].persona
                    assert runtime.store.db.execute('SELECT COUNT(*) FROM messages WHERE scene=?',
                                                    (OWNER_CHAT,)).fetchone()[0] >= 2
                    assert [params['user_id'] for action, params in sent if action == 'send_private_msg'] == [70001]
                else:
                    await asyncio.sleep(.3)
                    assert set(load_host_config(tmp_path).scenes) == {SCENE}
                    assert requests == [] and sent == []
                assert 'onebot:private:70002' not in runtime.runners
            finally:
                runtime.stop()
                await asyncio.wait_for(running, 5)
