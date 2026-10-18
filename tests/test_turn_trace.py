"""A local model drives live turn cards through the real panel event stream."""

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from test_attention_protocol import message, response
from test_host_stream import login, panel, receive
from test_next_native_models import peer_server
from test_next_panel_acts_as_owner import SCENE


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['success', 'tool-error', 'model-error', 'cancel'])
async def test_turn_trace_includes_model_tools_delivery_and_end(tmp_path, case):
    replies = [response('say', {'content': '合成回答', 'end_turn': True}, 'say1')]
    if case == 'tool-error':
        replies.insert(0, response('say', {'content': '', 'end_turn': True}, 'invalid1'))
    if case == 'model-error':
        replies = [(503, 'application/json', b'{"error":{"message":"synthetic unavailable"}}')]
    if case == 'cancel':
        replies = [response('wait', {'seconds': 30, 'reason': '合成等待'}, 'wait1')]
    requests = []
    server = await peer_server(replies, requests)

    def configure(root):
        path = root / 'lenbot.config.json'
        source = json.loads(path.read_text())
        source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        source['memory'] = {'backend': 'local', 'local': {'directory': 'memory'}}
        source['models']['roles']['mind']['context_window_tokens'] = 64000
        source['compaction']['input_tokens'] = 30000
        source['scenes'][SCENE]['attention'] = {'direct_idle_seconds': 0}
        path.write_text(json.dumps(source))
        path = root / 'persona/persona.yaml'
        path.write_text('id: trace-test\nname: 测试角色\nbrief: 合成资料\nbehavior: 回答\n'
                        'self_reference: [我]\naliases: []\ntools: [say, wait]\nskills: []\nstyles: []\n')

    async with server, panel(tmp_path, configure) as (runtime, client, url):
        await runtime.memory.write(SCENE, 'topics/report.md', '报告周五提交。', '合成记忆')
        async with connect(url, additional_headers=await login(client), proxy=None) as ws:
            await receive(ws)
            runner = runtime.runners[SCENE]
            runner.receive(message(70001, 101, '报告周五提交', direct=True))
            runner.close_input()
            running = asyncio.create_task(runner.run())
            events = []
            while True:
                event = await receive(ws)
                events.append(event)
                if case == 'cancel' and event['type'] == 'turn.step' and event['kind'] == 'tool' and event['phase'] == 'start':
                    running.cancel()
                if event['type'] == 'turn.ended':
                    break
            if case == 'cancel':
                with pytest.raises(asyncio.CancelledError):
                    await running
            else:
                await asyncio.wait_for(running, 3)
            turn_id = next(event['turn_id'] for event in events if event['type'] == 'turn.started')
            response_detail = await client.get(f'/api/host/scenes/{SCENE}/turns/{turn_id}')
            assert response_detail.status_code == 200, response_detail.text
            detail = response_detail.json()
            assert len(detail['steps']) == len(requests)
            assert detail['recall'][0]['path'] == 'topics/report.md'
            if case in {'success', 'tool-error'}:
                sent = detail['steps'][-1]['tools'][0]
                assert sent['arguments']['content'] == '合成回答' and sent['status'] == 'complete'
                assert sent['messages'][0]['status'] == 'simulated'
            if case == 'tool-error':
                assert detail['steps'][0]['tools'][0]['status'] == 'error'
            if case == 'cancel':
                assert detail['steps'][0]['tools'][0]['status'] == 'interrupted'
            if case in {'success', 'tool-error'}:
                links = runtime.store.db.execute('SELECT expression_entry_seq FROM messages WHERE expression_entry_seq IS NOT NULL').fetchall()
                assert len(links) == 1
                result = runtime.store.db.execute('SELECT message FROM mind_entries WHERE seq=?', (links[0][0],)).fetchone()[0]
                assert json.loads(result)['tool_call_id'] == 'say1'
            timeline = (await client.get(f'/api/host/scenes/{SCENE}/timeline')).json()
            card = next(item for item in timeline['items'] if item['type'] == 'turn')
            assert card['steps'] == len(requests)
            assert card['expressions'] == (1 if case in {'success', 'tool-error'} else 0)
    traced = [e for e in events if e['type'] in {'turn.started', 'turn.step', 'turn.ended', 'message.sent'}]
    assert traced[0]['type'] == 'turn.started'
    assert traced[0]['channel'] == 'direct' and traced[0]['direct']
    assert all(e['scene'] == SCENE and e['turn_id'] == traced[0]['turn_id'] for e in traced)
    assert traced[-1]['type'] == 'turn.ended'
    assert traced[-1]['status'] == ('error' if case == 'model-error' else 'cancelled' if case == 'cancel' else 'settled'), traced[-1]
    recall = next(e for e in traced if e.get('kind') == 'recall' and e['phase'] == 'end')
    assert any(item['path'] == 'topics/report.md' and item['characters'] > 0 for item in recall['items'])
    models = [e for e in traced if e.get('kind') == 'model']
    assert [e['phase'] for e in models] == ['start', 'end'] * len(requests)
    assert all(e['role'] == 'mind' and isinstance(e['call_id'], int) for e in models)
    assert models[-1]['elapsed_seconds'] >= 0
    if case == 'model-error':
        assert '503' in models[-1]['error'] and models[-1]['tokens'] is None
    else:
        assert models[-1]['tokens'] == {'input': 100, 'output': 20, 'cached': None}
        tools = [e for e in traced if e.get('kind') == 'tool']
        assert [e['phase'] for e in tools] == ['start', 'end'] * len(requests)
        assert all(len(e['arguments_summary']) <= 500 for e in tools if e['phase'] == 'start')
        if case == 'cancel':
            assert tools[-1]['status'] == 'cancelled'
        else:
            assert any(e['type'] == 'message.sent' and e['status'] == 'simulated' and e['message_seq'] > 0 for e in traced)
            assert any(e.get('kind') == 'expression' and e['status'] == 'simulated' for e in traced)
        if case == 'tool-error':
            assert tools[1]['status'] == 'error' and tools[-1]['status'] == 'complete'


