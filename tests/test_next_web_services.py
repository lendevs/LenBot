"""Keyed web services: request path, key header and how each provider's results reach the model."""

import json

import pytest

from len_bot.next.configuration.models import Provider
from len_bot.next.storage.store import Store
from len_bot.next.tools.web_read import WebReadArguments, WebReadSettings, execute_web_read
from len_bot.next.tools.web_search import WebSearchArguments, WebSearchSettings, execute_web_search

from test_next_native_models import peer_server

SCENE = 'onebot:group:80001'


def _payload(text: str) -> dict:
    return json.loads(text[text.index('{'):text.rindex('}') + 1])


def _json(value) -> tuple[int, str, bytes]:
    return 200, 'application/json', json.dumps(value, ensure_ascii=False).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize(('provider', 'api', 'reply', 'request_line', 'header', 'body', 'row'), [
    ('tavily', 'tavily',
     {'query': 'q', 'results': [{'title': 'T', 'url': 'https://a.example/1', 'content': '片段', 'score': 0.9}]},
     'POST /search HTTP/1.1', ('authorization', 'Bearer key-1'), {'query': '新闻', 'max_results': 3},
     {'title': 'T', 'url': 'https://a.example/1', 'snippet': '片段', 'published_at': None}),
    ('brave', 'brave-search',
     {'web': {'results': [{'title': 'B', 'url': 'https://b.example/', 'description': '描述',
                           'page_age': '2026-10-20T08:00:00'}]}},
     'GET /res/v1/web/search?q=%E6%96%B0%E9%97%BB&count=3 HTTP/1.1', ('x-subscription-token', 'key-1'), None,
     {'title': 'B', 'url': 'https://b.example/', 'snippet': '描述', 'published_at': '2026-10-20T08:00:00'}),
    ('bocha', 'bocha',
     {'code': 200, 'data': {'webPages': {'value': [{'name': '博', 'url': 'https://c.example/', 'snippet': '摘',
                                                     'summary': '更长的摘要', 'datePublished': '2026-10-19'}]}}},
     'POST /v1/web-search HTTP/1.1', ('authorization', 'Bearer key-1'),
     {'query': '新闻', 'count': 3, 'summary': True},
     {'title': '博', 'url': 'https://c.example/', 'snippet': '摘', 'published_at': '2026-10-19',
      'summary': '更长的摘要'}),
])
async def test_keyed_search_providers(provider, api, reply, request_line, header, body, row):
    received = []
    server = await peer_server([_json(reply)], received)
    async with server:
        port = server.sockets[0].getsockname()[1]
        base = {'brave-search': f'http://127.0.0.1:{port}/res/v1', 'bocha': f'http://127.0.0.1:{port}/v1'}.get(
            api, f'http://127.0.0.1:{port}')
        connection = Provider(api=api, base_url=base, api_key='key-1')
        text = await execute_web_search(WebSearchSettings(provider=provider, connection='search'),
                                        WebSearchArguments(query='新闻', count=3), connection=connection)
    assert _payload(text)['results'] == [row]
    line, headers, sent = received[0]
    assert line == request_line and headers[header[0]] == header[1] and sent == body


@pytest.mark.asyncio
@pytest.mark.parametrize(('provider', 'api', 'prefix', 'reply', 'request_line', 'body', 'final'), [
    ('deepseek', 'deepseek-search', '/v1', {'title': '页', 'content': '# 正文\n内容'},
     'POST /v1/tools/fetch HTTP/1.1', {'url': 'https://page.example/a'}, 'https://page.example/a'),
    ('deepseek', 'openai-chat', '', {'title': '页', 'content': '# 正文\n内容'},
     'POST /v1/tools/fetch HTTP/1.1', {'url': 'https://page.example/a'}, 'https://page.example/a'),
    ('tavily', 'tavily', '', {'results': [{'url': 'https://page.example/b', 'raw_content': '# 正文\n内容'}],
                              'failed_results': []},
     'POST /extract HTTP/1.1', {'urls': ['https://page.example/a'], 'format': 'markdown'}, 'https://page.example/b'),
    ('jina', 'jina-reader', '', {'code': 200, 'data': {'title': '页', 'url': 'https://page.example/a',
                                                        'content': '# 正文\n内容'}},
     'GET /https://page.example/a HTTP/1.1', None, 'https://page.example/a'),
])
async def test_keyed_read_providers(tmp_path, provider, api, prefix, reply, request_line, body, final):
    received = []
    server = await peer_server([_json(reply)], received)
    async with server:
        connection = Provider(api=api, api_key='key-2',
                              base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}{prefix}')
        with Store(tmp_path / 'read.db') as store:
            text = await execute_web_read(store, SCENE, WebReadSettings(provider=provider, connection='reader'),
                                          WebReadArguments(url='https://page.example/a'), fake_ip_networks=(),
                                          connection=connection)
    page = _payload(text)
    assert page['text'] == '# 正文\n内容' and page['final_url'] == final and page['media_type'] == 'text/markdown'
    line, headers, sent = received[0]
    assert line == request_line and headers['authorization'] == 'Bearer key-2' and sent == body


