"""One explicitly configured public search service; no provider failover."""

from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from string import Template
from collections.abc import Awaitable, Callable
from typing import Literal, TYPE_CHECKING
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..models.providers import SEARCH_APIS, http_client
from ..storage.store import WebPage

if TYPE_CHECKING:
    from ..configuration.models import Provider

from ..trials.replay_web import RecordedWeb
from ..prompt_files import read_prompt

SEARCH_URL = "https://www.bing.com/search"
YAHOO_URL = "https://search.yahoo.com/search"
YAHOO_HOST = "search.yahoo.com"
YAHOO_PAGES = 3
YAHOO_REDIRECTS = 3
YAHOO_RETRIES = 2
YAHOO_RETRY_SECONDS = 0.5
MAX_RESPONSE_BYTES = 1_000_000
ERROR_BYTES = 2048
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Yahoo sends a new visitor through a same-site redirect that sets a verification cookie. Keeping the cookie for
# the process lifetime lets later searches go straight to the result page.
_yahoo_cookies = httpx.Cookies()


class WebSearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    provider: Literal["yahoo", "bing_rss", "deepseek", "tavily", "brave", "bocha"]
    connection: str | None = Field(default=None, min_length=1, pattern=r"\S")
    timeout_seconds: float = Field(default=15, gt=0, allow_inf_nan=False)
    max_results: int = Field(default=5, ge=1, le=20, strict=True)


    @model_validator(mode="after")
    def search_connection(self):
        if self.provider in SEARCH_APIS and self.connection is None:
            raise ValueError(f"{self.provider} 搜索需要选择连接")
        if self.provider not in SEARCH_APIS and self.connection is not None:
            raise ValueError(f"{self.provider} 搜索不使用连接")
        return self


class WebSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    count: int | None = Field(default=None, ge=1, le=20, strict=True)


WEB_SEARCH_TOOL = {"type": "function", "function": {
    "name": "web_search",
    "description": "搜索公开网页，返回标题、链接、摘要与可用的发布日期。",
    "parameters": WebSearchArguments.model_json_schema(),
}}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    parser.close()
    return re.sub(r"\s+", " ", unescape("".join(parser.parts))).strip()


