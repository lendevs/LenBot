"""Bounded PDFium reads in a killable child process, never in the bot loop."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import sys

MAX_PDF_BYTES = 10_000_000
MAX_PAGES = 100
MAX_TEXT = 200_000
# Reference files are read once when they are indexed, so they get larger bounds.
REFERENCE_PDF_BYTES = 50_000_000
REFERENCE_PAGES = 2000
REFERENCE_TEXT = 5_000_000
REFERENCE_CPU_SECONDS = 60


async def read_pdf(data: bytes, *, page: int | None = None) -> dict:
    if len(data) > MAX_PDF_BYTES:
        raise ValueError('PDF超过10MB上限')
    if page is not None and (type(page) is not int or not 1 <= page <= MAX_PAGES):
        raise ValueError('PDF页码须为1至100')
    return await _child(data, 'text' if page is None else str(page), timeout=12)


async def read_pdf_pages(data: bytes) -> list[str]:
    """The text layer of every page, for the reference index."""
    if len(data) > REFERENCE_PDF_BYTES:
        raise ValueError('PDF超过50MB上限')
    return (await _child(data, 'pages', timeout=REFERENCE_CPU_SECONDS + 10))['pages']


async def _child(data: bytes, mode: str, *, timeout: float) -> dict:
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', __name__,
        mode, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(data), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError('PDF无法读取：'+stderr.decode(errors='replace')[-300:].strip())
    return json.loads(stdout)


def _pages(data):
    import pypdfium2 as pdfium
    pages, remaining = [], REFERENCE_TEXT
    with pdfium.PdfDocument(data) as document:
        count = len(document)
        if not 1 <= count <= REFERENCE_PAGES:
            raise ValueError(f'PDF须为1至{REFERENCE_PAGES}页')
        for index in range(count):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded()
                finally:
                    text_page.close()
            finally:
                page.close()
            remaining -= len(text)
            if remaining < 0:
                raise ValueError(f'PDF文字超过{REFERENCE_TEXT}字上限')
            pages.append(text)
    return {'pages': pages}


def _read(data, page_number):
    import pypdfium2 as pdfium
    if len(data) > MAX_PDF_BYTES:
        raise ValueError('PDF超过10MB上限')
    with pdfium.PdfDocument(data) as document:
        count = len(document)
        if not 1 <= count <= MAX_PAGES:
            raise ValueError('PDF须为1至100页')
        if page_number is not None:
            if not 1 <= page_number <= count:
                raise ValueError(f'PDF只有{count}页')
            page = document[page_number - 1]
            try:
                width, height = page.get_size()
                if not all(math.isfinite(v) and 0 < v < 100_000 for v in (width, height)):
                    raise ValueError('PDF页面尺寸不合法')
                bitmap = page.render(scale=min(2.5, 2048 / max(width, height)))
                try:
                    output = io.BytesIO()
                    bitmap.to_pil().convert('RGB').save(output, format='PNG')
                finally:
                    bitmap.close()
            finally:
                page.close()
            return {'page_count': count, 'page': page_number,
                    'png_base64': base64.b64encode(output.getvalue()).decode()}
        chunks, remaining, has_text = [], MAX_TEXT, False
        for index in range(count):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded()
                finally:
                    text_page.close()
            finally:
                page.close()
            chunks.append(f'\n[PDF 第 {index + 1} / {count} 页]\n'+text[:remaining])
            has_text = has_text or bool(text.strip())
            remaining -= min(len(text), remaining)
            if remaining <= 0:
                break
        return {'page_count': count, 'text': ''.join(chunks), 'truncated': remaining <= 0,
                'pages_extracted': len(chunks), 'has_text': has_text}


if __name__ == '__main__':
    try:
        reference = sys.argv[1] == 'pages'
        if sys.platform != 'win32':
            import resource
            seconds = REFERENCE_CPU_SECONDS if reference else 8
            resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
        if reference:
            result = _pages(sys.stdin.buffer.read(REFERENCE_PDF_BYTES + 1))
        else:
            result = _read(sys.stdin.buffer.read(MAX_PDF_BYTES + 1), None if sys.argv[1] == 'text' else int(sys.argv[1]))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
