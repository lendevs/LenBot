"""Worker container fallbacks at the proxy boundary, against loopback peers.

The container is configured with the primary binding; the proxy moves to a
fallback only before any response byte reaches the container.
"""
import asyncio
import json

import httpx
import pytest

from len_bot.next.configuration.models import Failover
from len_bot.next.models.client import ModelSettings
from len_bot.next.models.failover import ProviderHealth
from len_bot.next.models.protocols import build_request
from len_bot.next.work.worker_model import Limits, WorkerModelProxy
from test_next_native_models import response, sse

EVENT = {'choices': [{'index': 0, 'delta': {'content': 'synthetic'}, 'finish_reason': 'stop'}],
         'usage': {'prompt_tokens': 20, 'completion_tokens': 1}}
STREAM = ('data: ' + json.dumps(EVENT) + '\n\ndata: [DONE]\n\n').encode()
REQUEST = {'model': 'primary-model', 'stream': True, 'messages': [{'role': 'user', 'content': 'synthetic work'}]}


class Peer:
    """One loopback upstream: answers every request with the next scripted reply."""

    def __init__(self, *replies):
        self.replies, self.received, self.paths = list(replies), [], []

    async def serve(self, reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)
        self.paths.append(header.split(' ')[1])
        self.received.append(json.loads(await reader.readexactly(int(fields['Content-Length']))))
        status, body = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if status == 'truncated':
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: 1000\r\n\r\n'
                         + STREAM[:20])
        else:
            kind = b'text/event-stream' if status == 200 else b'application/json'
            writer.write(f'HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\nConnection: close\r\n'.encode()
                         + b'Content-Type: ' + kind + b'\r\n\r\n' + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.serve, '127.0.0.1', 0)
        await self.server.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.server.__aexit__(*exc)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/v1'


def chat(url, model, key, **extra):
    return ModelSettings(api='openai-chat', base_url=url, api_key=key, model=model, max_output_tokens=1024, **extra)


def proxy_for(primary, fallbacks, health, started, finished, *, limits=Limits(10, 100000, 100000)):
    def start(facts):
        started.append(facts)
        return len(started)
    return WorkerModelProxy(primary, 'main', 8192, 'synthetic-task', limits, start_call=start,
                            finish_call=lambda ident, facts: finished.append((ident, facts)),
                            fallbacks=fallbacks, health=health)


async def call(proxy, payload=REQUEST):
    async with proxy.open('synthetic-task', json.dumps(payload).encode()) as reply:
        return reply.status, b''.join([chunk async for chunk in reply.body])


@pytest.mark.asyncio
async def test_unavailable_primary_moves_to_the_fallback_before_the_container_sees_bytes():
    health, started, finished = ProviderHealth(Failover(failure_threshold=3, cooldown_seconds=60)), [], []
    async with Peer((503, b'{"error": "overloaded primary-secret-key"}')) as primary, Peer((200, STREAM)) as spare:
        async with proxy_for(chat(primary.url, 'primary-model', 'primary-secret-key'),
                             [('spare', chat(spare.url, 'spare-model', 'spare-secret-key', temperature=0.1))],
                             health, started, finished, limits=Limits(10, 100000, 100000, max_tokens=1000)) as proxy:
            assert await call(proxy) == (200, STREAM)
            # A failed-over 503 produced no output, so the token budget still admits the next call.
            assert await call(proxy) == (200, STREAM)
            assert proxy._calls == 2
    assert [item['model'] for item in primary.received] == ['primary-model'] * 2
    assert [(item['model'], item['temperature']) for item in spare.received] == [('spare-model', 0.1)] * 2
    assert [(item['provider'], item['model'], item['failover_priority']) for item in started] == [
        ('main', 'primary-model', 0), ('spare', 'spare-model', 1)] * 2
    first, second = finished[0][1], finished[1][1]
    assert first['http_status'] == 503 and first['error'] == 'upstream model HTTP 503'
    assert 'primary-secret-key' not in first['error_body']
    assert second['error'] is None and second['tokens']['input'] == 20
    state = health.state()['roles']['worker']
    assert [row['consecutive_failures'] for row in state['candidates']] == [2, 0]
    assert state['last_served']['provider'] == 'spare'
    assert state['last_served']['failed_before'][0]['error'] == 'upstream model HTTP 503'