@pytest.mark.asyncio
async def test_tavily_read_failure_names_the_page(tmp_path):
    received = []
    server = await peer_server([_json({'results': [], 'failed_results': [{'url': 'https://x.example',
                                                                          'error': 'blocked'}]})], received)
    async with server:
        connection = Provider(api='tavily', api_key='key-3',
                              base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}')
        with Store(tmp_path / 'read.db') as store, pytest.raises(ValueError, match='blocked'):
            await execute_web_read(store, SCENE, WebReadSettings(provider='tavily', connection='reader'),
                                   WebReadArguments(url='https://x.example'), fake_ip_networks=(),
                                   connection=connection)


@pytest.mark.parametrize('settings', [{'provider': 'tavily'}, {'provider': 'local', 'connection': 'reader'}])
def test_read_connection_configuration(settings):
    with pytest.raises(ValueError):
        WebReadSettings.model_validate(settings)


@pytest.mark.parametrize(('section', 'value', 'api', 'ok'), [
    ('web_search', {'provider': 'tavily', 'connection': 'svc'}, 'tavily', True),
    ('web_search', {'provider': 'brave', 'connection': 'svc'}, 'tavily', False),
    ('web_read', {'provider': 'jina', 'connection': 'svc'}, 'jina-reader', True),
    ('web_read', {'provider': 'deepseek', 'connection': 'svc'}, 'openai-chat', True),
    ('web_read', {'provider': 'tavily', 'connection': 'svc'}, 'bocha', False),
])
def test_connection_must_match_the_chosen_service(tmp_path, section, value, api, ok):
    from len_bot.next.config import load_host_config
    from test_next_host_manage_permissions_config import instance
    source = instance(tmp_path)
    source['models']['providers']['svc'] = {'api': api, 'base_url': 'https://svc.example', 'api_key': 'k'}
    source[section] = value
    (tmp_path / 'lenbot.config.json').write_text(json.dumps(source))
    if ok:
        assert getattr(load_host_config(tmp_path), section).connection == 'svc'
    else:
        with pytest.raises(ValueError, match='不能使用'):
            load_host_config(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,api', [
    ('jina', 'jina-reader'),
    ('tavily', 'tavily'),
    ('deepseek', 'deepseek-search'),
])
@pytest.mark.parametrize('bad_url', [
    'file:///etc/passwd',
    'http://127.0.0.1:8080/admin',
    'http://10.0.0.1/internal',
    'http://169.254.169.254/latest/meta-data/',
    'http://[::1]/secret',
    'http://localhost/local',
])
async def test_keyed_read_blocks_non_http_and_private_urls_before_remote_request(tmp_path, provider, api, bad_url):
    received = []
    server = await peer_server([_json({'code': 200, 'data': {'content': 'should not fetch'}})], received)
    async with server:
        connection = Provider(api=api, api_key='key-sec',
                              base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}')
        with Store(tmp_path / 'sec.db') as store, pytest.raises(ValueError):
            await execute_web_read(store, SCENE, WebReadSettings(provider=provider, connection='reader'),
                                   WebReadArguments(url=bad_url), fake_ip_networks=(), connection=connection)
    assert received == []


