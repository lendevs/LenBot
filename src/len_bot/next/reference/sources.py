"""Reference sources: a scene's file directory, the text of each file and its retrieval chunks.

Offsets refer to the extracted text. For Markdown and plain text that is the file's own text; a PDF's
text is its pages in order, each after a ``[第 N 页]`` line.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from ..memory.local import scope_directory
from ..memory.sections import split_sections
from ..tools.pdf_read import REFERENCE_PDF_BYTES, read_pdf_pages

KINDS = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".pdf": "pdf"}
MAX_FILE_BYTES = REFERENCE_PDF_BYTES
MAX_TEXT_BYTES = 10_000_000
CHUNK_CHARS = 600


@dataclass(frozen=True, slots=True)
class Extracted:
    kind: str
    text: str
    # The extracted-text offset where each PDF page begins.
    pages: tuple[int, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Chunk:
    heading: tuple[str, ...]
    page: int | None
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class FoundFile:
    file: Path
    size: int
    modified_ns: int


def scene_directory(root: Path | None, scene: str) -> Path | None:
    """Where a scene's own reference files live in the instance."""
    if root is None:
        return None
    return root / "state" / "reference" / "scenes" / scope_directory(scene)


def kind_of(path: str) -> str | None:
    return KINDS.get(os.path.splitext(path)[1].casefold())


def scan(directory: Path | None) -> dict[str, FoundFile]:
    """Regular files of a supported kind; links, hidden names and other kinds are left out."""
    if directory is None or directory.is_symlink() or not directory.is_dir():
        return {}
    found = {}
    for folder, folders, filenames in os.walk(directory, followlinks=False):
        folders[:] = [name for name in folders if not name.startswith(".")]
        for filename in filenames:
            path = Path(folder) / filename
            if filename.startswith(".") or kind_of(filename) is None or path.is_symlink():
                continue
            status = path.stat()
            found[path.relative_to(directory).as_posix()] = FoundFile(path, status.st_size, status.st_mtime_ns)
    return dict(sorted(found.items()))


def has_files(directory: Path | None) -> bool:
    return bool(scan(directory))


def _decode(data: bytes, kind: str) -> str:
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError(f"文本文件超过 {MAX_TEXT_BYTES // 1_000_000}MB 上限")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        if kind != "text":
            raise ValueError(f"不是 UTF-8 文本（第 {error.start} 字节）") from error
    # Plain text saved on Chinese Windows is often GB18030.
    try:
        return data.decode("gb18030")
    except UnicodeDecodeError as error:
        raise ValueError(f"不是 UTF-8 或 GB18030 文本（第 {error.start} 字节）") from error


async def extract(path: str, data: bytes) -> Extracted:
    kind = kind_of(path)
    if kind is None:
        raise ValueError(f"不支持的文件类型：{path}")
    if kind != "pdf":
        return Extracted(kind, _decode(data, kind))
    pages = [page.replace("\r\n", "\n").replace("\r", "\n").strip() for page in await read_pdf_pages(data)]
    if not any(pages):
        raise ValueError("PDF 没有文字层")
    parts, starts, length = [], [], 0
    for number, page in enumerate(pages, 1):
        part = f"[第 {number} 页]\n{page}\n\n"
        starts.append(length)
        parts.append(part)
        length += len(part)
    return Extracted("pdf", "".join(parts), tuple(starts))


def pieces(text: str, start: int, end: int, limit: int = CHUNK_CHARS) -> list[tuple[int, int]]:
    """Cut ``text[start:end]`` into ranges of at most ``limit`` characters at paragraph or line ends."""
    ranges = []
    while end - start > limit:
        window = text[start:start + limit]
        cut = window.rfind("\n\n") + 2
        if cut < limit // 2:
            cut = window.rfind("\n") + 1
        if cut < limit // 2:
            cut = limit
        if window[:cut].strip():
            ranges.append((start, start + cut))
        start += cut
    if text[start:end].strip():
        ranges.append((start, end))
    return ranges


def chunks(extracted: Extracted) -> list[Chunk]:
    text = extracted.text
    if extracted.kind == "markdown":
        return [Chunk(section.heading, None, start, end) for section in split_sections(text)
                for start, end in pieces(text, section.start_char, section.end_char)]
    if extracted.kind == "pdf":
        bounds = [*extracted.pages, len(text)]
        # A blank page holds only its page line.
        return [Chunk((), number, start, end) for number, (first, last) in enumerate(zip(bounds, bounds[1:]), 1)
                if text[first:last].strip() != f"[第 {number} 页]"
                for start, end in pieces(text, first, last)]
    return [Chunk((), None, start, end) for start, end in pieces(text, 0, len(text))]
