"""The panel manages a group's reference files; the chat finds them, hears about changes and loses them on delete.

Upload → processing → indexed → the knowledge tool appears and answers in that group only → an update
is told to the conversation before the next request → a delete removes the file from lookups.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest

from len_bot.next.config import load_host_config
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel, ToolCall
from len_bot.next.panel.app import create_app
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.lifecycle import HostLifecycle
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_next_host_manage_permissions_config import instance

SCENE, OTHER = "onebot:group:80001", "onebot:group:80002"
PATH = f"/api/host/scenes/{SCENE}/reference"


@asynccontextmanager
async def panel(root, *, knowledge: str | None = None):
    instance(root)
    if knowledge is not None:
        (root / "persona/knowledge").mkdir()
        (root / "persona/knowledge/设定.md").write_text(knowledge, encoding="utf-8")
    persona = root / "persona/persona.yaml"
    persona.write_text(persona.read_text().replace("tools: [say, tool_search, host_manage]",
                                                   "tools: [say, tool_search, knowledge]"))
    config = load_host_config(root)
    role = load_persona(config.scenes[SCENE].persona)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings("mind")) as mind, open_memory(config, store) as memory:
            runtime = NetworkRuntime(config, [(config.scene_config(scene), role) for scene in config.scenes],
                                     store, mind, memory=memory, lifecycle=HostLifecycle())
            runtime.accepting = True
            app = create_app(config, runtime, root=root)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                assert (await client.post("/api/auth/login", json={"username": "operator",
                                                                   "password": "fixture-password"})).status_code == 200
                try:
                    yield client, runtime
                finally:
                    await runtime.reference.close()


async def settled(client) -> dict:
    for _ in range(200):
        body = (await client.get(PATH)).json()
        if not body["processing"] and all(item["status"] != "processing" for item in body["files"]):
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(body)


async def search(runtime, scene: str, query: str) -> str:
    async def wait_for_messages(_: float) -> str:
        return "unused"
    chat = runtime.chats[scene]
    chat.toolset.discovered_tools = {"knowledge"}
    call = ToolCall(id="synthetic-search", name="knowledge", arguments={"query": query})
    content, _, _ = await chat.toolset.execute("unused-turn", call, wait_for_messages)
    return content


@pytest.mark.asyncio
async def test_upload_index_answer_update_and_delete(tmp_path):
    async with panel(tmp_path) as (client, runtime):
        chat = runtime.chats[SCENE]
        assert "knowledge" not in chat.toolset.allowed_tool_names
        empty = (await client.get(PATH)).json()
        assert empty["files"] == [] and empty["formats"] == [".markdown", ".md", ".pdf", ".txt"]

        uploaded = await client.post(PATH, files={"file": ("活动手册.md", "# 活动\n\n## 报名\n\n报名截止十一月三日。\n".encode())})
        assert uploaded.status_code == 200, uploaded.text
        body = await settled(client)
        [item] = body["files"]
        assert (item["filename"], item["status"], item["chunks"], item["error"]) == ("活动手册.md", "indexed", 1, None)
        assert "knowledge" in chat.toolset.allowed_tool_names
        assert "十一月三日" in await search(runtime, SCENE, "报名 截止")
        # The other group has no files of its own, so it is not offered the tool and finds nothing.
        assert "knowledge" not in runtime.chats[OTHER].toolset.allowed_tool_names
        assert await runtime.reference.search(OTHER, runtime.chats[OTHER].persona, "报名 截止") == []

        # The first turn only marks where the conversation starts; a later update is told once.
        await chat.announce_reference(runtime.store.now())
        replaced = await client.post(PATH, files={"file": ("活动手册.md", "# 活动\n\n## 报名\n\n报名截止十一月五日。\n".encode())})
        assert replaced.status_code == 200
        await settled(client)
        await chat.announce_reference(runtime.store.now())
        await chat.announce_reference(runtime.store.now())
        _, entries = runtime.store.active_history(SCENE)
        notices = [entry["content"] for _, entry in entries if "资料有变化" in str(entry.get("content"))]
        assert len(notices) == 1 and "本群资料 活动手册.md：已更新" in notices[0]
        assert "十一月五日" in await search(runtime, SCENE, "报名")

        refused = await client.post(PATH, files={"file": ("slides.pptx", b"x")})
        assert refused.status_code == 422 and "只支持" in refused.json()["detail"]["message"]
        assert (await client.post(f"{PATH}/reprocess", json={"filename": "活动手册.md"})).status_code == 200
        assert (await settled(client))["files"][0]["status"] == "indexed"

        deleted = await client.request("DELETE", PATH, json={"filename": "活动手册.md"})
        assert deleted.status_code == 200
        assert (await settled(client))["files"] == []
        assert "knowledge" not in chat.toolset.allowed_tool_names
        await chat.announce_reference(runtime.store.now())
        _, entries = runtime.store.active_history(SCENE)
        assert "本群资料 活动手册.md：已删除" in json.dumps([entry for _, entry in entries], ensure_ascii=False)
        assert (await client.request("DELETE", PATH, json={"filename": "活动手册.md"})).status_code == 404


@pytest.mark.asyncio
async def test_a_file_placed_by_hand_is_indexed_when_the_panel_lists_it_and_a_failure_shows(tmp_path):
    async with panel(tmp_path) as (client, runtime):
        directory = runtime.reference.directory(SCENE)
        directory.mkdir(parents=True)
        (directory / "通知.md").write_text("周六在东门集合。\n", encoding="utf-8")
        (directory / "坏的.pdf").write_bytes(b"%PDF-1.4 broken")
        assert {item["status"] for item in (await client.get(PATH)).json()["files"]} == {"processing"}
        files = {item["filename"]: item for item in (await settled(client))["files"]}
        assert files["通知.md"]["status"] == "indexed"
        assert files["坏的.pdf"]["status"] == "failed" and "PDF无法读取" in files["坏的.pdf"]["error"]
        assert (await client.get("/api/host/scenes/onebot:group:99999/reference")).status_code == 404


@pytest.mark.asyncio
async def test_the_role_knowledge_listing_shows_each_file_index_state(tmp_path):
    async with panel(tmp_path, knowledge="# 设定\n\n喜欢画绘本。\n\n## 口味\n\n不吃辣。\n") as (client, runtime):
        [role] = (await client.get("/api/host/personas")).json()["roles"]
        [file] = (await client.get(f"/api/host/personas/{role['key']}/knowledge")).json()["files"]
        assert (file["filename"], file["index"], file["chunks"], file["vectors"]) == ("设定.md", "indexed", 2, 0)
