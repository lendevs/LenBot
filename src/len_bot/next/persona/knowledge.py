"""Read one role's Markdown knowledge snapshot; the ``knowledge`` tool searches it through the reference index."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class PersonaDocument:
    content: str
    tags: tuple[str, ...]


def _frontmatter(path: Path, content: str) -> tuple[str, ...]:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return ()
    closing = next((position for position, line in enumerate(lines[1:], 1)
                    if line.rstrip("\r\n") == "---"), None)
    if closing is None:
        raise ValueError(f"{path}: unclosed YAML frontmatter; raw={content[:200]!r}")
    source = "".join(lines[1:closing])
    try:
        header = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise ValueError(f"{path}: invalid YAML frontmatter: {error}; raw={source[:200]!r}") from error
    if header is None:
        return ()
    if not isinstance(header, dict):
        raise ValueError(f"{path}: YAML frontmatter must be an object; raw={source[:200]!r}")
    if "tags" not in header:
        return ()
    tags = header["tags"]
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError(f"{path}: frontmatter tags must be a list of text; raw={source[:200]!r}")
    return tuple(tags)


def _document(path: Path) -> PersonaDocument:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{path}: cannot read knowledge file: {error}") from error
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as error:
        snippet = data[max(0, error.start - 30):error.end + 30]
        raise ValueError(f"{path}: invalid UTF-8: {error}; raw={snippet!r}") from error
    return parse_knowledge_document(path, content)


def parse_knowledge_document(path: Path, content: str) -> PersonaDocument:
    """The same frontmatter boundary for a disk source or an explicitly edited source."""
    return PersonaDocument(content=content, tags=_frontmatter(path, content))


def load_knowledge(persona_root: Path) -> dict[str, PersonaDocument]:
    """Load only actual files beneath knowledge/, preserving every source byte as text."""
    root = persona_root.resolve()
    directory = root / "knowledge"
    if not directory.exists() and not directory.is_symlink():
        return {}
    try:
        actual = directory.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{directory}: cannot resolve knowledge directory: {error}") from error
    if not actual.is_relative_to(root):
        raise ValueError(f"{directory}: knowledge directory points outside persona package: {actual}")
    if directory.is_symlink():
        raise ValueError(f"{directory}: knowledge directory symlink is not followed")
    if not directory.is_dir():
        raise ValueError(f"{directory}: knowledge path is not a directory")

    documents: dict[str, PersonaDocument] = {}

    def listing_error(error: OSError) -> None:
        raise ValueError(f"{error.filename or directory}: cannot list knowledge directory: {error}") from error

    for folder, _, filenames in os.walk(directory, followlinks=False, onerror=listing_error):
        for filename in filenames:
            if not filename.endswith(".md"):
                continue
            path = Path(folder) / filename
            try:
                target = path.resolve(strict=True)
            except OSError as error:
                raise ValueError(f"{path}: cannot resolve Markdown knowledge file: {error}") from error
            if not target.is_relative_to(actual):
                raise ValueError(f"{path}: Markdown file points outside knowledge directory: {target}")
            if not target.is_file():
                raise ValueError(f"{path}: Markdown knowledge path is not a regular file")
            documents[path.relative_to(directory).as_posix()] = _document(path)

    return dict(sorted(documents.items()))
