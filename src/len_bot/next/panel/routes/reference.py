"""A scene's reference files: listing with their index state, upload, delete and reading again."""

from collections.abc import Callable
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ...configuration.types import STRICT
from ...reference.sources import KINDS, MAX_FILE_BYTES
from ...runtime.network import NetworkRuntime


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


class ReferenceTarget(BaseModel):
    model_config = STRICT
    filename: str


def register_host_reference(app: FastAPI, *, runtime: NetworkRuntime, user: Callable[[Request], str]) -> None:
    library = runtime.reference

    def configured(scene: str) -> None:
        if scene not in runtime.chats:
            raise HTTPException(404, "当前宿主未配置此场景")
        if library.directory(scene) is None:
            raise HTTPException(409, "没有实例目录，不能保存资料文件")

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
                "formats": sorted(KINDS), "max_bytes": MAX_FILE_BYTES,
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
