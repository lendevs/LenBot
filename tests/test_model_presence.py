"""Staying present through provider failures: recap allowance, owner alerts and catching up, at the HTTP boundary."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from len_bot.next.chat.attention import CATCH_UP_SECONDS, SceneRunner
from len_bot.next.chat.session import Chat
from len_bot.next.models.client import ChatModel
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message, response, talking_instance
from test_host_stream import panel
from test_model_failure_protocol import instance
from test_next_native_models import peer_server
from test_next_panel_acts_as_owner import SCENE

LIMITED = (429, 'application/json', json.dumps({'error': {'message': 'rate limited, provider cooling down'}}).encode())


def text(request) -> str:
    return json.dumps(request[2]['messages'], ensure_ascii=False)


def cut_short(content='回想写了一半'):
    body = {'choices': [{'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'length'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 8192}}
    return 200, 'application/json', json.dumps(body).encode()


@pytest.mark.asyncio
async def test_recap_thinks_at_its_own_effort_and_reserves_by_it(tmp_path):
    config = instance(tmp_path)
    assert config.recap_reasoning_effort == 'low' and config.recap_reasoning_reserve == 4096
    path = tmp_path / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['compaction']['reasoning_effort'] = 'none'
    path.write_text(json.dumps(source))
    from len_bot.next.config import load_host_config
    config = load_host_config(tmp_path)
    # Without thinking the whole allowance is left for the recap text.
    assert config.recap_reasoning_effort == 'none' and config.recap_reasoning_reserve == 0
    body = {'choices': [{'message': {'role': 'assistant', 'content': '大家约好明天讨论报告。'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
    requests = []
    server = await peer_server([(200, 'application/json', json.dumps(body).encode())], requests)
    async with server:
        config.models.providers['local'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        from len_bot.next.persona.profile import load_persona
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                chat = Chat(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona), store, model)
                for content in ['明天讨论报告。' * 100, '好的。']:
                    store.append(SCENE, {'role': 'user', 'content': content})
                await chat.compact_now()
    assert len(requests) == 1
    assert requests[0][2]['reasoning_effort'] == 'none'
    assert '8192 token' in requests[0][2]['messages'][-1]['content']


@pytest.mark.asyncio
async def test_a_recap_out_of_allowance_keeps_the_old_recap_and_the_turn_goes_on(tmp_path):
    config, persona, replies = talking_instance(tmp_path, 2)
    config.compaction.keep_recent_tokens = 2000
    replies.insert(0, cut_short())
    requests, events, now = [], [], [START]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            for _ in range(12):
                store.append(SCENE, {'role': 'user', 'content': '明天讨论报告。' * 300})
            async with ChatModel(config.model_settings('mind')) as model:
                live = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), events.append)
                live.closing = True
                live.receive(message(70001, 1, '在吗', direct=True))
                await asyncio.wait_for(live.run(), 5)
                assert store.recap(SCENE) is None
                recap = store.db.execute("SELECT error FROM model_calls WHERE role='recap'").fetchall()
                assert len(recap) == 1 and '回想输出额度用完' in recap[0][0]
                now[0] += 60
                live.receive(message(70001, 2, '还在吗', direct=True))
                await asyncio.wait_for(live.run(), 5)
    turns = [event for event in events if 'turn_id' in event]
    assert [turn['status'] for turn in turns] == ['settled', 'settled']
    assert all(turn['expressions'] for turn in turns)
    # The second turn does not pay for the same failing recap again.
    assert len(requests) == 3 and '<回想整理>' not in text(requests[2])


@pytest.mark.asyncio
async def test_after_failed_turns_joining_in_looks_only_at_recent_chat(tmp_path):
    config, persona, replies = talking_instance(tmp_path, 1)
    replies.insert(0, LIMITED)
    requests, events, now = [], [], [START]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                live = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), events.append)
                live.closing = True
                live.receive(message(70001, 1, '你们觉得怎么办？'))
                await asyncio.wait_for(live.run(), 5)
                assert events[-1]['status'] == 'error' and events[-1]['model_failure']['kind'] == 'HTTP 429'
                now[0] += 10
                live.receive(message(70002, 2, '昨晚那场比赛谁赢了'))
                live.receive(message(70003, 3, '@机器人 帮我记一下周会改到周三', direct=False))
                # The interjection comes due long after these messages: old chat alone opens no turn.
                now[0] += 3 * 3600
                await asyncio.wait_for(live.run(), 5)
                assert len(requests) == 1 and live.state.pending is None
                now[0] += 5
                live.receive(message(70004, 4, '今晚有人一起打游戏吗'))
                await asyncio.wait_for(live.run(), 5)
                assert events[-1]['status'] == 'settled'
                assert live.behind_since is None
    assert len(requests) == 2
    batches = [item['content'] for item in requests[1][2]['messages'] if item['role'] == 'user'
               and isinstance(item['content'], str) and '较早的消息' in item['content']]
    assert len(batches) == 1 and '昨晚那场比赛谁赢了' in batches[0] and '今晚有人一起打游戏吗' not in batches[0]
    recent = text(requests[1])
    assert recent.index('今晚有人一起打游戏吗') > recent.index('较早的消息')
    assert CATCH_UP_SECONDS == 300


@pytest.mark.asyncio
async def test_input_left_from_before_a_restart_is_old_chat(tmp_path):
    config, persona, replies = talking_instance(tmp_path, 1)
    requests, now = [], [START]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), lambda _: None).receive(
                    message(70001, 1, '你们觉得怎么办？'))
                now[0] += 2 * 3600
                live = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), lambda _: None)
                live.closing = True
                assert live.behind_since == START
                await asyncio.wait_for(live.run(), 5)
                assert requests == [] and live.state.pending is None
                live.receive(message(70002, 2, '有人吗', direct=True))
                await asyncio.wait_for(live.run(), 5)
    assert len(requests) == 1
    content = text(requests[0])
    assert '较早的消息' in content and content.index('你们觉得怎么办') < content.index('有人吗')


@pytest.mark.asyncio
@pytest.mark.parametrize(('failure', 'threshold'), [('limited', None), ('slow', 2)])
async def test_owners_hear_once_when_turns_keep_failing_and_once_when_they_recover(tmp_path, failure, threshold):
    # The default threshold with HTTP 429; a configured one with requests that run past the model's timeout.
    peers, requests, sent = asyncio.Queue(), [], []
    turns = threshold or 3
    failing = [turns]

    async def model_peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.lower().split(':', 1) for line in header.split('\r\n')[1:] if ':' in line)
        requests.append(json.loads(await reader.readexactly(int(fields['content-length']))))
        if failing[0]:
            failing[0] -= 1
            if failure == 'slow':
                await asyncio.sleep(1)
            status, reason, content_type, body = 429, 'Too Many Requests', LIMITED[1], LIMITED[2]
        else:
            _, content_type, body = response('say', {'content': '回来了', 'end_turn': True}, f'call-{len(requests)}')
            status, reason = 200, 'OK'
        writer.write(f'HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\n'
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
            source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{model.sockets[0].getsockname()[1]}/v1'
            source['models']['roles']['mind']['context_window_tokens'] = 64000
            source['compaction']['input_tokens'] = 30000
            source['scenes'][SCENE]['attention'] = {'direct_idle_seconds': 0, 'speech_interval_seconds': 0}
            if threshold is not None:
                source['model_alert_failed_turns'] = threshold
            if failure == 'slow':
                source['models']['roles']['mind']['timeout_seconds'] = 0.2
            path.write_text(json.dumps(source))
            path = root / 'persona/persona.yaml'
            path.write_text(path.read_text().replace('tools: [tool_search, schedule, schedule_list, schedule_cancel]', 'tools: [say]'))

        def private_sends():
            return [params for action, params in sent if action == 'send_private_msg']

        async with panel(tmp_path, configure) as (runtime, client, url):
            running = asyncio.create_task(runtime.run(manage_signals=False))
            try:
                wire = await asyncio.wait_for(peers.get(), 3)
                async with asyncio.timeout(3):
                    while runtime.status != 'running':
                        await asyncio.sleep(.01)
                for index in range(1, turns + 2):
                    await wire.send(json.dumps(message(70002, index, f'第{index}次叫你', direct=True)))
                    async with asyncio.timeout(5):
                        while runtime.store.db.execute(
                                'SELECT COUNT(*) FROM turns WHERE ended IS NOT NULL').fetchone()[0] < index:
                            await asyncio.sleep(.01)
                    if index == turns - 1:
                        assert private_sends() == []
                async with asyncio.timeout(5):
                    while len(private_sends()) < 2:
                        await asyncio.sleep(.01)
                await asyncio.sleep(.2)
            finally:
                runtime.stop()
                await asyncio.wait_for(running, 5)
    alerts = private_sends()
    assert [params['user_id'] for params in alerts] == [70001, 70001]
    failed, recovered = (''.join(segment['data']['text'] for segment in params['message']) for params in alerts)
    assert f'连续 {turns} 个回合失败' in failed and '最早失败时间' in failed
    assert ('HTTP 429' if failure == 'limited' else '请求超时') in failed
    assert '已恢复' in recovered
    assert len(requests) == turns + 1
    assert [action for action, _ in sent].count('send_group_msg') == 1
