"""Synthetic loopback Chat Completions traffic at the Pi proxy protocol boundary."""

import asyncio
from copy import deepcopy
import json

import pytest

from len_bot.next.models.client import ModelSettings
from len_bot.next.models.slots import ModelSlots
from len_bot.next.work.worker_model import Limits, WorkerModelError, WorkerModelProxy


@pytest.mark.asyncio
@pytest.mark.parametrize('thinking', [None, 'enabled', 'disabled'])
async def test_pi_output_budget_is_validated_forwarded_and_recorded_without_retry(thinking):
    received, started, finished = [], [], []
    event = {'choices': [{'index': 0, 'delta': {'content': 'synthetic'}, 'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 20, 'completion_tokens': 1}}
    stream = ('data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n').encode()

    async def serve(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)
        received.append(json.loads(await reader.readexactly(int(fields['Content-Length']))))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                     + f'Content-Length: {len(stream)}\r\nConnection: close\r\n\r\n'.encode() + stream)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    def record(request):
        started.append(request)
        return len(started)

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(api='openai-chat', base_url=f'http://127.0.0.1:{port}/v1',
                                 api_key='synthetic-key', model='fixture', max_output_tokens=1024, thinking=thinking)
        async with WorkerModelProxy(settings, 'fixture', 4096, 'synthetic-task',
                                    Limits(10, 100000, 100000), start_call=record,
                                    finish_call=lambda ident, result: finished.append((ident, result))) as proxy:
            request = {'model': 'fixture', 'stream': True,
                       'messages': [{'role': 'user', 'content': 'synthetic summary material'}]}
            for invalid in (0, -1, 1025, True, 512.0, '512', None):
                with pytest.raises(WorkerModelError, match='max_completion_tokens'):
                    async with proxy.open('synthetic-task', json.dumps({
                        **request, 'max_completion_tokens': invalid}).encode()):
                        pytest.fail('Invalid output budget reached upstream')
            assert not received and not started
            for fields in ({'max_completion_tokens': 256}, {}):
                async with proxy.open('synthetic-task', json.dumps({**request, **fields}).encode()) as response:
                    assert b''.join([chunk async for chunk in response.body]) == stream
    assert all(item.get('thinking') == (None if thinking is None else {'type': thinking}) for item in received)
    assert [item['max_completion_tokens'] for item in received] == [256, 1024]
    assert [item['request']['max_completion_tokens'] for item in started] == [256, 1024]
    assert started[1]['text_request_estimate_tokens'] - started[0]['text_request_estimate_tokens'] == 768
    assert len(finished) == 2 and all(result['error'] is None for _, result in finished)


def test_rejected_calls_remain_unknown_in_records_but_do_not_block_a_task_budget(tmp_path):
    from len_bot.next.storage.store import Store
    from len_bot.next.work.store import TaskStore
    with Store(tmp_path / 'state.db') as store:
        tasks = TaskStore(store)
        task = tasks.create('onebot:group:80001', 'onebot:70001', '测试', '测试', '测试', '测试')
        call = tasks.start_call(task.scene, task.id, {'provider': 'fixture', 'model': 'fixture'})
        tasks.finish_call(call, {'http_status': 429, 'tokens': None, 'error': 'upstream model HTTP 429'})
        assert tasks.call_tokens(task.scene, task.id) == [None]
        assert tasks.call_tokens(task.scene, task.id, for_budget=True) == []
        interrupted = tasks.start_call(task.scene, task.id, {'provider': 'fixture', 'model': 'fixture'})
        tasks.finish_call(interrupted, {'http_status': 200, 'tokens': None, 'error': 'response interrupted'})
        assert tasks.call_tokens(task.scene, task.id, for_budget=True) == [None]


def _anthropic_sse() -> bytes:
    events = [
        {'type': 'message_start', 'message': {
            'id': 'msg_fixture', 'type': 'message', 'role': 'assistant', 'content': [],
            'stop_reason': None, 'usage': {'input_tokens': 12, 'output_tokens': 0},
        }},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'ok'}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 3}},
        {'type': 'message_stop'},
    ]
    return b''.join(f'event: {ev["type"]}\ndata: {json.dumps(ev)}\n\n'.encode() for ev in events)


