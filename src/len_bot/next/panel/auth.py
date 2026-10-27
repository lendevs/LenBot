"""Authentication and change notification shared by the isolated panels."""

from __future__ import annotations

import asyncio
import hmac
import socket
import struct
import time
from pathlib import Path
from urllib.parse import urlsplit
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.requests import HTTPConnection

from len_bot.web.errors import error_response, install_panel_errors
from len_bot.web.auth import (
    clear_login_failures, create_session, login_blocked, record_login_failure,
    revoke_session, session_user, verify_password,
)
from . import responses
from ..configuration.maintenance import PanelSettings
from ..configuration.types import STRICT
from ..runtime.events import EventHub


class Login(BaseModel):
    model_config = STRICT
    username: str
    password: str = Field(repr=False)


def cookie_name(connection: HTTPConnection) -> str:
    port = connection.url.port
    if port is None:
        port = 443 if connection.url.scheme in {"https", "wss"} else 80
    return f"lenbot_session_p{port}"


def default_gateway(routes: Path = Path('/proc/net/route')) -> str | None:
    """The IPv4 default gateway in the Linux routing table; None elsewhere."""
    try:
        lines = routes.read_text(encoding='ascii').splitlines()[1:]
    except (OSError, UnicodeDecodeError):
        return None
    for line in lines:
        fields = line.split()
        # Columns: Iface Destination Gateway Flags ...; addresses are little-endian hex, flag 0x2 is RTF_GATEWAY.
        if len(fields) > 3 and fields[1] == '00000000' and int(fields[3], 16) & 0x2:
            return socket.inet_ntoa(struct.pack('<I', int(fields[2], 16)))
    return None


def trusted_proxies(settings: PanelSettings, *, container: bool) -> list[str]:
    """Peers whose X-Forwarded-For and X-Forwarded-Proto decide the client address and scheme.

    In the container every connection through the published port arrives from the Docker network
    gateway. Compose publishes the panel only on the host's 127.0.0.1, so the gateway stands for that
    host the way 127.0.0.1 does outside a container, and a reverse proxy on it works the same way.
    """
    gateway = default_gateway() if container else None
    return [*settings.trusted_proxies, *([gateway] if gateway and gateway not in settings.trusted_proxies else [])]


def require_panel_origin(connection: HTTPConnection) -> None:
    origin = connection.headers.get('origin')
    if origin is None:
        return
    url = urlsplit(str(connection.url))
    scheme = {'ws': 'http', 'wss': 'https'}.get(url.scheme, url.scheme)
    if origin != f'{scheme}://{url.netloc}':
        raise HTTPException(403, '面板请求必须来自当前面板地址')


def install_panel_auth(app: FastAPI, settings: PanelSettings, *,
                       on_logout: Callable[[], None]) -> Callable[[Request], str]:
    install_panel_errors(app)
    last_login_at: float | None = None

    @app.middleware('http')
    async def same_origin(request: Request, call_next):
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            try:
                require_panel_origin(request)
            except HTTPException as error:
                return error_response(error.status_code, error.detail, headers=error.headers)
        return await call_next(request)

    def user(request: Request) -> str:
        return session_user(request.cookies.get(cookie_name(request)))

    @app.post("/api/auth/login", response_model=responses.LoginResult, response_model_exclude_unset=True)
    async def login(item: Login, request: Request, response: Response):
        nonlocal last_login_at
        key = f"isolated:{request.client.host if request.client is not None else 'local'}"
        # A blocked address is refused before the password is checked: answering a correct guess with 200
        # while wrong ones get 429 would leave the guessing loop as fast as before.
        if login_blocked(key):
            raise HTTPException(429, "登录尝试过于频繁，请稍后再试")
        record_login_failure(key)
        password_valid = await asyncio.to_thread(verify_password, item.password, settings.password_hash)
        valid = hmac.compare_digest(item.username.encode('utf-8'), settings.username.encode('utf-8')) and password_valid
        if not valid:
            raise HTTPException(401, "Invalid username or password")
        clear_login_failures(key)
        last_login_at = time.time()
        old_token = request.cookies.get(cookie_name(request))
        if old_token is not None:
            revoke_session(old_token)
        response.set_cookie(cookie_name(request), create_session(item.username), httponly=True, samesite="lax",
                            secure=settings.cookie_secure, max_age=7 * 86400)
        return {"success": True, "username": item.username, "is_default_password": False}

    @app.get("/api/auth/me", response_model=responses.CurrentUser, response_model_exclude_unset=True)
    async def me(current: str = Depends(user)):
        return {"username": current, "is_default_password": False, "last_login_at": last_login_at}

    @app.post("/api/auth/logout", response_model=responses.Success, response_model_exclude_unset=True)
    async def logout(request: Request, response: Response, _: str = Depends(user)):
        name = cookie_name(request)
        revoke_session(request.cookies[name])
        response.delete_cookie(name)
        on_logout()
        return {"success": True}

    return user


async def changes_socket(websocket: WebSocket, listeners: set[asyncio.Event]) -> None:
    token = websocket.cookies.get(cookie_name(websocket))
    try:
        require_panel_origin(websocket)
        session_user(token)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    changed = asyncio.Event()
    listeners.add(changed)
    changed.set()

    async def push():
        while True:
            await changed.wait()
            changed.clear()
            session_user(token)
            await websocket.send_json({"type": "changed"})

    pushing = asyncio.create_task(push())
    receiving = asyncio.create_task(websocket.receive())
    try:
        done, _ = await asyncio.wait({pushing, receiving}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            result = await task
            if task is receiving and result["type"] != "websocket.disconnect":
                await websocket.close(code=1003, reason="This stream only reports changes")
    except HTTPException:
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        listeners.remove(changed)
        pushing.cancel()
        receiving.cancel()
        await asyncio.gather(pushing, receiving, return_exceptions=True)


async def event_socket(websocket: WebSocket, hub: EventHub) -> None:
    token = websocket.cookies.get(cookie_name(websocket))
    try:
        require_panel_origin(websocket)
        session_user(token)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    reader, hello = hub.subscribe()

    async def push():
        await websocket.send_json(hello)
        while True:
            event = await reader.get()
            session_user(token)
            await websocket.send_json(event)

    pushing = asyncio.create_task(push())
    receiving = asyncio.create_task(websocket.receive())
    try:
        done, _ = await asyncio.wait({pushing, receiving}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            result = await task
            if task is receiving and result["type"] != "websocket.disconnect":
                await websocket.close(code=1003, reason="This stream only reports events")
    except HTTPException:
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        reader.close()
        pushing.cancel()
        receiving.cancel()
        await asyncio.gather(pushing, receiving, return_exceptions=True)