@pytest.mark.asyncio
@pytest.mark.parametrize('early_echo', [False, True])
async def test_turn_detail_uses_actual_delivery_results_and_merged_echo(tmp_path, early_echo):
    peers = asyncio.Queue()

    async def peer(ws):
        await peers.put(ws)
        async for frame in ws:
            request = json.loads(frame)
            result = {'status': 'ok', 'retcode': 0, 'echo': request['echo']}
            if request['action'] == 'get_login_info':
                result['data'] = {'user_id': 90001, 'nickname': '合成角色'}
            elif early_echo:
                await ws.send(json.dumps(message(90001, 999, '合成回答')))
                result['data'] = {'message_id': 999}
            else:
                result.update(status='failed', retcode=100, message='合成发送失败', data=None)
            await ws.send(json.dumps(result))

    requests = []
    responses = [response('say', {'content': '合成回答', 'end_turn': True}, 'say1')]
    if not early_echo:
        responses.append((200, 'application/json', json.dumps({
            'choices': [{'message': {'role': 'assistant', 'content': '停止发送'}, 'finish_reason': 'stop'}]}).encode()))
    model = await peer_server(responses, requests)
    async with model, serve(peer, '127.0.0.1', 0) as platform:
        def configure(root):
            path = root / 'lenbot.config.json'
            source = json.loads(path.read_text())
            source['onebot'] = {'mode': 'forward_ws', 'ws_url': f'ws://127.0.0.1:{platform.sockets[0].getsockname()[1]}'}
            source['delivery'] = 'onebot'
            source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{model.sockets[0].getsockname()[1]}/v1'
            source['models']['roles']['mind']['context_window_tokens'] = 64000
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
                    await wire.send(json.dumps(message(70001, 1, '在吗', direct=True)))
                    sent = None
                    while True:
                        event = await receive(ws)
                        if event['type'] == 'message.sent':
                            sent = event
                        if event['type'] == 'turn.ended':
                            break
                    response_detail = await client.get(f'/api/host/scenes/{SCENE}/turns/{event["turn_id"]}')
                    assert response_detail.status_code == 200, response_detail.text
                    delivered = response_detail.json()['steps'][0]['tools'][0]['messages']
                    assert len(delivered) == 1
                    assert delivered[0]['message_seq'] == sent['message_seq']
                    assert delivered[0]['status'] == ('sent' if early_echo else 'failed')
                    if early_echo:
                        assert delivered[0]['platform_message_id'] == '999'
                        assert runtime.store.db.execute("SELECT COUNT(*) FROM messages WHERE platform_id='999'").fetchone()[0] == 1
                finally:
                    runtime.stop()
                    await asyncio.wait_for(running, 3)
