"""A scene's reference files: listing with their index state, upload, import from group files, delete and
reading again."""

from collections.abc import Callable
from functools import partial
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
import httpx
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ...configuration.types import STRICT
from ...platform.adapter import PlatformCallError
from ...platform.platform_tools import group_file_url, group_files
from ...reference.sources import KINDS, MAX_FILE_BYTES, kind_of
from ...runtime.network import NetworkRuntime

TOO_LARGE = f"文件超过 {MAX_FILE_BYTES // 1_000_000}MB 上限"


class ReferenceFile(BaseModel):
    filename: str
    kind: str
    size: int
    modified: float
    status: Literal["processing", "indexed", "failed"]
    error: str | None
    chars: int | None
    pages: int | None
    chunks: int
    vectors: int


class ReferenceListing(BaseModel):
    scene: str
    files: list[ReferenceFile]
    processing: bool
    vectors: bool
    formats: list[str]
    max_bytes: int
    group_files: bool


class ReferenceTarget(BaseModel):
    model_config = STRICT
    filename: str


class GroupFile(BaseModel):
    file_id: str
    busid: int
    name: str
    size: int
    uploaded: int
    uploader: str | None
    supported: bool


class GroupFolder(BaseModel):
    folder_id: str
    name: str
    files: int


class GroupFiles(BaseModel):
    folder: str | None
    files: list[GroupFile]
    folders: list[GroupFolder]


class GroupFileTarget(BaseModel):
    model_config = STRICT
    file_id: str
    busid: int
    name: str


async def download(url: str, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """A group file from the address OneBot gave, refused once it passes the size limit."""
    async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=True, transport=transport) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_FILE_BYTES:
                    raise ValueError(TOO_LARGE)
    return bytes(data)


def register_host_reference(app: FastAPI, *, runtime: NetworkRuntime, user: Callable[[Request], str]) -> None:
    library = runtime.reference

    def configured(scene: str) -> None:
        if scene not in runtime.chats:
            raise HTTPException(404, "当前宿主未配置此场景")
        if library.directory(scene) is None:
            raise HTTPException(409, "没有实例目录，不能保存资料文件")

    def has_group_files(scene: str) -> bool:
        return runtime.config.onebot is not None and scene.split(":", 2)[1] == "group"

    def group(scene: str) -> str:
        configured(scene)
        if not has_group_files(scene):
            raise HTTPException(409, "这个聊天没有 QQ 群文件")
        return scene.split(":", 2)[2]

    def index(scene: str) -> None:
        chat = runtime.chats[scene]

        def done() -> None:
            # The knowledge tool appears with the scene's first file and goes with its last one.
            chat.set_external_tools(list(chat.toolset.external.values()))
            runtime.notify()

        library.schedule(scene, chat.persona, done)
        runtime.notify()

    async def listing(scene: str) -> dict:
        files = await library.scene_files(scene)
        if any(item.status == "processing" for item in files) and not library.processing(scene):
            # A file placed in the directory by hand is indexed once the panel sees it.
            index(scene)
        return {"scene": scene, "processing": library.processing(scene), "vectors": library.embedding is not None,
                "formats": sorted(KINDS), "max_bytes": MAX_FILE_BYTES, "group_files": has_group_files(scene),
                "files": [{"filename": item.path, "kind": item.kind, "size": item.size, "modified": item.modified,
                           "status": item.status, "error": item.error, "chars": item.chars, "pages": item.pages,
                           "chunks": item.chunks, "vectors": item.vectors} for item in files]}

    @app.get("/api/host/scenes/{scene}/reference", response_model=ReferenceListing)
    async def files(scene: str, _: str = Depends(user)):
        configured(scene)
        return await listing(scene)

    @app.post("/api/host/scenes/{scene}/reference", response_model=ReferenceListing)
    async def upload(scene: str, file: UploadFile = File(...), _: str = Depends(user)):
        configured(scene)
        try:
            data = await file.read(MAX_FILE_BYTES + 1)
            await run_in_threadpool(library.save, scene, file.filename or "", data)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        finally:
            await file.close()
        index(scene)
        return await listing(scene)

    @app.delete("/api/host/scenes/{scene}/reference", response_model=ReferenceListing)
    async def delete(scene: str, body: ReferenceTarget, _: str = Depends(user)):
        configured(scene)
        try:
            await run_in_threadpool(library.delete, scene, body.filename)
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        index(scene)
        return await listing(scene)

    @app.post("/api/host/scenes/{scene}/reference/reprocess", response_model=ReferenceListing)
    async def reprocess(scene: str, body: ReferenceTarget, _: str = Depends(user)):
        configured(scene)
        try:
            await run_in_threadpool(library.reprocess, scene, body.filename)
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        index(scene)
        return await listing(scene)

    @app.get("/api/host/scenes/{scene}/reference/group-files", response_model=GroupFiles)
    async def group_folder(scene: str, folder: str | None = None, _: str = Depends(user)):
        group_id = group(scene)
        try:
            found = await group_files(partial(runtime.platform_call, scene=scene), group_id, folder)
        except (PlatformCallError, ValueError) as error:
            raise HTTPException(502, f"读取群文件失败：{error}") from error
        return {"folder": folder, "folders": found["folders"],
                "files": [item | {"supported": kind_of(item["name"]) is not None and item["size"] <= MAX_FILE_BYTES}
                          for item in found["files"]]}

    @app.post("/api/host/scenes/{scene}/reference/group-files", response_model=ReferenceListing)
    async def import_group_file(scene: str, body: GroupFileTarget, _: str = Depends(user)):
        group_id = group(scene)
        if kind_of(body.name) is None:
            raise HTTPException(422, "只支持 Markdown、纯文本和 PDF")
        try:
            url = await group_file_url(partial(runtime.platform_call, scene=scene), group_id, body.file_id, body.busid)
        except (PlatformCallError, ValueError) as error:
            raise HTTPException(502, f"获取群文件下载地址失败：{error}") from error
        try:
            data = await download(url)
        except httpx.HTTPError as error:
            raise HTTPException(502, f"下载群文件失败：{type(error).__name__}: {error}") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        try:
            await run_in_threadpool(library.save, scene, body.name, data)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        index(scene)
        return await listing(scene)
