"""Direct reserve across model tool calls and OneBot send receipts; loopback services only."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.session import Chat
from len_bot.next.configuration.onebot import OneBotForward
from len_bot.next.models.client import ChatModel
from len_bot.next.models.limits import record_speech, speech_quota
from len_bot.next.platform.onebot import OneBot
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message, response
from test_native_tool_calls import _instance


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['failed', 'second-at', 'answered'])
async def test_direct_reserve_tracks_delivery_since_the_latest_direct_input(tmp_path, case):
    config, persona = _instance(tmp_path)
    persona.tools = ['say', 'wait']
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    config.attention.direct_idle_seconds = config.attention.focus_idle_seconds = 0
    config.limits.messages_per_hour, config.limits.direct_reserve = 1, 3
    requests, receipts, events = [], [], []
    inputs = {ident: asyncio.Event() for ident in (102, 103)}
    platform = []

    def receive(raw):
        runner.receive(raw)
        inputs[raw['message_id']].set()

    async def onebot_peer(websocket):
        platform.append(websocket)
        async for frame in websocket:
            request = json.loads(frame)
            result = {'status': 'ok', 'retcode': 0, 'echo': request['echo']}
            if request['action'] == 'get_login_info':
                result['data'] = {'user_id': 90001, 'nickname': '合成 Bot'}
            else:
                assert request['action'] == 'send_group_msg'
                failed = case == 'failed' and not receipts
                receipts.append('failed' if failed else 'sent')
                if len(receipts) == 1:
                    await websocket.send(json.dumps(message(70002, 102, '第二个问题' if case == 'second-at' else '无关闲聊',
                                                            direct=case == 'second-at')))
                    await inputs[102].wait()
                if failed:
                    result.update(status='failed', retcode=100, data=None, message='合成发送失败')
                else:
                    result['data'] = {'message_id': 1000 + len(receipts)}
            await websocket.send(json.dumps(result))

    async def model_peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.lower().split(':', 1) for line in header.split('\r\n')[1:] if ':' in line)
        requests.append(json.loads(await reader.readexactly(int(fields['content-length']))))
        number = len(requests)
        if case == 'second-at' and number == 2:
            # The new @ has been consumed, but its answer has not been sent yet.
            await platform[0].send(json.dumps(message(70003, 103, '无关闲聊')))
            await inputs[103].wait()
            _, content_type, body = response('wait', {'seconds': 0, 'reason': '处理第二个问题'}, 'call2')
        else:
            _, content_type, body = response('say', {'content': '合成回答', 'end_turn': number > 1}, f'call{number}')
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    model_server = await asyncio.start_server(model_peer, '127.0.0.1', 0)
    async with model_server, serve(onebot_peer, '127.0.0.1', 0) as wire_server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{model_server.sockets[0].getsockname()[1]}/v1'
        config.onebot = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{wire_server.sockets[0].getsockname()[1]}')
        config.delivery = 'onebot'
        with Store(config.database, now=lambda: START) as store:
            record_speech(store, config.scene)  # Normal allowance is exhausted; direct reserve remains.
            async with ChatModel(config.model_settings('mind')) as model, OneBot(
                config.onebot, bot_id=config.bot_id, on_event=receive, on_error=lambda _: None,
            ) as bot:
                chat = Chat(config, persona, store, model, send_message=bot.send_message, now=lambda: START)
                runner = SceneRunner(chat, events.append)
                runner.receive(message(70001, 101, '第一个问题', direct=True))
                runner.close_input()
                await asyncio.wait_for(runner.run(), timeout=5)
            expected = {
                'failed': ('settled', 2, ['failed', 'sent'], 2),
                'second-at': ('settled', 3, ['sent', 'sent'], 1),
                'answered': ('limited', 1, ['sent'], 2),
            }[case]
            assert (events[-1]['status'], len(requests), receipts, speech_quota(store, config).reserve_left) == expected
            own = [item for item in store.recent(config.scene, 20) if item.is_self]
            assert sum(item.send_status == 'sent' for item in own) == receipts.count('sent')
