"""The panel's one-step update: download and install a release beside the running one, then hand over.

The running host prepares everything that does not need it stopped: a deployment package downloads its
platform package and unpacks ``releases/<version>``; Docker downloads the wheel and the locked requirements
and installs them into a copy of the running environment in the data volume. The host then writes the
launcher's request and exits; the launcher snapshots, migrates, starts the new version and waits until it
is ready, putting the previous version and the snapshot back when it is not.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import hashlib
import logging
from pathlib import Path
import shutil
import sys
import tarfile
import time
import zipfile

import httpx

from ..deployment import Deployment, read_json, write_json
from .logs import log_event

logger = logging.getLogger(__name__)

PROTOCOL = 2
CHUNK = 1 << 20


class UpdateError(Exception):
    """A release that cannot be installed here, or a step that failed; the message is shown in the panel."""


def release_manifest(value: dict, tag: str) -> dict:
    if value.get('manifest_version') != 1 or value.get('updater_protocol') != PROTOCOL:
        raise UpdateError(f'{tag} 的发行清单格式与本机不一致，请下载新的部署包或镜像')
    if value['tag'] != tag:
        raise UpdateError('发行清单不属于所选版本')
    return value


class Updater:
    def __init__(self, deployment: Deployment | None, current: str, *, exit_for_update: Callable[[], Awaitable[None]]):
        self.deployment = deployment
        self.current = current
        self.exit_for_update = exit_for_update
        self.stage: str = 'idle'
        self.target: str | None = None
        self.progress: dict | None = None
        self.error: str | None = None
        self.task: asyncio.Task | None = None

    @property
    def managed(self) -> str | None:
        return None if self.deployment is None else self.deployment.kind

    def state(self) -> dict:
        return {'stage': self.stage, 'target': self.target, 'progress': self.progress, 'error': self.error}

    def result(self) -> dict | None:
        if self.deployment is None:
            return None
        path = self.deployment.updates / 'result.json'
        return read_json(path) if path.exists() else None

    def plugins_follow(self) -> bool:
        """Whether this start is the update that asked for plugin updates, or one that still owes them."""
        if self.deployment is None:
            return False
        request = self.deployment.updates / 'request.json'
        if request.exists():
            value = read_json(request)
            if value.get('action') == 'update' and value.get('version') == self.current and value.get('plugins'):
                return True
        result = self.result()
        return result is not None and result.get('to') == self.current and result.get('plugins') == 'pending'

    def record_plugins(self, plugins: list[dict]) -> None:
        result = self.result()
        if result is not None:
            write_json(self.deployment.updates / 'result.json', {**result, 'plugins': plugins})

    def snapshots(self) -> list[dict]:
        if self.deployment is None:
            return []
        return [{**item, 'bytes': sum(path.stat().st_size for path in (self.deployment.backups / item['name']).rglob('*')
                                      if path.is_file() and not path.is_symlink())}
                for item in self.deployment.snapshots()]

    def delete_snapshot(self, name: str) -> None:
        if self.deployment is None or name not in {item['name'] for item in self.deployment.snapshots()}:
            raise UpdateError(f'没有快照 {name}')
        shutil.rmtree(self.deployment.backups / name)
        (self.deployment.backups / (name + '.json')).unlink(missing_ok=True)

    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, release: dict, *, plugins: bool) -> None:
        if self.deployment is None:
            raise UpdateError('源码运行的实例用 git pull 更新')
        if self.busy() or self.stage == 'restart':
            raise UpdateError('正在更新')
        self.stage, self.target, self.progress, self.error = 'download', release['version'], None, None
        self.task = asyncio.create_task(self._update(release, plugins))

    async def restore(self, name: str) -> None:
        if self.deployment is None:
            raise UpdateError('源码运行的实例没有快照')
        if self.busy() or self.stage == 'restart':
            raise UpdateError('正在更新')
        found = [item for item in self.deployment.snapshots() if item['name'] == name]
        if not found:
            raise UpdateError(f'没有快照 {name}')
        if not found[0]['restorable']:
            raise UpdateError(f'快照 {name} 属于 {found[0]["version"]}，本机已不保留这个版本')
        write_json(self.deployment.updates / 'request.json', {'action': 'restore', 'snapshot': name})
        self.stage = 'restart'
        await self.exit_for_update()

    async def _update(self, release: dict, plugins: bool) -> None:
        deployment = self.deployment
        work = deployment.updates / 'downloads'
        try:
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), follow_redirects=True,
                                         headers={'User-Agent': 'LenBot/' + self.current}) as client:
                assets = release['assets']
                if 'release-manifest.json' not in assets:
                    raise UpdateError(f'{release["tag"]} 没有发行清单')
                response = await client.get(assets['release-manifest.json'])
                response.raise_for_status()
                manifest = release_manifest(response.json(), release['tag'])
                if deployment.kind == 'package':
                    names = [manifest['bundles'][deployment.platform()]]
                else:
                    names = [f'len_bot-{manifest["version"]}-py3-none-any.whl', 'requirements.txt']
                total = sum(manifest['files'][name]['bytes'] for name in names)
                self.progress = {'done': 0, 'total': total}
                for name in names:
                    await self._download(client, assets[name], work / name, manifest['files'][name])
            self.stage, self.progress = 'install', None
            if deployment.kind == 'package':
                await asyncio.to_thread(self._unpack, work / names[0], manifest['version'])
            else:
                await self._install_environment(work / names[0], work / names[1], manifest['version'])
            write_json(deployment.updates / 'request.json', {
                'action': 'update', 'version': manifest['version'], 'from': self.current, 'plugins': plugins,
                'requested_at': time.time()})
            log_event(logger, 'update_prepared', version=manifest['version'], current=self.current)
            self.stage = 'restart'
            await self.exit_for_update()
        except Exception as error:
            self.stage, self.progress = 'failed', None
            self.error = str(error) if isinstance(error, UpdateError) else f'{type(error).__name__}: {error}'
            log_event(logger, 'update_failed', level=logging.ERROR, error=error, target=self.target)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def _download(self, client: httpx.AsyncClient, url: str, destination: Path, expected: dict) -> None:
        digest = hashlib.sha256()
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            with destination.open('xb') as target:
                async for block in response.aiter_bytes(CHUNK):
                    digest.update(block)
                    await asyncio.to_thread(target.write, block)
                    self.progress = {**self.progress, 'done': self.progress['done'] + len(block)}
        if destination.stat().st_size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
            raise UpdateError(f'{destination.name} 的大小或校验和与发行清单不一致')

    def _unpack(self, archive: Path, version: str) -> None:
        deployment = self.deployment
        unpacked = archive.parent / 'package'
        unpacked.mkdir()
        if archive.suffix == '.zip':
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    if not (unpacked / name).resolve().is_relative_to(unpacked.resolve()):
                        raise UpdateError(f'部署包内的路径越界：{name}')
                bundle.extractall(unpacked)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(unpacked, filter='tar')
        package, = unpacked.iterdir()
        source = package / 'releases' / version
        metadata = read_json(source / 'release.json')
        if metadata['version'] != version or metadata['platform'] != deployment.platform():
            raise UpdateError('下载的部署包版本或平台与所选版本不一致')
        if version == deployment.selected():
            raise UpdateError(f'{version} 正在运行')
        target = deployment.directory(version)
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(source, target)

    async def _install_environment(self, wheel: Path, requirements: Path, version: str) -> None:
        """A copy of the running environment, brought to the release's locked requirements and wheel."""
        deployment = self.deployment
        if version == deployment.selected():
            raise UpdateError(f'{version} 正在运行')
        uv = shutil.which('uv')
        if uv is None:
            raise UpdateError('镜像中没有 uv')
        target = deployment.directory(version)
        await asyncio.to_thread(shutil.rmtree, target, True)
        target.mkdir(parents=True)
        environment = target / 'venv'
        # Copying the running environment means only the packages that changed are downloaded.
        await asyncio.to_thread(shutil.copytree, Path(sys.prefix), environment, symlinks=True)
        python = environment / 'bin/python'
        await self._run([uv, 'pip', 'install', '--python', str(python), '--link-mode', 'copy', '--no-cache',
                         '--requirement', str(requirements), str(wheel)])
        installed = (await self._run([str(python), '-c', 'from importlib.metadata import version; print(version("len-bot"))'])).strip()
        if installed != version:
            raise UpdateError(f'安装后的版本是 {installed}，不是 {version}')

    async def _run(self, command: list[str]) -> str:
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.STDOUT)
        output, _ = await process.communicate()
        text = output.decode('utf-8', 'replace')
        if process.returncode != 0:
            raise UpdateError(f'{Path(command[0]).name} 退出码 {process.returncode}：{text[-2000:]}')
        return text

