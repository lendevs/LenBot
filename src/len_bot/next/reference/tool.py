"""The ``knowledge`` tool: the current role's knowledge files and this chat's own files."""

from __future__ import annotations

import json
from string import Template
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..prompt_files import read_prompt
from .library import KnowledgeOwner, ReferenceChange, ReferenceLibrary

FILES_PAGE = 20
HITS_PAGE = 5
SEARCH_LIMIT = 50
READ_CHARS = 4000


class KnowledgeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # With no action: a query searches, a filename reads, otherwise list.
    action: Literal["list", "search", "read"] | None = None
    scope: Literal["all", "persona", "chat"] = "all"
    query: str | None = None
    filename: str | None = None
    offset: int = Field(default=0, ge=0, strict=True)

    @field_validator("query", "filename")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("query and filename must not be blank")
        return value

    @model_validator(mode="after")
    def operation_fields(self) -> KnowledgeArguments:
        if self.action is None:
            self.action = "search" if self.query is not None else "read" if self.filename is not None else "list"
        if self.action == "list":
            if self.query is not None or self.filename is not None:
                raise ValueError("list does not accept query or filename")
        elif self.action == "search":
            if self.query is None:
                raise ValueError("search requires query")
        elif self.filename is None or self.query is not None or self.scope == "all":
            raise ValueError("read requires scope persona or chat and filename, and does not accept query")
        return self


KNOWLEDGE_TOOL = {"type": "function", "function": {
    "name": "knowledge",
    "description": "查资料：scope=persona 是当前角色的设定资料，scope=chat 是本聊天的资料文件，默认 all 两边都查。"
                   "search 的 query 写 1 到 4 个关键词、用空格分开，可用 filename 限定文件，返回原文片段及文件名和位置，每页5条；"
                   "list 列出文件，每页20个；read 用结果里的 scope 和 filename 从 offset 字符位置起读4000字符。"
                   "按 next_offset 续页。",
    "parameters": KnowledgeArguments.model_json_schema(),
}}


def chat_name(scene: str) -> str:
    return "本群" if scene.split(":", 2)[1] == "group" else "这个私聊"


def changes_notice(scene: str, changes: list[ReferenceChange], time: str) -> str:
    """The conversation note for files the chat may have read before they changed."""
    lines = [f"- {'角色资料' if change.owner.startswith('persona:') else chat_name(scene) + '资料'} {change.path}："
             f"{'已更新' if change.action == 'updated' else '已删除'}" for change in changes]
    return Template(read_prompt("next_reference_changed.md")).substitute(time=time, changes="\n".join(lines)).strip()


def _scope(owner: str) -> str:
    return "persona" if owner.startswith("persona:") else "chat"


def _page(items: list[dict], offset: int, size: int) -> tuple[list[dict], int | None]:
    if offset > len(items):
        raise ValueError(f"offset {offset} exceeds result count {len(items)}")
    end = min(offset + size, len(items))
    return items[offset:end], end if end < len(items) else None


async def knowledge(library: ReferenceLibrary, scene: str, persona: KnowledgeOwner, persona_name: str,
                    arguments: KnowledgeArguments) -> str:
    if arguments.action == "list":
        files = []
        for item in await library.files(scene, persona, arguments.scope):
            entry = {"scope": _scope(item.owner), "filename": item.path}
            if item.error is not None:
                entry["error"] = item.error
            else:
                entry["chars"] = item.chars
            if item.pages is not None:
                entry["pages"] = item.pages
            if item.tags:
                entry["tags"] = list(item.tags)
            files.append(entry)
        page, next_offset = _page(files, arguments.offset, FILES_PAGE)
        result = {"action": "list", "offset": arguments.offset, "next_offset": next_offset, "files": page}
    elif arguments.action == "search":
        matches = []
        for hit in await library.search(scene, persona, arguments.query, scope=arguments.scope,
                                        filename=arguments.filename, limit=SEARCH_LIMIT):
            entry = {"scope": _scope(hit.owner), "filename": hit.path}
            if hit.page is not None:
                entry["page"] = hit.page
            if hit.heading:
                entry["heading"] = list(hit.heading)
            entry |= {"offset": hit.start_char, "matched": list(hit.matched), "text": hit.text}
            matches.append(entry)
        page, next_offset = _page(matches, arguments.offset, HITS_PAGE)
        result = {"action": "search", "query": arguments.query, "offset": arguments.offset,
                  "next_offset": next_offset, "matches": page}
        if arguments.filename is not None:
            result["filename"] = arguments.filename
    else:
        read = await library.read(scene, persona, arguments.scope, arguments.filename, arguments.offset, READ_CHARS)
        result = {"action": "read", "scope": arguments.scope, "filename": read.path, "offset": read.offset,
                  "total_chars": read.total_chars, "next_offset": read.next_offset, "text": read.text}
    return Template(read_prompt("next_knowledge.md")).substitute(
        persona_id=persona.id, persona_name=persona_name, chat=chat_name(scene),
        result=json.dumps(result, ensure_ascii=False, allow_nan=False),
    )
