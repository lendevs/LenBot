"""Yahoo search: verification redirect, retried 500, paging and the result layout the model receives."""

import json

import httpx
import pytest

from len_bot.next.tools import web_search
from len_bot.next.tools.web_search import WebSearchArguments, WebSearchSettings, execute_web_search


def _result(url: str, title: str, snippet: str) -> str:
    wrapped = 'https://r.search.yahoo.com/_ylt=A/RV=2/RE=1/RO=10/RU=' + url.replace(':', '%3a').replace('/', '%2f')
    return (f'<li><div class="dd algo algo-sr relsrch Sr"><div class="compTitle options-toggle">'
            f'<a class="d-ib" href="{wrapped}/RK=2/RS=x-"><div class="thmb algo-favicon"></div>'
            f'<h3 class="title"><span>{title}</span></h3></a></div>'
            f'<div class="compText aAbs"><p>{snippet}</p></div></div></li>')


def _page(*results: str) -> str:
    return '<html><body><div id="web"><ol>' + ''.join(results) + '</ol></div></body></html>'


FIRST = _page(
    _result('https://nodejs.org/en/blog/vulnerability/october-2026-security-releases',
            'Wednesday, October 21, 2026 Security Releases - Node.js',
            '<span class="fc-smoke">17 hours ago · </span>This vulnerability affects <b>Node.js</b> 26.x.'),
    _result('https://example.org/php-advisory', 'PHP &amp; RCE advisory',
            '<span class="fc-smoke">Sep 21, 2026 · </span>PHP security team notes.'),
    _result('https://search.yahoo.com/preferences', 'Yahoo settings', 'not a result'),
)
SECOND = _page(
    _result('https://example.org/php-advisory', 'PHP &amp; RCE advisory', 'duplicate from page one'),
    _result('https://example.net/third', 'Third result', 'Yesterday · no parsable age'),
)


@pytest.fixture
def yahoo(monkeypatch):
    requests: list[httpx.Request] = []
    state = {'failed': False}

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == '/_bv/v.gif':
            return httpx.Response(307, headers={'location': '/search?' + request.url.params['orig'].split('?', 1)[1],
                                                'set-cookie': 'bv=ok; Domain=search.yahoo.com; Path=/'})
        if 'bv=ok' not in request.headers.get('cookie', ''):
            return httpx.Response(307, headers={'location': '/_bv/v.gif?orig=%2Fsearch%3F' + request.url.query.decode()})
        if not state['failed']:
            state['failed'] = True
            return httpx.Response(500, text='busy')
        return httpx.Response(200, text=SECOND if request.url.params.get('b') else FIRST)

    monkeypatch.setattr(web_search, '_transport', lambda: httpx.MockTransport(handle))
    monkeypatch.setattr(web_search, '_yahoo_cookies', httpx.Cookies())
    monkeypatch.setattr(web_search, 'YAHOO_RETRY_SECONDS', 0)
    return requests


def _payload(text: str) -> dict:
    return json.loads(text[text.index('{'):text.rindex('}') + 1])


@pytest.mark.asyncio
async def test_yahoo_passes_verification_retries_and_pages(yahoo):
    settings = WebSearchSettings(provider='yahoo', max_results=5)
    text = await execute_web_search(settings, WebSearchArguments(query='node php cve', count=3))
    payload = _payload(text)
    assert payload['provider'] == 'yahoo' and payload['query'] == 'node php cve'
    rows = payload['results']
    assert [row['url'] for row in rows] == ['https://nodejs.org/en/blog/vulnerability/october-2026-security-releases',
                                            'https://example.org/php-advisory', 'https://example.net/third']
    assert rows[0]['snippet'] == 'This vulnerability affects Node.js 26.x.' and rows[0]['published_at'].endswith('Z')
    assert rows[1]['title'] == 'PHP & RCE advisory' and rows[1]['published_at'] == '2026-09-21'
    assert rows[2]['published_at'] is None and rows[2]['snippet'] == 'Yesterday · no parsable age'
    assert [request.url.params.get('b') for request in yahoo if request.url.path == '/search'][-1] == '3'

    # The verification cookie outlives the client, so the next search goes straight to the result page.
    before = len(yahoo)
    await execute_web_search(settings, WebSearchArguments(query='again', count=1))
    assert [request.url.path for request in yahoo[before:]] == ['/search']


