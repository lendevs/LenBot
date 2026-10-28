"""Isolated public document read: one bounded fetch, one extraction, saved pages."""

from __future__ import annotations

import asyncio
import codecs
import json
import sys
import time
from datetime import datetime, timezone
from email.message import Message
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from string import Template

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pdf_read import read_pdf

from ..configuration.chat import WebReadSettings
from .http_read import fetch_public
from ..storage.store import Store, WebPage
from ..trials.replay_web import RecordedWeb
from ..prompt_files import read_prompt
from .web_search import keyed_request

if TYPE_CHECKING:
    from ..configuration.models import Provider


PAGE_CHARS = 4000
TEXT_BYTES = 2_000_000
PDF_BYTES = 10_000_000


class WebReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: str | None = None
    document: int | None = Field(default=None, gt=0)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def one_location(self) -> WebReadArguments:
        if (self.url is None) == (self.document is None):
            raise ValueError("exactly one of url or document is required")
        if self.url is not None:
            if not self.url.strip():
                raise ValueError("url must not be blank")
            if self.offset:
                raise ValueError("url first read requires offset=0; use document to continue")
        return self


WEB_READ_TOOL = {"type": "function", "function": {
    "name": "web_read",
    "description": "读取公开 HTTP(S) 网页、文本、JSON 或 PDF 文本层。url 首读保存完整实际提取结果并显示前4000字符；"
                   "document 用返回的文档编号和字符 offset 续读已保存的结果。",
    "parameters": WebReadArguments.model_json_schema(),
}}


def _web_limit(media_type: str, prefix: bytes) -> int:
    return PDF_BYTES if media_type == "application/pdf" or prefix.startswith(b"%PDF-") else TEXT_BYTES


def _decode(body: bytes, content_type: str) -> str:
    header = Message()
    header["content-type"] = content_type
    encoding = codecs.lookup(header.get_content_charset() or "utf-8").name
    if (encoding not in {"utf-8", "utf-8-sig", "ascii", "gb18030", "gbk", "gb2312", "big5", "big5hkscs",
                         "shift_jis", "cp932", "euc_jp", "euc_kr", "iso2022_jp", "koi8-r", "koi8-u",
                         "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"}
            and not encoding.startswith("iso8859-")
            and encoding not in {f"cp125{n}" for n in range(9)}):
        raise ValueError(f"web_read unsupported web charset: {encoding}")
    return body.decode(encoding, errors="strict")


async def _extract_html(body: str, url: str) -> str:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", __name__, "extract",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate(
            json.dumps({"html": body, "url": url}, ensure_ascii=False).encode("utf-8"),
        )
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError(f"web_read HTML extraction failed: {stderr.decode(errors='replace')[-500:]}")
    return stdout.decode("utf-8", errors="strict")


async def _extract(url: str, content_type: str, body: bytes) -> tuple[str, str, str]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type == "application/pdf" or body.startswith(b"%PDF-"):
        document = await read_pdf(body)
        notice = (f"PDF文本层：共{document['page_count']}页，实际提取{document['pages_extracted']}页；"
                  f"20万字符上限{'已达到，正文已截断' if document['truncated'] else '未达到'}；"
                  "内容来自文本层，图像和图表需查看原文件。")
        if not document["has_text"]:
            notice += " 页面未提取到文字，可能是扫描页；需查看原图。"
        return "application/pdf", document["text"], notice
    if not media_type:
        raise ValueError("web_read response has no Content-Type")
    if media_type in {"text/html", "application/xhtml+xml"}:
        decoded = _decode(body, content_type)
        content = await _extract_html(decoded, url)
        if not content.strip():
            raise ValueError("web_read HTML extraction returned no body")
        return media_type, content, "HTML正文由trafilatura提取。"
    if media_type in {"text/plain", "text/markdown", "text/csv"}:
        decoded = _decode(body, content_type)
        return media_type, decoded, "按响应字符集（缺省UTF-8）严格解码的文本；未执行页面脚本。"
    if media_type in {"application/json", "text/json"} or media_type.endswith("+json"):
        decoded = _decode(body, content_type)
        try:
            json.loads(decoded, parse_constant=_reject_json_constant,
                       parse_float=str, parse_int=str)
        except ValueError as error:
            raise ValueError(f"web_read invalid JSON: {error}; response fragment: {decoded[:500]}") from error
        return media_type, decoded, "已校验JSON语法，正文保留响应原文与数字写法。"
    raise ValueError(f"web_read unsupported Content-Type: {media_type}")


def _page(document: int, page: WebPage, offset: int) -> str:
    total = len(page.content)
    if offset > total:
        raise ValueError(f"web_read offset {offset} exceeds document length {total}")
    end = min(total, offset + PAGE_CHARS)
    result = {
        "document": document, "url": page.url, "final_url": page.final_url,
        "fetched_at": datetime.fromtimestamp(page.fetched_at, timezone.utc).isoformat(),
        "media_type": page.media_type, "notice": page.notice,
        "offset": offset, "end": end, "total_chars": total,
        "next_offset": end if end < total else None,
        "text": page.content[offset:end],
    }
    return Template(read_prompt("next_web_read.md")).substitute(result=json.dumps(result, ensure_ascii=False))


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value}")


