"""Authenticated handoff to the installation's independent update controller."""

from collections.abc import Callable
import json
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Request
import httpx

from .. import responses
from ...runtime.releases import CHECK_TIMEOUT_SECONDS, GITHUB_RELEASES, ReleaseCheck, current_version, github_releases

ERRORS = (OSError, ValueError, KeyError, TimeoutError, httpx.HTTPError)

# Shown in the update confirmation of a managed installation, before the user applies an update.
UPDATE_NOTICE = [
    '更新期间聊天、提醒和后台任务暂停，通常持续几分钟；更新前已连接聊天平台时，会等待新版本重新连接。',
    '备份完成后的更新失败时，会自动恢复更新前的程序和数据快照并启动旧版本。',
    '自动回滚或手动恢复快照都会丢弃更新开始后写入的数据，包括新消息、记忆、设置修改和任务记录。',
    '快照按时间保存在部署目录的 backups/ 下，可在本页删除。',
]
# The controller's backups/<UTC time>-<8 hex> names.
SNAPSHOT = r'^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$'


def register_host_updates(app: FastAPI, *, root: Path, user: Callable[[Request], str],
                          check_enabled: bool = True) -> ReleaseCheck:
    """Register the update routes; the returned check is started by the panel's lifespan when enabled."""
    def control() -> dict | None:
        file = root / '.runtime/update-control.json'
        if not file.exists():
            return None
        value = json.loads(file.read_text(encoding='utf-8'))
        if value['protocol'] != 1:
            raise ValueError('请先更新安装控制器；控制协议不匹配')
        return value

    async def request_control(path: str, method: str = 'GET') -> dict | list:
        reference = control()
        if reference is None:
            raise HTTPException(409, '源码安装不支持面板换版；请使用 Git 和离线迁移命令')
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, reference['endpoint'] + '/api/' + path,
                                            headers={'Authorization': 'Bearer ' + reference['token']})
            if response.status_code in (404, 409):
                # A missing snapshot or a refusal in the current update state; the controller words it for the user.
                raise HTTPException(response.status_code, response.json()['detail'])
            if response.is_error:
                raise HTTPException(502, f'更新控制器 HTTP {response.status_code}: {response.text[:2000]}')
            return response.json()

    async def load_releases() -> list[dict]:
        # A managed installation asks its own controller, which reads the release source it was installed from.
        if control() is not None:
            return await request_control('releases')
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS, headers={
                'Accept': 'application/vnd.github+json', 'User-Agent': 'LenBot/' + current_version()}) as client:
            response = await client.get(GITHUB_RELEASES)
            if response.is_error:
                # GitHub explains rate limits and outages in the body; keep it instead of a bare status.
                raise ValueError(f'GitHub HTTP {response.status_code}: {response.text[:500]}')
            return github_releases(response.json())

    releases = ReleaseCheck(load_releases, enabled=check_enabled)

    @app.get('/api/host/updates', response_model=responses.UpdateState, response_model_exclude_unset=True)
    async def current(_: str = Depends(user)):
        try:
            reference = control()
            return {'version': releases.current, 'managed': reference is not None,
                    'status': None if reference is None else await request_control('status'),
                    'check': releases.state(),
                    # The panel shows these before an update; rolling back loses data written after it.
                    'notice': None if reference is None else UPDATE_NOTICE,
                    'rollback_loses_data': reference is not None}
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/host/updates/releases', response_model=list[responses.JsonObject], response_model_exclude_unset=True)
    async def published(_: str = Depends(user)):
        # An explicit check works even with the background check turned off.
        try:
            return await releases.refresh()
        except ERRORS as error:
            raise HTTPException(422, f'{type(error).__name__}: {error}') from error

    @app.post('/api/host/updates/session', response_model=responses.JsonObject, response_model_exclude_unset=True)
    async def session(_: str = Depends(user)):
        try:
            return await request_control('session')
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/host/updates/snapshots', response_model=list[responses.UpdateSnapshot])
    async def snapshots(_: str = Depends(user)):
        try:
            return await request_control('snapshots')
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error

    @app.delete('/api/host/updates/snapshots/{name}', response_model=list[responses.UpdateSnapshot])
    async def delete_snapshot(name: Annotated[str, PathParameter(pattern=SNAPSHOT)], _: str = Depends(user)):
        try:
            return await request_control('snapshots/' + name, 'DELETE')
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error

    return releases