@pytest.mark.asyncio
async def test_http_read_headers_bounded_gzip_deflate_and_bomb_protection(monkeypatch):
    import gzip
    import zlib
    import httpx
    from len_bot.next.tools import http_read

    captured_headers: list[dict[str, str]] = []
    payload = ('测试网页正文内容' * 40).encode('utf-8')
    gzipped = gzip.compress(payload)
    deflated = zlib.compress(payload)
    raw_deflated = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw_deflate_bytes = raw_deflated.compress(payload) + raw_deflated.flush()
    bomb = gzip.compress(b'A' * 200_000)
    assert len(bomb) < 1024

    mode = {'kind': 'gzip'}

    def handle(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        kind = mode['kind']
        if kind == 'gzip':
            return httpx.Response(200, stream=httpx.ByteStream(gzipped),
                                  headers={'content-type': 'text/plain; charset=utf-8', 'content-encoding': 'gzip'})
        if kind == 'deflate':
            return httpx.Response(200, stream=httpx.ByteStream(deflated),
                                  headers={'content-type': 'text/plain; charset=utf-8', 'content-encoding': 'deflate'})
        if kind == 'raw-deflate':
            return httpx.Response(200, stream=httpx.ByteStream(raw_deflate_bytes),
                                  headers={'content-type': 'text/plain; charset=utf-8', 'content-encoding': 'deflate'})
        if kind == 'bomb':
            return httpx.Response(200, stream=httpx.ByteStream(bomb),
                                  headers={'content-type': 'text/plain', 'content-encoding': 'gzip'})
        return httpx.Response(200, stream=httpx.ByteStream(b'abc'),
                              headers={'content-type': 'text/plain', 'content-encoding': 'br'})

    async def fake_numeric(host, port, fake_ip_networks, public_dns_url, timeout_seconds):
        return '93.184.216.34'

    monkeypatch.setattr(http_read, '_numeric_address', fake_numeric)
    monkeypatch.setattr(http_read, 'MeteredTransport', lambda transport, **kwargs: httpx.MockTransport(handle))

    # Gzip succeeds and sends modern User-Agent + Accept-Encoding: gzip, deflate.
    _, _, body = await http_read.fetch_public('https://example.org/a', 5.0, lambda _m, _p: len(payload),
                                              fake_ip_networks=())
    assert body == payload
    assert 'Mozilla/5.0' in captured_headers[-1]['user-agent']
    assert captured_headers[-1]['accept-encoding'] == 'gzip, deflate'

    # Custom User-Agent override is respected.
    _, _, _ = await http_read.fetch_public('https://example.org/a', 5.0, lambda _m, _p: len(payload),
                                           fake_ip_networks=(), headers={'User-Agent': 'CustomBot/1.0'})
    assert captured_headers[-1]['user-agent'] == 'CustomBot/1.0'

    # Both standard zlib deflate and raw deflate work.
    for kind in ('deflate', 'raw-deflate'):
        mode['kind'] = kind
        _, _, body = await http_read.fetch_public('https://example.org/a', 5.0, lambda _m, _p: len(payload),
                                                  fake_ip_networks=())
        assert body == payload

    # Gzip bomb is stopped at byte_limit without expanding into memory.
    mode['kind'] = 'bomb'
    with pytest.raises(ValueError, match='exceeds 1024 decoded bytes'):
        await http_read.fetch_public('https://example.org/bomb', 5.0, lambda _m, _p: 1024, fake_ip_networks=())

    # Unsupported Content-Encoding is rejected.
    mode['kind'] = 'br'
    with pytest.raises(ValueError, match='unsupported Content-Encoding'):
        await http_read.fetch_public('https://example.org/br', 5.0, lambda _m, _p: 1024, fake_ip_networks=())


@pytest.mark.asyncio
async def test_http_read_multimember_gzip_and_chunk_boundaries(monkeypatch):
    import asyncio
    import gzip
    import httpx
    from len_bot.next.tools import http_read

    class ChunkStream(httpx.AsyncByteStream):
        def __init__(self, chunks: list[bytes]):
            self._chunks = chunks

        async def __aiter__(self):
            for chunk in self._chunks:
                yield chunk

    part1 = gzip.compress(b'hello ')
    part2 = gzip.compress(b'world')
    bomb_part = gzip.compress(b'A' * 200_000)

    chunks_box: dict[str, list[bytes]] = {'chunks': [part1 + part2]}

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=ChunkStream(chunks_box['chunks']),
            headers={'content-type': 'text/plain', 'content-encoding': 'gzip'},
        )

    async def fake_numeric(host, port, fake_ip_networks, public_dns_url, timeout_seconds):
        return '93.184.216.34'

    monkeypatch.setattr(http_read, '_numeric_address', fake_numeric)
    monkeypatch.setattr(http_read, 'MeteredTransport', lambda transport, **kwargs: httpx.MockTransport(handle))

    # Single chunk multi-member gzip with small byte_limit triggering max_length stepping must not infinite-loop.
    async with asyncio.timeout(2):
        _, _, body = await http_read.fetch_public(
            'https://example.org/multi', 5.0, lambda _m, _p: 11, fake_ip_networks=(),
        )
    assert body == b'hello world'

    # Tight byte_limit below decoded size stops before overflowing.
    async with asyncio.timeout(2):
        with pytest.raises(ValueError, match='exceeds 10 decoded bytes'):
            await http_read.fetch_public(
                'https://example.org/multi-over', 5.0, lambda _m, _p: 10, fake_ip_networks=(),
            )

    # Two gzip members arriving across separate network chunks decode completely.
    chunks_box['chunks'] = [part1, part2]
    async with asyncio.timeout(2):
        _, _, body = await http_read.fetch_public(
            'https://example.org/chunked-multi', 5.0, lambda _m, _p: 11, fake_ip_networks=(),
        )
    assert body == b'hello world'

    # Multi-member gzip bomb (both single-chunk and cross-chunk) is still rejected at byte_limit.
    for bomb_chunks in ([part1 + bomb_part], [part1, bomb_part]):
        chunks_box['chunks'] = bomb_chunks
        async with asyncio.timeout(2):
            with pytest.raises(ValueError, match='exceeds 1024 decoded bytes'):
                await http_read.fetch_public(
                    'https://example.org/multi-bomb', 5.0, lambda _m, _p: 1024, fake_ip_networks=(),
                )

    # Truncated second gzip member after a complete first member still raises truncated error.
    chunks_box['chunks'] = [part1, part2[:5]]
    async with asyncio.timeout(2):
        with pytest.raises(ValueError, match='truncated gzip body'):
            await http_read.fetch_public(
                'https://example.org/truncated-second', 5.0, lambda _m, _p: 1024, fake_ip_networks=(),
            )