@pytest.mark.asyncio
async def test_an_unreachable_primary_fails_over_and_an_open_circuit_is_skipped():
    health, started, finished = ProviderHealth(Failover(failure_threshold=1, cooldown_seconds=60)), [], []
    async with Peer((200, STREAM)) as spare:
        async with proxy_for(chat('http://127.0.0.1:9/v1', 'primary-model', 'primary-key'),
                             [('spare', chat(spare.url, 'spare-model', 'spare-key'))],
                             health, started, finished) as proxy:
            assert await call(proxy) == (200, STREAM)
            assert await call(proxy) == (200, STREAM)
    assert [item['provider'] for item in started] == ['main', 'spare', 'spare']
    assert finished[0][1]['error'].startswith('ConnectError')
    assert health.state()['roles']['worker']['candidates'][0]['state'] == 'open'


@pytest.mark.asyncio
async def test_refused_requests_and_broken_streams_do_not_fail_over():
    health, started, finished = ProviderHealth(), [], []
    async with Peer((400, b'{"error": "bad request"}'), ('truncated', b'')) as primary, Peer((200, STREAM)) as spare:
        async with proxy_for(chat(primary.url, 'primary-model', 'primary-key'),
                             [('spare', chat(spare.url, 'spare-model', 'spare-key'))],
                             health, started, finished) as proxy:
            assert await call(proxy) == (400, b'{"error": "bad request"}')
            # A transport error after the container got the headers is not retried elsewhere.
            with pytest.raises(httpx.TransportError):
                await call(proxy)
    assert not spare.received and len(primary.received) == 2
    assert [item['provider'] for item in started] == ['main', 'main']


@pytest.mark.asyncio
async def test_the_last_candidate_failure_reaches_the_container():
    health, started, finished = ProviderHealth(), [], []
    async with Peer((503, b'{"error": "one"}')) as primary, Peer((429, b'{"error": "two"}')) as spare:
        async with proxy_for(chat(primary.url, 'primary-model', 'primary-key'),
                             [('spare', chat(spare.url, 'spare-model', 'spare-key'))],
                             health, started, finished) as proxy:
            assert await call(proxy) == (429, b'{"error": "two"}')
    assert [facts['http_status'] for _, facts in finished] == [503, 429]
    assert [row['failures'] for row in health.state()['roles']['worker']['candidates']] == [1, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize('api', ['openai-responses', 'anthropic', 'gemini'])
async def test_native_fallbacks_send_their_own_model(api):
    health, started, finished = ProviderHealth(), [], []
    body = sse(api, response(api))
    async with Peer((502, b'{}')) as primary, Peer((200, body)) as spare:
        settings = ModelSettings(api=api, base_url=primary.url, api_key='primary-key', model='primary-model',
                                 temperature=None)
        backup = ModelSettings(api=api, base_url=spare.url, api_key='spare-key', model='spare-model', temperature=None)
        _, payload = build_request(settings, [{'role': 'user', 'content': '执行测试'}], [])
        if api != 'gemini':
            payload['stream'] = True
        async with proxy_for(settings, [('spare', backup)], health, started, finished) as proxy:
            assert await call(proxy, payload) == (200, body)
    if api == 'gemini':
        assert 'primary-model' in primary.paths[0] and 'spare-model' in spare.paths[0]
    else:
        assert primary.received[0]['model'] == 'primary-model' and spare.received[0]['model'] == 'spare-model'
    assert finished[-1][1]['error'] is None


def test_fallbacks_must_share_the_primary_protocol():
    primary = chat('http://127.0.0.1:9/v1', 'primary-model', 'key')
    other = ModelSettings(api='anthropic', base_url='http://127.0.0.1:9', api_key='key', model='m')
    with pytest.raises(ValueError, match='protocol'):
        proxy_for(primary, [('spare', other)], ProviderHealth(), [], [])
