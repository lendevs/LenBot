"""The reference index answers the ``knowledge`` tool from the role's knowledge and the chat's own files.

Each lookup follows the sources as they are now: a changed file is indexed again, a removed one is no
longer found, and a chat's files stay inside that chat.
"""

from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from len_bot.next.persona.knowledge import PersonaDocument
from len_bot.next.reference.library import ReferenceLibrary
from len_bot.next.reference.sources import CHUNK_CHARS
from len_bot.next.reference.tool import KnowledgeArguments, knowledge

SCENE, OTHER = "onebot:group:80001", "onebot:group:80002"
ROLE = SimpleNamespace(id="role", knowledge={
    "设定.md": PersonaDocument("# 角色\n\n喜欢画绘本，最近在画月亮。\n", ()),
})


def pdf(pages: list[str]) -> bytes:
    """A minimal PDF with one Helvetica line per page; an empty string is a blank page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
               + f"] /Count {len(pages)} >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for index, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * index} 0 R >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    data, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n{body}\nendobj\n".encode()
    table = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    data += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n".encode()
    return bytes(data)


def files(library: ReferenceLibrary, scene: str = SCENE) -> Path:
    directory = library.directory(scene)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def ask(library: ReferenceLibrary, scene: str = SCENE, persona=ROLE, **arguments) -> dict:
    page = await knowledge(library, scene, persona, "合成角色", KnowledgeArguments(**arguments))
    return json.loads(page.split("\n\n", 1)[1])


@pytest.mark.asyncio
async def test_a_long_document_is_found_in_the_middle_with_its_section(tmp_path):
    library = ReferenceLibrary(tmp_path)
    filler = "\n\n".join(f"第 {number} 段是普通的说明文字，和集合地点无关。" for number in range(200))
    (files(library) / "手册.md").write_text(
        f"# 手册\n\n## 前言\n\n{filler}\n\n## 集合\n\n{filler}\n\n周六早上九点在东门集合。\n\n{filler}\n", encoding="utf-8")
    # Every filler paragraph holds one of the keywords; the chunk with both comes first.
    hit = (await ask(library, action="search", query="东门 集合"))["matches"][0]
    assert (hit["scope"], hit["filename"], hit["heading"]) == ("chat", "手册.md", ["手册", "集合"])
    assert hit["matched"] == ["东门", "集合"]
    assert "周六早上九点在东门集合" in hit["text"] and len(hit["text"]) <= CHUNK_CHARS
    page = await ask(library, action="read", scope="chat", filename="手册.md", offset=hit["offset"])
    assert page["text"].startswith(hit["text"])


@pytest.mark.asyncio
async def test_pdf_pages_text_files_and_failures(tmp_path):
    library = ReferenceLibrary(tmp_path)
    directory = files(library)
    (directory / "guide.pdf").write_bytes(pdf(["Welcome to the club", "", "The essay deadline is Friday noon"]))
    (directory / "scan.pdf").write_bytes(b"%PDF-1.4 not a document")
    (directory / "旧通知.txt").write_bytes("社团会费每学期五十元。".encode("gb18030"))
    (directory / "bad.md").write_bytes(b"# \xff\xfe")
    (directory / "notes.docx").write_bytes(b"unsupported")
    (directory / ".hidden.md").write_text("隐藏文件", encoding="utf-8")
    (directory / "link.md").symlink_to(directory / "旧通知.txt")
    listing = {item["filename"]: item for item in (await ask(library, action="list", scope="chat"))["files"]}
    assert set(listing) == {"bad.md", "guide.pdf", "scan.pdf", "旧通知.txt"}
    assert listing["guide.pdf"]["pages"] == 3 and "PDF无法读取" in listing["scan.pdf"]["error"]
    assert "不是 UTF-8 文本" in listing["bad.md"]["error"]
    [hit] = (await ask(library, action="search", query="deadline essay"))["matches"]
    assert hit["page"] == 3 and hit["text"].startswith("[第 3 页]\nThe essay deadline")
    assert (await ask(library, action="search", query="会费"))["matches"][0]["text"] == "社团会费每学期五十元。"
    with pytest.raises(ValueError, match="没有建立索引"):
        await ask(library, action="read", scope="chat", filename="scan.pdf")


@pytest.mark.asyncio
async def test_lookups_follow_changed_and_removed_files(tmp_path):
    library = ReferenceLibrary(tmp_path)
    path = files(library) / "通知.md"
    path.write_text("报名截止时间是十一月三日。\n", encoding="utf-8")
    assert (await ask(library, action="search", query="十一月三日"))["matches"]
    path.write_text("报名截止时间改到十一月十日。\n", encoding="utf-8")
    assert not (await ask(library, action="search", query="十一月三日"))["matches"]
    assert (await ask(library, action="search", query="十一月十日"))["matches"]
    os.utime(path, ns=(1, 1))
    assert (await ask(library, action="search", query="十一月十日"))["matches"]
    path.unlink()
    assert not (await ask(library, action="search", query="报名"))["matches"]
    with closing(sqlite3.connect(library.index)) as db:
        assert db.execute("SELECT count(*) FROM reference_chunks").fetchone()[0] == 1  # the role's file


@pytest.mark.asyncio
async def test_a_chat_sees_its_own_files_and_the_knowledge_of_its_role(tmp_path):
    library = ReferenceLibrary(tmp_path)
    (files(library) / "通知.md").write_text("周六在东门集合。\n", encoding="utf-8")
    other_role = SimpleNamespace(id="other", knowledge={"设定.md": PersonaDocument("另一个角色的月亮设定。\n", ())})
    assert [item["scope"] for item in (await ask(library, action="search", query="东门"))["matches"]] == ["chat"]
    assert not (await ask(library, OTHER, action="search", query="东门"))["matches"]
    assert (await ask(library, OTHER, action="search", query="绘本"))["matches"][0]["scope"] == "persona"
    found = (await ask(library, persona=other_role, action="search", query="月亮"))["matches"]
    assert [item["text"] for item in found] == ["另一个角色的月亮设定。\n"]
    assert not (await ask(library, action="search", scope="persona", query="东门"))["matches"]
    with pytest.raises(ValueError, match="没有资料文件"):
        await ask(library, OTHER, action="read", scope="chat", filename="通知.md")


@pytest.mark.asyncio
async def test_a_chunk_needs_at_least_half_of_the_keywords(tmp_path):
    library = ReferenceLibrary(tmp_path)
    directory = files(library)
    (directory / "a.md").write_text("报名截止在周五。\n", encoding="utf-8")
    (directory / "b.md").write_text("报名表在群文件里，截止前交到东门。\n", encoding="utf-8")
    matches = (await ask(library, action="search", query="报名 截止 东门"))["matches"]
    assert [(item["filename"], item["matched"]) for item in matches] == [
        ("b.md", ["报名", "截止", "东门"]), ("a.md", ["报名", "截止"])]
    assert not (await ask(library, action="search", query="报名 火星 基地"))["matches"]


@pytest.mark.asyncio
async def test_an_index_of_another_schema_is_built_again(tmp_path):
    library = ReferenceLibrary(tmp_path)
    library.index.parent.mkdir(parents=True)
    with closing(sqlite3.connect(library.index)) as db:
        db.execute("CREATE TABLE reference_sources (id INTEGER PRIMARY KEY, owner TEXT)")
        db.execute("INSERT INTO reference_sources(owner) VALUES ('scene:old')")
        db.commit()
    assert (await ask(library, action="search", query="绘本"))["matches"]
    with closing(sqlite3.connect(library.index)) as db:
        assert [row[0] for row in db.execute("SELECT owner FROM reference_sources")] == ["persona:role"]


@pytest.mark.asyncio
async def test_without_an_instance_directory_only_the_role_knowledge_is_searched(tmp_path):
    library = ReferenceLibrary(None)
    assert library.directory(SCENE) is None
    assert (await ask(library, action="search", query="绘本"))["matches"][0]["filename"] == "设定.md"
    assert [item["scope"] for item in (await ask(library, action="list"))["files"]] == ["persona"]


def test_read_names_one_scope_and_a_file():
    for arguments in ({"action": "read", "filename": "a.md"}, {"action": "read", "scope": "chat"},
                      {"action": "search"}, {"action": "list", "query": "x"}):
        with pytest.raises(ValidationError):
            KnowledgeArguments(**arguments)


@pytest.mark.asyncio
async def test_the_tool_is_offered_once_the_chat_has_files(tmp_path):
    from len_bot.next.chat.session import Chat
    from len_bot.next.models.client import ChatModel, ToolCall
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.storage.store import Store
    from test_next_persona_permissions import _config, _package

    async def wait_for_messages(_: float) -> str:
        return "unused"

    role = _package(tmp_path, "plain", tools="all", documents={})
    config = _config(tmp_path / "instance", role)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings("mind")) as mind:
            chat = Chat(config, load_persona(role), store, mind)
            assert "knowledge" not in chat.toolset.allowed_tool_names
            directory = ReferenceLibrary(config._instance_root).directory(config.scene)
            directory.mkdir(parents=True)
            (directory / "通知.md").write_text("周六在东门集合。\n", encoding="utf-8")
            chat = Chat(config, load_persona(role), store, mind)
            assert "knowledge" in chat.toolset.allowed_tool_names
            store.save_discovered_tools(config.scene, ["knowledge"])
            chat = Chat(config, load_persona(role), store, mind)
            call = ToolCall(id="synthetic-search", name="knowledge", arguments={"action": "search", "query": "东门"})
            content, _, _ = await chat.toolset.execute("unused-turn", call, wait_for_messages)
    assert "来自本群的资料文件" in content and "周六在东门集合" in content
