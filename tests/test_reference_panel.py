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


def _group_files(files: list[dict], folders: list[dict] | None) -> dict:
    return {"status": "ok", "retcode": 0, "data": {"files": files, "folders": folders}}


# Field sets as NapCat (size and file_size, creator_name) and SnowLuma (file_size, create_name) return them.
NAPCAT_FILE = {"group_id": 80001, "file_id": "/napcat-uuid", "file_name": "活动手册.md", "busid": 102, "size": 40,
               "file_size": 40, "upload_time": 1792000000, "dead_time": 0, "modify_time": 1792000000,
               "download_times": 3, "uploader": 70002, "uploader_name": "群友乙"}
SNOWLUMA_FOLDER = {"group_id": 80001, "folder_id": "/folder-1", "folder_name": "课程", "create_time": 1792000000,
                   "creator": 70002, "create_name": "群友乙", "total_file_count": 2}


@pytest.mark.asyncio
async def test_group_files_are_listed_by_folder_and_imported_into_the_reference_directory(tmp_path, monkeypatch):
    from len_bot.next.panel.routes import reference as routes

    calls = []

    async def call(action: str, params: dict) -> dict:
        calls.append((action, params))
        if action == "get_group_root_files":
            return _group_files([NAPCAT_FILE, NAPCAT_FILE | {"file_id": "/deck", "file_name": "slides.pptx"}],
                                [SNOWLUMA_FOLDER])
        if action == "get_group_files_by_folder":
            return _group_files([], None)
        assert action == "get_group_file_url"
        return {"status": "ok", "retcode": 0, "data": {"url": "https://files.example/ftn_handler/abc/?fname="}}

    async def download(url: str) -> bytes:
        assert url == "https://files.example/ftn_handler/abc/?fname="
        return "# 活动\n\n报名截止十一月三日。\n".encode()

    monkeypatch.setattr(routes, "download", download)
    async with panel(tmp_path) as (client, runtime):
        runtime.platform.call = call
        assert (await client.get(PATH)).json()["group_files"] is True
        root = (await client.get(f"{PATH}/group-files")).json()
        assert [(item["name"], item["supported"], item["uploader"]) for item in root["files"]] == [
            ("活动手册.md", True, "群友乙"), ("slides.pptx", False, "群友乙")]
        assert root["folders"] == [{"folder_id": "/folder-1", "name": "课程", "files": 2}]
        inside = (await client.get(f"{PATH}/group-files", params={"folder": "/folder-1"})).json()
        assert inside == {"folder": "/folder-1", "files": [], "folders": []}
        assert calls[1] == ("get_group_files_by_folder", {"group_id": 80001, "folder_id": "/folder-1",
                                                          "file_count": 200})

        imported = await client.post(f"{PATH}/group-files", json={"file_id": "/napcat-uuid", "busid": 102,
                                                                  "name": "活动手册.md"})
        assert imported.status_code == 200, imported.text
        assert calls[-1] == ("get_group_file_url", {"group_id": 80001, "file_id": "/napcat-uuid", "busid": 102})
        [item] = (await settled(client))["files"]
        assert (item["filename"], item["status"]) == ("活动手册.md", "indexed")
        assert "十一月三日" in await search(runtime, SCENE, "报名 截止")

        refused = await client.post(f"{PATH}/group-files", json={"file_id": "/deck", "busid": 102,
                                                                 "name": "slides.pptx"})
        assert refused.status_code == 422 and calls[-1][0] == "get_group_file_url" and len(calls) == 3


@pytest.mark.asyncio
async def test_group_file_failures_name_the_step_and_a_private_chat_has_no_group_files(tmp_path):
    async def call(action: str, params: dict) -> dict:
        if action == "get_group_root_files":
            return {"status": "failed", "retcode": 1404, "wording": "不支持的动作", "data": None}
        return {"status": "ok", "retcode": 0, "data": {}}

    async with panel(tmp_path) as (client, runtime):
        runtime.platform.call = call
        listed = await client.get(f"{PATH}/group-files")
        assert listed.status_code == 502 and "读取群文件失败" in listed.json()["detail"]["message"]
        assert "不支持的动作" in listed.json()["detail"]["message"]
        url = await client.post(f"{PATH}/group-files", json={"file_id": "/x", "busid": 102, "name": "a.md"})
        assert url.status_code == 502 and "下载地址" in url.json()["detail"]["message"]
        assert (await client.get(PATH)).json()["files"] == []


@pytest.mark.asyncio
async def test_download_stops_at_the_size_limit():
    import httpx

    from len_bot.next.panel.routes.reference import download
    from len_bot.next.reference.sources import MAX_FILE_BYTES

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/large":
            return httpx.Response(200, content=b"x" * (MAX_FILE_BYTES + 1))
        if request.url.path == "/gone":
            return httpx.Response(404)
        return httpx.Response(200, content=b"ok")

    transport = httpx.MockTransport(answer)
    assert await download("https://files.example/small", transport) == b"ok"
    with pytest.raises(ValueError, match="上限"):
        await download("https://files.example/large", transport)
    with pytest.raises(httpx.HTTPStatusError):
        await download("https://files.example/gone", transport)
