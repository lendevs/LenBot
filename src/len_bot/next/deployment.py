"""Program versions of a managed installation, and the switch between them that the launcher performs.

A deployment package keeps every version in ``<root>/releases/<version>/`` (Python, uv, the task runtime)
and names the selected one in ``<root>/current.json``. A Docker deployment runs the image's own environment
until the panel installs a newer version into the data volume: ``<root>/runtime/<version>/venv``, selected by
``<root>/runtime/current.json``; whichever of the image and the selected volume version is newer runs.
A source checkout or a pip install is not managed here.

The host and its launcher exchange two files: ``<root>/updates/request.json`` (switch to a prepared version,
or restore a snapshot) before the host exits with ``UPDATE_EXIT``, and ``<root>/updates/result.json``,
which the next host reads and shows in the panel.
"""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from typing import Callable, Literal
import urllib.request

from packaging.version import InvalidVersion, Version

KIND = 'LENBOT_DEPLOYMENT_KIND'
ROOT = 'LENBOT_DEPLOYMENT_ROOT'
IMAGE_ENVIRONMENT = Path('/opt/lenbot/.venv')
# Versions kept after an update: the running one and the one before it, for snapshot restores.
KEEP_VERSIONS = 2
KEEP_SNAPSHOTS = 2
READY_SECONDS = 120


def newer(left: str, right: str) -> bool:
    try:
        return Version(left) > Version(right)
    except InvalidVersion:
        return False


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def image_version() -> str | None:
    """The version installed in the Docker image's environment, read without importing it."""
    found = sorted(IMAGE_ENVIRONMENT.glob('lib/python3*/site-packages/len_bot-*.dist-info'))
    return found[0].name.removeprefix('len_bot-').removesuffix('.dist-info') if found else None


@dataclass(frozen=True)
class Deployment:
    kind: Literal['package', 'docker']
    root: Path

    @classmethod
    def from_environment(cls) -> Deployment | None:
        kind, root = os.environ.get(KIND), os.environ.get(ROOT)
        if kind not in ('package', 'docker') or not root:
            return None
        return cls(kind, Path(root))

    @property
    def instance(self) -> Path:
        return self.root / 'instance'

    @property
    def backups(self) -> Path:
        return self.root / 'backups'

    @property
    def updates(self) -> Path:
        return self.root / 'updates'

    @property
    def versions(self) -> Path:
        return self.root / ('releases' if self.kind == 'package' else 'runtime')

    @property
    def pointer(self) -> Path:
        return self.root / 'current.json' if self.kind == 'package' else self.versions / 'current.json'

    def directory(self, version: str) -> Path:
        return self.versions / version

    def python(self, version: str) -> Path:
        if self.kind == 'docker':
            if version == image_version():
                return IMAGE_ENVIRONMENT / 'bin/python'
            return self.directory(version) / 'venv/bin/python'
        python = self.directory(version) / 'python'
        return python / 'python.exe' if sys.platform == 'win32' else python / 'bin/python3'

    def installed(self, version: str) -> bool:
        return self.python(version).exists()

    def selected(self) -> str:
        """The version the launcher starts."""
        chosen = read_json(self.pointer)['version'] if self.pointer.exists() else None
        if self.kind == 'docker':
            image = image_version()
            if chosen is None or not self.installed(chosen) or (image is not None and not newer(chosen, image)):
                return image
        return chosen

    def select(self, version: str) -> None:
        if self.kind == 'package':
            write_json(self.pointer, read_json(self.directory(version) / 'release.json'))
        else:
            write_json(self.pointer, {'version': version})

    def platform(self) -> str | None:
        """The package platform (windows-x64, linux-x64 ...); None in Docker."""
        if self.kind != 'package':
            return None
        return read_json(self.directory(self.selected()) / 'release.json')['platform']

    def environment(self, version: str) -> dict:
        """The host's environment: where the deployment is, UTF-8 mode, and a package's own uv first on PATH."""
        environment = {**os.environ, 'PYTHONUTF8': '1', KIND: self.kind, ROOT: str(self.root)}
        if self.kind == 'package':
            environment['PATH'] = str(self.directory(version) / 'bin') + os.pathsep + os.environ.get('PATH', '')
        return environment

    def kept(self) -> set[str]:
        """Versions installed in the volume or the package."""
        if not self.versions.is_dir():
            return set()
        return {path.name for path in self.versions.iterdir()
                if path.is_dir() and not path.name.startswith('.') and self.installed(path.name)}

    def snapshots(self) -> list[dict]:
        """Snapshots this launcher took, newest first, with the version each belongs to."""
        found = []
        for meta in self.backups.glob('*.json') if self.backups.is_dir() else []:
            directory = meta.with_suffix('')
            if directory.is_dir():
                found.append({**read_json(meta), 'name': directory.name, 'restorable': self.installed(read_json(meta)['version'])})
        return sorted(found, key=lambda item: item['created_at'], reverse=True)

    def prune(self, keep: set[str]) -> None:
        """Remove installed versions other than these; the image's own version is never in the volume."""
        for version in self.kept() - keep:
            shutil.rmtree(self.directory(version), ignore_errors=True)

    def prune_snapshots(self) -> None:
        for item in self.snapshots()[KEEP_SNAPSHOTS:]:
            shutil.rmtree(self.backups / item['name'], ignore_errors=True)
            (self.backups / (item['name'] + '.json')).unlink(missing_ok=True)