@pytest.mark.asyncio
async def test_web_read_sniffs_html_meta_charset_for_chinese_pages(tmp_path, monkeypatch):
    from len_bot.next.tools import web_read

    html_gbk = (
        '<html><head><meta charset="gbk"><title>中文页面</title></head>'
        '<body><article><h1>中文编码测试</h1><p>这是一段使用 GBK 编码保存的中文新闻正文内容，确保不会出现乱码。</p></article></body></html>'
    ).encode('gbk')
    html_http_equiv = (
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"><title>旧站</title></head>'
        '<body><article><h1>旧站通知</h1><p>使用传统 meta http-equiv 声明编码的中文正文镕字扩展字符。</p></article></body></html>'
    ).encode('gb18030')

    pages = {'https://gbk.example/a': html_gbk, 'https://gb2312.example/b': html_http_equiv}

    async def fake_fetch(url, timeout_seconds, byte_limit, *, fake_ip_networks, public_dns_url=None):
        return url, 'text/html', pages[url]

    monkeypatch.setattr(web_read, 'fetch_public', fake_fetch)

    with Store(tmp_path / 'charset.db') as store:
        text_a = await execute_web_read(store, SCENE, WebReadSettings(),
                                        WebReadArguments(url='https://gbk.example/a'), fake_ip_networks=())
        assert '中文编码测试' in _payload(text_a)['text']
        assert '不会出现乱码' in _payload(text_a)['text']

        text_b = await execute_web_read(store, SCENE, WebReadSettings(),
                                        WebReadArguments(url='https://gb2312.example/b'), fake_ip_networks=())
        assert '旧站通知' in _payload(text_b)['text']
        assert '镕字扩展字符' in _payload(text_b)['text']
