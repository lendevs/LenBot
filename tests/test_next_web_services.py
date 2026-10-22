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