def _public_link(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (not any(character.isspace() or ord(character) < 32 for character in url)
            and parts.scheme in {"http", "https"} and bool(parts.netloc) and parts.hostname is not None
            and parts.username is None and parts.password is None)


def _item(item: ET.Element, index: int, raw: bytes) -> dict[str, str | None]:
    title = _plain(item.findtext("title") or "")
    url = (item.findtext("link") or "").strip()
    snippet = _plain(item.findtext("description") or "")
    published_at = (item.findtext("pubDate") or "").strip() or None
    if not title or not _public_link(url):
        raise ValueError(f"web_search RSS item {index} has invalid title or link {url[:200]!r}; "
                         f"response fragment: {raw[:500]!r}")
    return {"title": title, "url": url, "snippet": snippet, "published_at": published_at}


def _parse_rss(raw: bytes, max_results: int) -> list[dict[str, str | None]]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError(f"web_search RSS contains a DTD or entity; response fragment: {raw[:500]!r}")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError(f"web_search invalid RSS: {error}; response fragment: {raw[:500]!r}") from error
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError(f"web_search expected RSS channel; response fragment: {raw[:500]!r}")
    return [_item(item, index, raw) for index, item in enumerate(channel.findall("item")[:max_results], 1)]


_YAHOO_RESULT = re.compile(r'<div[^>]+class="[^"]*\balgo-sr\b[^"]*"')
_YAHOO_AGE = re.compile(r"(\d+) (minute|hour|day|week)s? ago")


def _yahoo_date(text: str, fetched: datetime) -> str | None:
    """Yahoo prints either an age such as "17 hours ago" or an English date such as "Sep 21, 2026"."""
    age = _YAHOO_AGE.fullmatch(text)
    if age is not None:
        moment = fetched - timedelta(**{f"{age[2]}s": int(age[1])})
        return moment.strftime("%Y-%m-%dT%H:%MZ") if age[2] in {"minute", "hour"} else moment.date().isoformat()
    try:
        return datetime.strptime(text, "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


def _parse_yahoo(raw: bytes, fetched: datetime) -> list[dict[str, str | None]]:
    blocks = _YAHOO_RESULT.split(raw.decode("utf-8", errors="replace"))[1:]
    rows = []
    for block in blocks:
        href = re.search(r'href="([^"]*/RU=[^"]*)"', block) or re.search(r'href="(https?://[^"]+)"', block)
        title = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        if href is None or title is None:
            continue
        url = unescape(href[1])
        wrapped = re.search(r"/RU=([^/]+)/RK=", url)
        if wrapped is not None:
            url = unquote(wrapped[1])
        text = re.search(r'<div class="compText[^"]*">(.*?)</div>', block, re.S)
        snippet = _plain(text[1]) if text else ""
        published_at = None
        prefix, separator, rest = snippet.partition(" · ")
        if separator and (published_at := _yahoo_date(prefix, fetched)) is not None:
            snippet = rest
        if _public_link(url) and urlsplit(url).hostname != YAHOO_HOST and _plain(title[1]):
            rows.append({"title": _plain(title[1]), "url": url, "snippet": snippet, "published_at": published_at})
    return rows


def _transport() -> httpx.AsyncBaseTransport:
    return httpx.AsyncHTTPTransport(retries=0, trust_env=False)


async def _fetch(client: httpx.AsyncClient, url: str, params: dict[str, str] | None,
                 headers: dict[str, str], label: str) -> tuple[httpx.Response, bytes]:
    async with client.stream("GET", url, params=params, headers=headers) as response:
        body = bytearray()
        limit = MAX_RESPONSE_BYTES if response.status_code == 200 else ERROR_BYTES
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if len(body) + len(chunk) > limit:
                if response.status_code == 200:
                    raise ValueError(f"web_search {label} exceeds {MAX_RESPONSE_BYTES} decoded bytes")
                body.extend(chunk[:limit - len(body)])
                break
            body.extend(chunk)
    return response, bytes(body)


async def _yahoo_page(client: httpx.AsyncClient, query: str, start: int) -> bytes:
    url, params = YAHOO_URL, {"p": query, **({"b": str(start)} if start > 1 else {})}
    headers = {"Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"}
    redirects = failures = 0
    while True:
        response, body = await _fetch(client, url, params, headers, "Yahoo page")
        if response.status_code in {302, 303, 307} and redirects < YAHOO_REDIRECTS:
            target = response.url.join(response.headers.get("location", ""))
            if target.scheme != "https" or target.host != YAHOO_HOST:
                raise ValueError(f"web_search Yahoo redirected outside {YAHOO_HOST}: {str(target)[:200]}")
            redirects += 1
            url, params = str(target), None
            continue
        # Yahoo answers a small share of ordinary searches with 500; the same request succeeds shortly after.
        if response.status_code >= 500 and failures < YAHOO_RETRIES:
            failures += 1
            await asyncio.sleep(YAHOO_RETRY_SECONDS)
            continue
        if response.status_code != 200:
            raise ValueError(f"web_search Yahoo HTTP {response.status_code}: {body.decode('utf-8', errors='replace')}")
        return body


async def _search_yahoo(client: httpx.AsyncClient, query: str, count: int,
                        fetched: datetime) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    seen, start = set(), 1
    for _ in range(YAHOO_PAGES):
        raw = await _yahoo_page(client, query, start)
        page = _parse_yahoo(raw, fetched)
        # Yahoo fills the first page even for nonsense queries, so an empty one means the layout changed.
        if not page and start == 1:
            raise ValueError(f"web_search Yahoo page has no organic results; response fragment: {raw[:500]!r}")
        fresh = [row for row in page if row["url"] not in seen]
        seen.update(row["url"] for row in fresh)
        rows.extend(fresh)
        if len(rows) >= count or not fresh:
            break
        start += len(page)
    return rows[:count]


async def _search_bing_rss(client: httpx.AsyncClient, query: str, count: int) -> list[dict[str, str | None]]:
    response, body = await _fetch(client, SEARCH_URL, {"q": query, "format": "rss"},
                                  {"Accept": "application/rss+xml, application/xml"}, "RSS")
    if response.status_code != 200:
        raise ValueError(f"web_search Bing RSS HTTP {response.status_code}: {body.decode('utf-8', errors='replace')}")
    return _parse_rss(body, count)


TOP_PAGE_CHARS = 2000
TOP_PAGE_TRIES = 2


async def _top_page(rows: list[dict[str, str | None]],
                    read: Callable[[str], Awaitable[tuple[int, object]]]) -> dict:
    """The opening text of the first result that reads, saved as a web_read document."""
    skipped = []
    for row in rows[:TOP_PAGE_TRIES]:
        try:
            document, page = await read(row["url"])
        except Exception as error:
            skipped.append({"url": row["url"], "error": f"{type(error).__name__}: {error}"[:300]})
            continue
        end = min(len(page.content), TOP_PAGE_CHARS)
        return {"document": document, "url": row["url"], "final_url": page.final_url,
                "total_chars": len(page.content), "next_offset": end if end < len(page.content) else None,
                "text": page.content[:end], **({"skipped": skipped} if skipped else {})}
    return {"skipped": skipped}


class DeepSeekResult(BaseModel):
    model_config = ConfigDict(strict=True)
    title: str
    url: str
    snippet: str
    summary: str
    content: str
    date: str | None


class DeepSeekResponse(BaseModel):
    model_config = ConfigDict(strict=True)
    results: list[DeepSeekResult]


async def _search_deepseek(connection: Provider, query: str, count: int, timeout: float) -> list[dict]:
    if len(query) > 128:
        raise ValueError("DeepSeek 搜索词最多 128 个字符，请缩短 query")
    # The API accepts the host root or a versioned API root, including a gateway prefix.
    base = connection.base_url.rstrip('/')
    path = 'tools/search' if urlsplit(base).path.rstrip('/').endswith('/v1') else 'v1/tools/search'
    async with http_client(base_url=base, api_key=connection.api_key, api='openai-chat',
                           proxy=connection.proxy, timeout_seconds=timeout) as client:
        response = await client.post(path, json={'query': query, 'count': count, 'need_content': True})
    raw = response.text.replace(connection.api_key, '[hidden]')
    if not response.is_success:
        raise ValueError(f"web_search DeepSeek HTTP {response.status_code}: {raw[:ERROR_BYTES]}")
    try:
        parsed = DeepSeekResponse.model_validate_json(response.content)
    except ValueError as error:
        raise ValueError(f"web_search DeepSeek invalid response: {raw[:500]}") from error
    return [{'title': row.title, 'url': row.url, 'snippet': row.snippet, 'summary': row.summary,
             'content': row.content, 'published_at': row.date}
            for row in parsed.results[:count]]


async def keyed_request(connection: Provider, method: str, path: str, timeout: float, *, label: str,
                 json_body: dict | None = None, params: dict | None = None) -> object:
    """One request to a keyed web service; the key never appears in errors."""
    async with http_client(base_url=connection.base_url, api_key=connection.api_key, api=connection.api,
                           proxy=connection.proxy, timeout_seconds=timeout) as client:
        response = await client.request(method, path, json=json_body, params=params,
                                        headers={"Accept": "application/json"})
    raw = response.text.replace(connection.api_key, '[hidden]')
    if not response.is_success:
        raise ValueError(f"{label} HTTP {response.status_code}: {raw[:ERROR_BYTES]}")
    try:
        return response.json()
    except ValueError as error:
        raise ValueError(f"{label} invalid response: {raw[:500]}") from error


def _rows(items: object, label: str, fields: tuple[str, str, str, str]) -> list[dict]:
    """Map a provider's result list onto title, url, snippet and published_at."""
    if not isinstance(items, list):
        raise ValueError(f"{label} returned no result list")
    title, url, snippet, date = fields
    return [{"title": item.get(title) or "", "url": item[url], "snippet": item.get(snippet) or "",
             "published_at": item.get(date)} for item in items if isinstance(item, dict) and item.get(url)]


async def _search_tavily(connection: Provider, query: str, count: int, timeout: float) -> list[dict]:
    body = await keyed_request(connection, "POST", "search", timeout, label="web_search Tavily",
                        json_body={"query": query, "max_results": count})
    return _rows(body.get("results"), "web_search Tavily", ("title", "url", "content", "published_date"))[:count]


async def _search_brave(connection: Provider, query: str, count: int, timeout: float) -> list[dict]:
    body = await keyed_request(connection, "GET", "web/search", timeout, label="web_search Brave",
                        params={"q": query, "count": count})
    web = body.get("web") or {}
    return _rows(web.get("results", []), "web_search Brave", ("title", "url", "description", "page_age"))[:count]


async def _search_bocha(connection: Provider, query: str, count: int, timeout: float) -> list[dict]:
    body = await keyed_request(connection, "POST", "web-search", timeout, label="web_search 博查",
                        json_body={"query": query, "count": count, "summary": True})
    pages = (body.get("data") or body).get("webPages") or {}
    rows = _rows(pages.get("value", []), "web_search 博查", ("name", "url", "snippet", "datePublished"))
    for row, item in zip(rows, pages.get("value", []), strict=False):
        if item.get("summary"):
            row["summary"] = item["summary"]
    return rows[:count]


KEYED_SEARCH = {"deepseek": _search_deepseek, "tavily": _search_tavily, "brave": _search_brave,
                "bocha": _search_bocha}


async def execute_web_search(settings: WebSearchSettings, arguments: WebSearchArguments, *,
                             recording: RecordedWeb | None = None,
                             connection: Provider | None = None,
                             save_page: Callable[[WebPage], int] | None = None,
                             read_top: Callable[[str], Awaitable[tuple[int, object]]] | None = None) -> str:
    """``read_top`` reads the first readable result live and adds its opening text."""
    count = arguments.count if arguments.count is not None else settings.max_results
    if count > settings.max_results:
        raise ValueError(f"web_search count {count} exceeds configured max_results {settings.max_results}")
    if recording is not None:
        item, body = recording.search(arguments.query)
        if item.status_code != 200:
            raise ValueError(f'web_search Bing RSS HTTP {item.status_code}: {body[:ERROR_BYTES].decode("utf-8", errors="replace")}')
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError(f'Frozen RSS exceeds {MAX_RESPONSE_BYTES} decoded bytes')
        result = {'provider': 'bing_rss', 'query': arguments.query, 'results': _parse_rss(body, count),
                  'recording': {'source': recording.data.source,
                                'fetched_at': datetime.fromtimestamp(item.fetched_at, timezone.utc).isoformat(),
                                'live_request': False}}
        return Template(read_prompt('next_replay_web_search.md')).substitute(
            result=json.dumps(result, ensure_ascii=False))
    fetched = datetime.now(timezone.utc)
    deadline = asyncio.timeout(settings.timeout_seconds)
    try:
        async with deadline:
            if settings.provider in KEYED_SEARCH:
                if connection is None:
                    raise ValueError(f"{settings.provider} 搜索连接未提供")
                rows = await KEYED_SEARCH[settings.provider](connection, arguments.query, count,
                                                             settings.timeout_seconds)
            else:
                async with httpx.AsyncClient(
                    timeout=settings.timeout_seconds, trust_env=False, follow_redirects=False,
                    headers={"User-Agent": USER_AGENT}, transport=_transport(),
                    cookies=_yahoo_cookies if settings.provider == "yahoo" else None,
                ) as client:
                    try:
                        if settings.provider == "yahoo":
                            rows = await _search_yahoo(client, arguments.query, count, fetched)
                        else:
                            rows = await _search_bing_rss(client, arguments.query, count)
                    finally:
                        if settings.provider == "yahoo":
                            _yahoo_cookies.update(client.cookies)
    except TimeoutError as error:
        if deadline.expired():
            raise TimeoutError(f"web_search exceeded {settings.timeout_seconds} seconds") from error
        raise
    if settings.provider == "deepseek":
        for row in rows:
            content = row["content"]
            if content:
                if save_page is not None:
                    row["document"] = save_page(WebPage(url=row["url"], final_url=row["url"],
                        fetched_at=fetched.timestamp(), media_type="text/markdown", content=content, notice=""))
                row["total_chars"] = len(content)
                row["next_offset"] = TOP_PAGE_CHARS if len(content) > TOP_PAGE_CHARS else None
                row["content"] = content[:TOP_PAGE_CHARS]
    result = {"provider": settings.provider, "query": arguments.query,
              "fetched_at": fetched.strftime("%Y-%m-%dT%H:%MZ"), "results": rows}
    if read_top is not None and rows and settings.provider != "deepseek":
        result["top_page"] = await _top_page(rows, read_top)
    return Template(read_prompt("next_web_search.md")).substitute(result=json.dumps(result, ensure_ascii=False))