@pytest.mark.asyncio
async def test_yahoo_page_without_results_is_an_error(monkeypatch):
    monkeypatch.setattr(web_search, '_transport',
                        lambda: httpx.MockTransport(lambda request: httpx.Response(200, text='<html>captcha</html>')))
    monkeypatch.setattr(web_search, '_yahoo_cookies', httpx.Cookies())
    with pytest.raises(ValueError, match='no organic results'):
        await execute_web_search(WebSearchSettings(provider='yahoo'), WebSearchArguments(query='anything'))


@pytest.mark.asyncio
async def test_yahoo_redirect_outside_search_host_is_refused(monkeypatch):
    redirect = httpx.Response(307, headers={'location': 'https://evil.example/search'})
    monkeypatch.setattr(web_search, '_transport', lambda: httpx.MockTransport(lambda request: redirect))
    monkeypatch.setattr(web_search, '_yahoo_cookies', httpx.Cookies())
    with pytest.raises(ValueError, match='redirected outside'):
        await execute_web_search(WebSearchSettings(provider='yahoo'), WebSearchArguments(query='anything'))


@pytest.mark.asyncio
async def test_search_adds_the_opening_text_of_the_first_result_that_reads(yahoo):
    from types import SimpleNamespace
    tried = []

    async def read(url):
        tried.append(url)
        if len(tried) == 1:
            raise TimeoutError('web_read exceeded 20 seconds')
        return 7, SimpleNamespace(final_url=url, content='正文' * 1500)

    text = await execute_web_search(WebSearchSettings(provider='yahoo', max_results=3),
                                    WebSearchArguments(query='php cve'), read_top=read)
    result = json.loads(text.split('\n\n')[1])
    top = result['top_page']
    assert tried == [row['url'] for row in result['results'][:2]]
    assert top['document'] == 7 and top['url'] == tried[1] and len(top['text']) == 2000
    assert top['total_chars'] == 3000 and top['next_offset'] == 2000
    assert top['skipped'] == [{'url': tried[0], 'error': 'TimeoutError: web_read exceeded 20 seconds'}]


# Structured fields from the Search API's published response example.
DEEPSEEK_ROW = {
    'rerank_score': 2.4, 'title': 'DeepSeek V4 模型发布',
    'url': 'https://example.com/deepseek-v4', 'snippet': 'DeepSeek V4 已上线。',
    'summary': '模型支持工具调用与长上下文。', 'content': '网页正文。',
    'site_name': 'Example News', 'site_icon': None, 'date': None, 'authority': 3,
}


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['', '/v1', '/gateway/v1'])
async def test_deepseek_search_uses_selected_connection_and_preserves_page(tmp_path, prefix):
    from len_bot.next.configuration.models import Provider
    from len_bot.next.storage.store import Store
    from len_bot.next.tools.web_read import execute_web_read, WebReadArguments, WebReadSettings
    from test_next_native_models import peer_server
    received = []
    content = '网页正文。' * 600
    response = {'results': [{**DEEPSEEK_ROW, 'content': content}]}
    server = await peer_server([(200, 'application/json', json.dumps(response).encode())], received)
    async with server:
        connection = Provider(api='deepseek-search', api_key='search-key',
                              base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}{prefix}')
        with Store(tmp_path / 'search.db') as store:
            scene = 'onebot:group:80001'
            text = await execute_web_search(WebSearchSettings(provider='deepseek', connection='search'),
                WebSearchArguments(query='DeepSeek V4', count=2), connection=connection,
                save_page=lambda page: store.save_web_page(scene, page))
            row = _payload(text)['results'][0]
            assert row['summary'] == DEEPSEEK_ROW['summary']
            assert row['published_at'] is None and row['next_offset'] == 2000
            assert row['total_chars'] == len(content) and row['content'] == content[:2000]
            more = await execute_web_read(store, scene, WebReadSettings(),
                WebReadArguments(document=row['document'], offset=row['next_offset']), fake_ip_networks=())
            assert _payload(more)['text'] == content[2000:]
    assert len(received) == 1
    line, headers, body = received[0]
    expected = (prefix if prefix.endswith('/v1') else prefix + '/v1') + '/tools/search'
    assert line == f'POST {expected} HTTP/1.1'
    assert headers['authorization'] == 'Bearer search-key'
    assert body == {'query': 'DeepSeek V4', 'count': 2, 'need_content': True}


