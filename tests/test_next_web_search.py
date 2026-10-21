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