async def execute_web_read(store: Store, scene: str, settings: WebReadSettings,
                           arguments: WebReadArguments, *, recording: RecordedWeb | None = None,
                           fake_ip_networks: tuple, public_dns_url: str | None = None,
                           connection: Provider | None = None) -> str:
    if arguments.document is not None:
        page = store.web_page(scene, arguments.document)
        if page is None:
            raise ValueError(f"当前场景没有网页文档 {arguments.document}")
        return _page(arguments.document, page, arguments.offset)
    if recording is None:
        document, page = await read_web_page(store, scene, settings, arguments.url,
                                             fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
                                             connection=connection)
        return _page(document, page, 0)
    deadline = asyncio.timeout(settings.timeout_seconds)
    try:
        async with deadline:
            item, body = recording.document(arguments.url)
            if not 200 <= item.status_code < 300:
                raise ValueError(f'HTTP read status {item.status_code}: {body[:2048].decode("utf-8", errors="replace")}')
            final_url, content_type, fetched_at = item.final_url, item.content_type, item.fetched_at
            media_type = content_type.split(';', 1)[0].strip().lower()
            if len(body) > _web_limit(media_type, body[:8]):
                raise ValueError(f'Frozen web_read response exceeds the normal {media_type} byte limit')
            media_type, content, notice = await _extract(final_url, content_type, body)
            notice += " 本次读取的是录制的响应，抓取时间来自原始资料清单。"
            page = WebPage(url=arguments.url, final_url=final_url, fetched_at=fetched_at,
                           media_type=media_type, content=content, notice=notice)
            document = store.save_web_page(scene, page)
    except TimeoutError as error:
        if deadline.expired():
            raise TimeoutError(f"web_read exceeded {settings.timeout_seconds} seconds") from error
        raise
    return _page(document, page, 0)


async def _read_deepseek(connection: Provider, url: str, timeout: float) -> tuple[str, str]:
    base = connection.base_url.rstrip('/')
    path = 'tools/fetch' if urlsplit(base).path.rstrip('/').endswith('/v1') else 'v1/tools/fetch'
    body = await keyed_request(connection, "POST", path, timeout, label="web_read DeepSeek", json_body={"url": url})
    return url, body["content"]


async def _read_tavily(connection: Provider, url: str, timeout: float) -> tuple[str, str]:
    body = await keyed_request(connection, "POST", "extract", timeout, label="web_read Tavily",
                        json_body={"urls": [url], "format": "markdown"})
    results = body.get("results") or []
    if not results:
        raise ValueError(f"web_read Tavily could not read {url}: {json.dumps(body.get('failed_results'), ensure_ascii=False)[:500]}")
    return results[0].get("url") or url, results[0]["raw_content"]


async def _read_jina(connection: Provider, url: str, timeout: float) -> tuple[str, str]:
    # The page address follows the reader's own address; passed alone, httpx would request the page itself.
    body = await keyed_request(connection, "GET", f"{connection.base_url.rstrip('/')}/{url}", timeout,
                               label="web_read Jina")
    data = body.get("data") or {}
    return data.get("url") or url, data["content"]


KEYED_READ = {"deepseek": _read_deepseek, "tavily": _read_tavily, "jina": _read_jina}
KEYED_NAMES = {"deepseek": "DeepSeek", "tavily": "Tavily", "jina": "Jina Reader"}


async def read_web_page(store: Store, scene: str, settings: WebReadSettings, url: str, *,
                        fake_ip_networks: tuple, public_dns_url: str | None = None,
                        connection: Provider | None = None) -> tuple[int, WebPage]:
    """Fetch one public page live, extract its text and save it as a scene document."""
    deadline = asyncio.timeout(settings.timeout_seconds)
    try:
        async with deadline:
            if settings.provider != "local":
                if connection is None:
                    raise ValueError(f"{settings.provider} 读取连接未提供")
                final_url, content = await KEYED_READ[settings.provider](connection, url, settings.timeout_seconds)
                if not content.strip():
                    raise ValueError(f"web_read {KEYED_NAMES[settings.provider]} returned no text for {url}")
                page = WebPage(url=url, final_url=final_url, fetched_at=time.time(), media_type="text/markdown",
                               content=content, notice=f"由 {KEYED_NAMES[settings.provider]} 读取并转为 Markdown。")
                return store.save_web_page(scene, page), page
            final_url, content_type, body = await fetch_public(url, settings.timeout_seconds, _web_limit,
                                                               fake_ip_networks=fake_ip_networks,
                                                               public_dns_url=public_dns_url)
            fetched_at = time.time()
            media_type, content, notice = await _extract(final_url, content_type, body)
            page = WebPage(url=url, final_url=final_url, fetched_at=fetched_at,
                           media_type=media_type, content=content, notice=notice)
            return store.save_web_page(scene, page), page
    except TimeoutError as error:
        if deadline.expired():
            raise TimeoutError(f"web_read exceeded {settings.timeout_seconds} seconds") from error
        raise


def _worker() -> None:
    import trafilatura

    request = json.loads(sys.stdin.buffer.read())
    content = trafilatura.extract(
        request["html"], url=request["url"], output_format="markdown",
        include_links=True, include_tables=True, include_images=True,
        with_metadata=True,
    )
    if content is None or not content.strip():
        raise ValueError("trafilatura returned no readable article body")
    sys.stdout.buffer.write(content.encode("utf-8"))


if __name__ == "__main__":
    if sys.argv[1:] != ["extract"]:
        raise SystemExit("web_read worker expects extract")
    try:
        _worker()
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
