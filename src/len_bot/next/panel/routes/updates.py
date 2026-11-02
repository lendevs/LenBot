"""The panel's update: one request downloads and installs a release, the launcher switches to it."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Request
import httpx
from packaging.version import Version
from pydantic import BaseModel, ConfigDict

from .. import responses
from ...runtime.logs import log_event
from ...runtime.releases import CHECK_TIMEOUT_SECONDS, GITHUB_RELEASES, ReleaseCheck, current_version, github_releases
from ...runtime.updater import UpdateError, Updater

ERRORS = (OSError, ValueError, KeyError, TimeoutError, httpx.HTTPError, UpdateError)

logger = logging.getLogger(__name__)
# backups/<UTC time>-<8 hex>, as the launcher names them.
SNAPSHOT = r'^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$'


class UpdateStart(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    tag: str
    # Also bring installed plugins to their newest catalog versions once the new version runs.
    plugins: bool = True


def register_host_updates(app: FastAPI, *, updater: Updater, user: Callable[[Request], str],
                          check_enabled: bool = True,
                          update_plugins: Callable[[], Awaitable[list[dict] | None]] | None = None
                          ) -> tuple[ReleaseCheck, list[Callable[[], Awaitable[None]]]]:
    """Register the update routes; the panel's lifespan starts the check (when enabled) and the returned jobs."""
    published: dict[str, dict] = {}

    async def load_releases() -> list[dict]:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS, follow_redirects=True, headers={
                'Accept': 'application/vnd.github+json', 'User-Agent': 'LenBot/' + current_version()}) as client:
            response = await client.get(GITHUB_RELEASES)
            if response.is_error:
                # GitHub explains rate limits and outages in the body; keep it instead of a bare status.
                raise ValueError(f'GitHub HTTP {response.status_code}: {response.text[:500]}')
            found = github_releases(response.json())
        published.clear()
        published.update({item['tag']: item for item in found})
        return found

    releases = ReleaseCheck(load_releases, enabled=check_enabled)

    @app.get('/api/host/updates', response_model=responses.UpdateState, response_model_exclude_unset=True)
    async def current(_: str = Depends(user)):
        try:
            return {'version': releases.current, 'managed': updater.managed, 'check': releases.state(),
                    'operation': updater.state(), 'result': await asyncio.to_thread(updater.result),
                    'snapshots': await asyncio.to_thread(updater.snapshots)}
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/host/updates/releases', response_model=list[responses.JsonObject], response_model_exclude_unset=True)
    async def list_releases(_: str = Depends(user)):
        # An explicit check works even with the background check turned off.
        try:
            return [{key: value for key, value in item.items() if key != 'assets'} for item in await releases.refresh()]
        except ERRORS as error:
            raise HTTPException(422, f'{type(error).__name__}: {error}') from error

    @app.post('/api/host/updates/start', response_model=responses.UpdateState, response_model_exclude_unset=True)
    async def start(request: Request, _: str = Depends(user)):
        try:
            change = UpdateStart.model_validate(await request.json())
            if change.tag not in published:
                await releases.refresh()
            release = published.get(change.tag)
            if release is None:
                raise UpdateError(f'没有发行版本 {change.tag}')
            if Version(release['version']) <= Version(releases.current):
                raise UpdateError(f'{release["version"]} 不比当前版本新；回到旧版本使用快照恢复')
            updater.start(release, plugins=change.plugins)
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error
        return await current()

    @app.post('/api/host/updates/snapshots/{name}/restore', response_model=responses.UpdateState,
              response_model_exclude_unset=True)
    async def restore(name: Annotated[str, PathParameter(pattern=SNAPSHOT)], _: str = Depends(user)):
        try:
            await updater.restore(name)
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error
        return await current()

    @app.delete('/api/host/updates/snapshots/{name}', response_model=responses.UpdateState,
                response_model_exclude_unset=True)
    async def delete_snapshot(name: Annotated[str, PathParameter(pattern=SNAPSHOT)], _: str = Depends(user)):
        try:
            await asyncio.to_thread(updater.delete_snapshot, name)
        except ERRORS as error:
            raise HTTPException(422, str(error)) from error
        return await current()

    async def follow_plugins() -> None:
        """After an update that asked for it, bring plugins to their newest catalog versions.

        The launcher records the update only once this host is ready; a host that stops before it runs
        its plugins leaves them pending for the next start."""
        while (result := await asyncio.to_thread(updater.result)) is None or result.get('to') != releases.current \
                or result.get('plugins') != 'pending':
            if result is not None and result.get('to') == releases.current and result.get('status') != 'complete':
                return
            await asyncio.sleep(1)
        try:
            results = await update_plugins()
            if results is None:
                return
        except Exception as error:
            results = [{'name': '*', 'error': f'{type(error).__name__}: {error}'}]
            log_event(logger, 'update_plugins_failed', level=logging.ERROR, error=error)
        await asyncio.to_thread(updater.record_plugins, results)

    jobs = [follow_plugins] if update_plugins is not None and updater.plugins_follow() else []
    return releases, jobs