@pytest.mark.asyncio
@pytest.mark.parametrize(('status', 'body', 'error'), [
    (200, {'results': []}, None),
    (200, {'results': [{'title': 'missing fields'}]}, 'invalid response'),
    (200, {'results': [{**DEEPSEEK_ROW, 'content': 42}]}, 'invalid response'),
    (200, 'not json', 'invalid response'),
    (429, {'error': {'message': 'rate limited'}}, 'HTTP 429.*rate limited'),
    (401, {'error': {'message': 'search-key invalid'}}, r'HTTP 401.*\[hidden\] invalid'),
])
async def test_deepseek_empty_and_error_responses(status, body, error):
    from len_bot.next.configuration.models import Provider
    from test_next_native_models import peer_server
    received = []
    raw = body if isinstance(body, str) else json.dumps(body)
    server = await peer_server([(status, 'application/json', raw.encode())], received)
    async with server:
        connection = Provider(api='openai-chat', api_key='search-key',
                              base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1')
        settings = WebSearchSettings(provider='deepseek', connection='primary')
        if error:
            with pytest.raises(ValueError, match=error):
                await execute_web_search(settings, WebSearchArguments(query='test'), connection=connection)
        else:
            result = await execute_web_search(settings, WebSearchArguments(query='test'), connection=connection)
            assert _payload(result)['results'] == []
    assert len(received) == 1


@pytest.mark.asyncio
async def test_deepseek_rejects_long_query_before_request():
    from len_bot.next.configuration.models import Provider
    connection = Provider(api='deepseek-search', base_url='http://127.0.0.1:9/v1', api_key='search-key')
    with pytest.raises(ValueError, match='128'):
        await execute_web_search(WebSearchSettings(provider='deepseek', connection='search'),
            WebSearchArguments(query='长' * 129), connection=connection)


@pytest.mark.parametrize('settings', [
    {'provider': 'deepseek'}, {'provider': 'deepseek', 'connection': ' '},
    {'provider': 'yahoo', 'connection': 'search'},
])
def test_search_connection_configuration(settings):
    with pytest.raises(ValueError):
        WebSearchSettings.model_validate(settings)


@pytest.mark.parametrize(('search', 'limit'), [({'provider': 'yahoo'}, 500),
                                               ({'provider': 'deepseek', 'connection': 'fixture'}, 128)])
def test_tool_schema_limits_query_for_deepseek(tmp_path, search, limit):
    from len_bot.next.chat.tools import build_tools
    from len_bot.next.config import load_host_config
    from len_bot.next.persona.profile import load_persona
    from test_next_host_manage_permissions_config import instance
    source = instance(tmp_path)
    source['web_search'] = search
    (tmp_path / 'lenbot.config.json').write_text(json.dumps(source))
    config = load_host_config(tmp_path).scene_config('onebot:group:80001')
    persona = load_persona(config.persona).model_copy(update={'tools': ['say', 'web_search', 'tool_search']})
    tool = next(tool['function'] for tool in build_tools(config, persona, platform=True)
                if tool['function']['name'] == 'web_search')
    assert tool['parameters']['properties']['query']['maxLength'] == limit
