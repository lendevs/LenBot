"""Shared built frontend; each host registers only its own business routes."""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .errors import error_response


BUILT_PANEL = Path(__file__).parent / "static" / "dist"
FRONTEND = Path(__file__).parent / "frontend"


class PanelContext(BaseModel):
    mode: Literal["isolated", "isolated-multi", "setup"]
    home: str


def missing_build(dist: Path) -> str | None:
    """Why the built frontend cannot be served, or None when it can."""
    if (dist / "index.html").is_file():
        return None
    return (f"控制面板尚未构建：缺少 {dist / 'index.html'}。"
            f"请在 {FRONTEND} 执行 npm ci 和 npm run build，或通过 len-bot 启动器启动（源码检出时会自动构建）")


def mount_panel(app: FastAPI, *, mode: Literal["isolated", "isolated-multi", "setup"],
                home: str, assets_dir: Path | None = None) -> None:
    @app.get("/api/panel-context", response_model=PanelContext)
    async def panel_context():
        return {"mode": mode, "home": home}

    dist = BUILT_PANEL if assets_dir is None else assets_dir
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

    @app.get("/")
    async def index():
        problem = missing_build(dist)
        if problem is not None:
            return error_response(503, problem)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/{full_path:path}")
    async def unknown_path(full_path: str):
        return error_response(404, "接口不存在" if full_path.startswith("api/") else "资源不存在")