def ready_url(instance: Path) -> str:
    panel = read_json(instance / 'lenbot.config.json')['panel']
    host = panel['host']
    if host in ('0.0.0.0', '::', ''):
        host = '127.0.0.1'
    if ':' in host:
        host = f'[{host}]'
    return f'http://{host}:{panel["port"]}/api/host/ready'


# wait_ready's answer when the launcher itself is being stopped, which says nothing about the new version.
STOPPING = '启动器正在停止'


def wait_ready(instance: Path, version: str, exited: Callable[[], int | None],
               stopping: Callable[[], bool], seconds: float = READY_SECONDS) -> str | None:
    """None once the host serves this version and finished starting; otherwise why it did not."""
    url = ready_url(instance)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stopping():
            return STOPPING
        code = exited()
        if code is not None:
            return f'新版本退出，退出码 {code}'
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                status = json.load(response)
            if status['version'] != version:
                return f'面板运行的是 {status["version"]}，不是 {version}'
            if status['status'] == 'failed':
                return '新版本运行时初始化失败，详情见宿主日志'
            if status['ready']:
                return None
        except (OSError, http.client.HTTPException, ValueError):
            pass
        time.sleep(0.5)
    return f'新版本 {seconds:.0f} 秒内没有就绪'


class Switch:
    """One request from the host, carried out by the launcher while no host runs."""

    def __init__(self, deployment: Deployment):
        self.deployment = deployment
        self.request_path = deployment.updates / 'request.json'
        self.result_path = deployment.updates / 'result.json'

    def pending(self) -> dict | None:
        return read_json(self.request_path) if self.request_path.exists() else None

    def maintenance(self, version: str, action: str, snapshot: Path | None = None) -> None:
        arguments = [str(self.deployment.python(version)), '-X', 'utf8', '-m', 'len_bot.next.maintenance.upgrade', action]
        if snapshot is not None:
            arguments += ['--snapshot', str(snapshot)]
        subprocess.run(arguments, cwd=self.deployment.instance, env=self.deployment.environment(version), check=True)

    def snapshot(self, version: str, reason: str) -> Path:
        name = time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4)
        path = self.deployment.backups / name
        self.deployment.backups.mkdir(mode=0o700, exist_ok=True)
        try:
            self.maintenance(version, 'backup', path)
        except BaseException:
            shutil.rmtree(path, ignore_errors=True)
            raise
        write_json(self.deployment.backups / (name + '.json'),
                   {'version': version, 'reason': reason, 'created_at': time.time()})
        return path

    def finish(self, result: dict) -> None:
        write_json(self.result_path, {**result, 'finished_at': time.time()})
        self.request_path.unlink(missing_ok=True)

    def restore(self, request: dict, current: str) -> dict:
        """Restore a snapshot before the next start. A failure is recorded and the current version starts as it was."""
        try:
            name = request['snapshot']
            meta = read_json(self.deployment.backups / (name + '.json'))
            print(f'LenBot：恢复快照 {name}（{meta["version"]}）。', flush=True)
            self.maintenance(meta['version'], 'restore', self.deployment.backups / name)
            self.deployment.select(meta['version'])
        except Exception as error:
            print(f'LenBot：恢复快照失败：{error}', flush=True)
            self.finish({'action': 'restore', 'status': 'failed', 'snapshot': request.get('snapshot'),
                         'from': current, 'error': f'恢复快照失败：{type(error).__name__}: {error}'})
            return {}
        self.finish({'action': 'restore', 'status': 'complete', 'snapshot': name, 'from': current, 'to': meta['version']})
        return {}

    def prepare(self, request: dict) -> dict:
        """Before the next start: snapshot and migrate for an update, or restore a snapshot.

        Returns the trial for the start that follows: the version to wait for and how to undo it.
        """
        current = self.deployment.selected()
        if request['action'] == 'restore':
            return self.restore(request, current)
        target = request['version']
        print(f'LenBot：更新 {current} → {target}，先保存快照。', flush=True)
        try:
            snapshot = self.snapshot(current, 'update')
        except Exception as error:
            self.finish({'action': 'update', 'status': 'failed', 'from': current, 'to': target,
                         'error': f'快照失败：{error}'})
            return {}
        try:
            print('LenBot：迁移实例数据。', flush=True)
            self.maintenance(target, 'apply')
            follow_release(self.deployment, current, target)
            self.deployment.select(target)
        except Exception as error:
            self.roll_back(current, target, snapshot, f'迁移失败：{error}', request)
            return {}
        return {'version': target, 'from': current, 'snapshot': snapshot, 'request': request}

    def roll_back(self, previous: str, target: str, snapshot: Path, reason: str, request: dict) -> None:
        print(f'LenBot：{reason}；恢复快照并回到 {previous}。', flush=True)
        status = 'rolled_back'
        try:
            self.maintenance(previous, 'restore', snapshot)
            self.deployment.select(previous)
        except Exception as error:
            status, reason = 'failed', f'{reason}；恢复快照也失败：{error}'
        else:
            # The version that did not start is not kept.
            self.deployment.prune(self.deployment.kept() - {target})
        self.finish({'action': 'update', 'status': status, 'from': previous, 'to': target, 'error': reason,
                     'snapshot': snapshot.name})

    def settle(self, trial: dict, problem: str | None) -> None:
        """After the trial start: keep the new version, or put the previous one back."""
        if problem is not None:
            self.roll_back(trial['from'], trial['version'], trial['snapshot'], problem, trial['request'])
            return
        self.finish({'action': 'update', 'status': 'complete', 'from': trial['from'], 'to': trial['version'],
                     'snapshot': trial['snapshot'].name,
                     'plugins': 'pending' if trial['request'].get('plugins') else None})
        self.deployment.prune({trial['version'], trial['from']})
        self.deployment.prune_snapshots()
        print(f'LenBot：已更新到 {trial["version"]}。', flush=True)

    def interrupted(self, trial: dict) -> None:
        """The launcher was stopped during the trial start: nothing is known about the new version, so keep it and its
        snapshot (no pruning) instead of rolling back a version that may be healthy. A bad one is restored from the snapshot."""
        self.finish({'action': 'update', 'status': 'complete', 'from': trial['from'], 'to': trial['version'],
                     'snapshot': trial['snapshot'].name, 'verified': False,
                     'plugins': 'pending' if trial['request'].get('plugins') else None})
        print(f'LenBot：启动器在试启动期间停止，保留 {trial["version"]} 与更新前快照，未验证就绪。', flush=True)


OFFICIAL_WORKERS = ('ghcr.io/lendevs/lenbot-worker', 'docker.io/lendevs/lenbot-worker', 'lendevs/lenbot-worker')


def follow_release(deployment: Deployment, previous: str, target: str) -> None:
    """An official task image, and a package's own task runtime, follow the program version."""
    path = deployment.instance / 'lenbot.config.json'
    source = read_json(path)
    worker = source.get('worker')
    if worker is None:
        return
    changed = False
    if worker.get('sandbox', 'docker') == 'docker' and 'image' in worker:
        name = worker['image'].split('@', 1)[0]
        head, slash, last = name.rpartition('/')
        repository = head + slash + last.split(':', 1)[0]
        if repository in OFFICIAL_WORKERS and worker['image'] != f'{repository}:{target}':
            worker['image'] = f'{repository}:{target}'
            changed = True
    runtime = worker.get('task_runtime')
    if deployment.kind == 'package' and runtime is not None \
            and Path(runtime) == deployment.directory(previous) / 'task-runtime':
        worker['task_runtime'] = str(deployment.directory(target) / 'task-runtime')
        changed = True
    if changed:
        from .storage.files import atomic_text
        atomic_text(path, json.dumps(source, ensure_ascii=False, indent=2) + '\n')