def _responses_sse() -> bytes:
    event = {
        'type': 'response.completed',
        'response': {
            'id': 'resp_fixture', 'status': 'completed',
            'output': [{'type': 'message', 'role': 'assistant', 'id': 'msg_fixture', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': 'ok', 'annotations': []}]}],
            'usage': {'input_tokens': 12, 'output_tokens': 3},
        },
    }
    return f'data: {json.dumps(event)}\n\n'.encode()


def _count_cache_controls(payload: dict) -> int:
    total = 1 if payload.get('cache_control') is not None else 0
    if isinstance(payload.get('system'), list):
        total += sum(1 for b in payload['system'] if isinstance(b, dict) and 'cache_control' in b)
    if isinstance(payload.get('tools'), list):
        total += sum(1 for t in payload['tools'] if isinstance(t, dict) and 'cache_control' in t)
    for msg in payload.get('messages', []):
        if isinstance(msg, dict) and isinstance(msg.get('content'), list):
            total += sum(1 for b in msg['content'] if isinstance(b, dict) and 'cache_control' in b)
    return total


@pytest.mark.asyncio
async def test_anthropic_worker_injects_three_cache_breakpoints_and_skips_thinking():
    received, started, finished = [], [], []
    stream = _anthropic_sse()

    async def serve(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = {k.lower(): v for k, v in (line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)}
        received.append(json.loads(await reader.readexactly(int(fields['content-length']))))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                     + f'Content-Length: {len(stream)}\r\nConnection: close\r\n\r\n'.encode() + stream)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(api='anthropic', base_url=f'http://127.0.0.1:{port}/v1',
                                 api_key='synthetic-key', model='fixture', max_output_tokens=1024, temperature=None)
        async with WorkerModelProxy(
            settings, 'fixture', 8192, 'synthetic-task', Limits(10, 100000, 100000),
            start_call=lambda req: started.append(req) or len(started),
            finish_call=lambda ident, res: finished.append((ident, res)),
        ) as proxy:
            # 1) List system + tools + messages[-2] ending with thinking/redacted_thinking blocks
            inbound_list = {
                'model': 'fixture',
                'stream': True,
                'system': [{'type': 'text', 'text': 'sys-1'}, {'type': 'text', 'text': 'sys-2'}],
                'tools': [
                    {'name': 'tool_a', 'input_schema': {'type': 'object', 'properties': {}}},
                    {'name': 'tool_b', 'input_schema': {'type': 'object', 'properties': {}}},
                ],
                'messages': [
                    {'role': 'user', 'content': [{'type': 'text', 'text': 'step 1'}]},
                    {'role': 'assistant', 'content': [
                        {'type': 'text', 'text': 'step 2'},
                        {'type': 'thinking', 'thinking': 'hidden', 'signature': 'sig'},
                        {'type': 'redacted_thinking', 'data': 'opaque'},
                    ]},
                    {'role': 'user', 'content': [{'type': 'text', 'text': 'step 3'}]},
                ],
            }
            snapshot = deepcopy(inbound_list)
            outgoing, wire, _, _ = proxy._native_request(inbound_list, json.dumps(inbound_list).encode())
            assert inbound_list == snapshot
            assert json.loads(wire) == outgoing

            async with proxy.open('synthetic-task', json.dumps(inbound_list).encode()) as response:
                assert b''.join([chunk async for chunk in response.body]) == stream

            # 2) String system + string content on messages[-2]
            inbound_str = {
                'model': 'fixture',
                'stream': True,
                'system': 'plain system prompt',
                'tools': [{'name': 'tool_a', 'input_schema': {'type': 'object', 'properties': {}}}],
                'messages': [
                    {'role': 'user', 'content': 'earlier user turn'},
                    {'role': 'assistant', 'content': 'latest turn'},
                ],
            }
            async with proxy.open('synthetic-task', json.dumps(inbound_str).encode()) as response:
                assert b''.join([chunk async for chunk in response.body]) == stream

    first = received[0]
    assert 'cache_control' not in first['system'][0]
    assert first['system'][1]['cache_control'] == {'type': 'ephemeral'}
    assert 'cache_control' not in first['tools'][0]
    assert first['tools'][1]['cache_control'] == {'type': 'ephemeral'}
    assert first['messages'][1]['content'][0]['cache_control'] == {'type': 'ephemeral'}
    assert 'cache_control' not in first['messages'][1]['content'][1]
    assert 'cache_control' not in first['messages'][1]['content'][2]
    assert 'cache_control' not in first['messages'][2]['content'][0]
    assert _count_cache_controls(first) == 3

    second = received[1]
    assert second['system'] == [{'type': 'text', 'text': 'plain system prompt', 'cache_control': {'type': 'ephemeral'}}]
    assert second['tools'][0]['cache_control'] == {'type': 'ephemeral'}
    assert second['messages'][0]['content'] == [
        {'type': 'text', 'text': 'earlier user turn', 'cache_control': {'type': 'ephemeral'}},
    ]
    assert second['messages'][1]['content'] == 'latest turn'
    assert _count_cache_controls(second) == 3
    assert len(finished) == 2 and all(res['error'] is None for _, res in finished)


def test_anthropic_worker_cache_breakpoints_respect_existing_and_cap_at_four():
    settings = ModelSettings(api='anthropic', base_url='http://127.0.0.1:9/v1',
                             api_key='synthetic-key', model='fixture', max_output_tokens=1024, temperature=None)
    proxy = WorkerModelProxy(
        settings, 'fixture', 8192, 'synthetic-task', Limits(10, 100000, 100000),
        start_call=lambda _: 1, finish_call=lambda *_: None,
    )
    custom = {'type': 'ephemeral', 'ttl': '1h'}

    # Already has 2 breakpoints in earlier messages -> system (3rd) and tools (4th) injected, messages[-2] skipped.
    payload_two = {
        'model': 'fixture',
        'stream': True,
        'system': [{'type': 'text', 'text': 'sys'}],
        'tools': [{'name': 'tool_a', 'input_schema': {'type': 'object', 'properties': {}}}],
        'messages': [
            {'role': 'user', 'content': [{'type': 'text', 'text': 'm0', 'cache_control': custom}]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'm1', 'cache_control': {'type': 'ephemeral'}}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': 'm2'}]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'm3'}]},
        ],
    }
    out_two, _, _, _ = proxy._native_request(payload_two, json.dumps(payload_two).encode())
    assert _count_cache_controls(out_two) == 4
    assert out_two['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert out_two['tools'][0]['cache_control'] == {'type': 'ephemeral'}
    assert out_two['messages'][0]['content'][0]['cache_control'] == custom
    assert 'cache_control' not in out_two['messages'][-2]['content'][0]

    # System already carries custom cache_control + 2 in messages = 3 -> tools gets 4th, system preserved, messages[-2] skipped.
    payload_three = {
        'model': 'fixture',
        'stream': True,
        'system': [{'type': 'text', 'text': 'sys', 'cache_control': custom}],
        'tools': [{'name': 'tool_a', 'input_schema': {'type': 'object', 'properties': {}}}],
        'messages': [
            {'role': 'user', 'content': [{'type': 'text', 'text': 'm0', 'cache_control': {'type': 'ephemeral'}}]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'm1', 'cache_control': {'type': 'ephemeral'}}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': 'm2'}]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'm3'}]},
        ],
    }
    out_three, _, _, _ = proxy._native_request(payload_three, json.dumps(payload_three).encode())
    assert _count_cache_controls(out_three) == 4
    assert out_three['system'][0]['cache_control'] == custom
    assert out_three['tools'][0]['cache_control'] == {'type': 'ephemeral'}
    assert 'cache_control' not in out_three['messages'][-2]['content'][0]

    # Already at 4 breakpoints -> nothing added.
    payload_four = deepcopy(out_three)
    out_four, _, _, _ = proxy._native_request(payload_four, json.dumps(payload_four).encode())
    assert _count_cache_controls(out_four) == 4
    assert 'cache_control' not in out_four['messages'][-2]['content'][0]


@pytest.mark.asyncio
async def test_openai_responses_worker_injects_prompt_cache_key_unless_provided():
    received, finished = [], []
    stream = _responses_sse()

    async def serve(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = {k.lower(): v for k, v in (line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)}
        received.append(json.loads(await reader.readexactly(int(fields['content-length']))))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                     + f'Content-Length: {len(stream)}\r\nConnection: close\r\n\r\n'.encode() + stream)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(api='openai-responses', base_url=f'http://127.0.0.1:{port}/v1',
                                 api_key='synthetic-key', model='fixture', max_output_tokens=1024, temperature=None)
        base_req = {'model': 'fixture', 'stream': True, 'input': [{'role': 'user', 'content': 'hello'}]}
        async with WorkerModelProxy(
            settings, 'fixture', 8192, 'synthetic-task', Limits(10, 100000, 100000),
            cache_key='worker-key-abc',
            start_call=lambda _: 1,
            finish_call=lambda ident, res: finished.append((ident, res)),
        ) as proxy:
            async with proxy.open('synthetic-task', json.dumps(base_req).encode()) as response:
                assert b''.join([chunk async for chunk in response.body]) == stream
            with_client_key = {**base_req, 'prompt_cache_key': 'client-provided-key'}
            async with proxy.open('synthetic-task', json.dumps(with_client_key).encode()) as response:
                assert b''.join([chunk async for chunk in response.body]) == stream

    assert received[0]['prompt_cache_key'] == 'worker-key-abc'
    assert received[1]['prompt_cache_key'] == 'client-provided-key'
    assert len(finished) == 2 and all(res['error'] is None for _, res in finished)


@pytest.mark.asyncio
async def test_worker_proxy_uses_worker_slot_tier_and_is_busy_while_queued():
    received, finished = [], []
    stream = _responses_sse()
    server_hit = asyncio.Event()

    async def serve(reader, writer):
        server_hit.set()
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = {k.lower(): v for k, v in (line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)}
        received.append(json.loads(await reader.readexactly(int(fields['content-length']))))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                     + f'Content-Length: {len(stream)}\r\nConnection: close\r\n\r\n'.encode() + stream)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    # limit=2 -> worker_limit=1, leaving 1 hot slot for normal interactive turns.
    slots = ModelSlots(2)
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(api='openai-responses', base_url=f'http://127.0.0.1:{port}/v1',
                                 api_key='synthetic-key', model='fixture', max_output_tokens=1024, temperature=None)
        req_bytes = json.dumps({'model': 'fixture', 'stream': True,
                                'input': [{'role': 'user', 'content': 'queued'}]}).encode()
        async with WorkerModelProxy(
            settings, 'fixture', 8192, 'synthetic-task', Limits(10, 100000, 100000),
            slots=slots, scene='onebot:group:1', cache_key='slot-test-key',
            start_call=lambda _: 1,
            finish_call=lambda ident, res: finished.append((ident, res)),
        ) as proxy:
            assert proxy.busy is False
            async with slots.slot(worker=True):
                async def call_proxy() -> bytes:
                    async with proxy.open('synthetic-task', req_bytes) as response:
                        return b''.join([chunk async for chunk in response.body])

                task = asyncio.create_task(call_proxy())
                for _ in range(3):
                    await asyncio.sleep(0)

                # Proxy must be queued under worker=True (blocked by worker_limit=1) and report busy=True.
                assert proxy.busy is True
                assert not server_hit.is_set()
                assert len(slots._worker) == 1

                # Interactive normal turn still enters the reserved hot slot with zero wait.
                async with slots.slot():
                    assert slots._active == 2
                    assert not server_hit.is_set()

            result = await asyncio.wait_for(task, timeout=2.0)
            assert result == stream
            assert proxy.busy is False

    assert len(received) == 1
    assert received[0]['prompt_cache_key'] == 'slot-test-key'
    assert len(finished) == 1 and finished[0][1]['error'] is None


def test_worker_anthropic_cache_skips_empty_text_blocks_and_null_cache_control():
    from len_bot.next.work.worker_model import _apply_anthropic_cache_breakpoints

    outgoing = {
        'model': 'fixture',
        'stream': True,
        'system': [
            {'type': 'text', 'text': 'valid system', 'cache_control': None},
            {'type': 'text', 'text': '   '},
        ],
        'tools': [{'name': 'bash', 'input_schema': {'type': 'object'}, 'cache_control': None}],
        'messages': [
            {
                'role': 'assistant',
                'content': [
                    {'type': 'tool_use', 'id': 'tu-1', 'name': 'bash', 'input': {}},
                    {'type': 'text', 'text': ''},
                ],
            },
            {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'tu-1', 'content': 'ok'}]},
        ],
    }
    _apply_anthropic_cache_breakpoints(outgoing)
    assert outgoing['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert 'cache_control' not in outgoing['system'][1]
    assert outgoing['tools'][0]['cache_control'] == {'type': 'ephemeral'}
    assert outgoing['messages'][0]['content'][0]['cache_control'] == {'type': 'ephemeral'}
    assert 'cache_control' not in outgoing['messages'][0]['content'][1]
