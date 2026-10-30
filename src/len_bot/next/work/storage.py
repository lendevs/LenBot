"""Read current task-tree metadata without content access or link traversal."""

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import stat
import shutil
import sys

from ..configuration.tasks import WorkerSettings
from .store import TERMINAL, Task
from ..platform.identity import scene_directory
from ..storage.files import Directory, is_link


def continuation_state(item: Task, discarded: bool) -> str:
    if discarded:
        return 'discarded'
    if item.status not in TERMINAL or item.container is not None:
        return 'active'
    return 'retained'


def temporary_paths(settings: WorkerSettings, scene: str, task_id: int) -> list[tuple[Path, str]]:
    workspace = settings.workspace_root / scene_directory(scene) / 'tasks' / str(task_id)
    runtime = settings.runtime_root / scene_directory(scene) / str(task_id)
    return [(runtime / 'control', 'directory'), (workspace / '.playwright', 'directory'),
            *((workspace / name, 'file') for name in ('pi.stderr', 'model-bridge.stderr', 'egress-bridge.stderr')),
            (runtime / 'home' / '.pi' / 'agent' / 'models.json', 'file')]


def temporary_usage(settings: WorkerSettings, scene: str, task_id: int) -> list[dict]:
    result = []
    for path, kind in temporary_paths(settings, scene, task_id):
        if path.resolve(strict=False) != path:
            raise ValueError(f'Task temporary path must not traverse a symbolic link: {path}')
        if kind == 'directory':
            usage = directory_usage(path)
            result.append({'path': str(path), 'kind': kind, 'exists': usage is not None,
                           'file_bytes': 0 if usage is None else usage.file_bytes})
        else:
            try:
                info = path.lstat()
            except FileNotFoundError:
                result.append({'path': str(path), 'kind': kind, 'exists': False, 'file_bytes': 0})
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f'Task temporary file is not a regular file: {path}')
            result.append({'path': str(path), 'kind': kind, 'exists': True, 'file_bytes': info.st_size})
    return result


def clean_temporary_files(settings: WorkerSettings, scene: str, task_id: int, progress: dict) -> None:
    for item in temporary_usage(settings, scene, task_id):
        if not item['exists']:
            progress['absent'].append(item['path'])
            continue
        progress['active_root'] = item['path']
        path = Path(item['path'])
        if item['kind'] == 'directory':
            shutil.rmtree(path)
        else:
            path.unlink()
        progress['removed'].append(item['path'])
        progress['removed_file_bytes'] += item['file_bytes']
    progress['active_root'] = None
    progress['complete'] = True


def output_entries(root: Path, path: str, offset: int, limit: int) -> dict:
    """List one actual output directory without opening file contents or links."""
    if root.resolve(strict=False) != root:
        raise ValueError(f'Task output root must not traverse a symbolic link: {root}')
    try:
        directory = Directory.open(root)
    except FileNotFoundError:
        return {'exists': False, 'entries': [], 'next_offset': None}
    try:
        if path:
            for part in path.split('/'):
                nested = directory.child(part)
                directory.close()
                directory = nested
        names = sorted(directory.names())
        entries = []
        for name in names[offset:offset + limit]:
            info = directory.stat(name)
            kind = ('symlink' if is_link(info) else
                    'file' if stat.S_ISREG(info.st_mode) else
                    'directory' if stat.S_ISDIR(info.st_mode) else 'other')
            entries.append({'path': f'{path}/{name}' if path else name, 'kind': kind,
                            'size': info.st_size if kind == 'file' else None,
                            'modified': info.st_mtime})
        return {'exists': True, 'entries': entries,
                'next_offset': offset + limit if offset + limit < len(names) else None}
    finally:
        directory.close()


@dataclass
class TreeUsage:
    file_bytes: int = 0
    allocated_bytes: int = 0
    files: int = 0
    directories: int = 0
    links: int = 0
    special_files: int = 0
    hardlinked_files: int = 0


def directory_usage(root: Path) -> TreeUsage | None:
    if root.resolve(strict=False) != root:
        raise ValueError(f'Task storage root must not traverse a symbolic link: {root}')
    try:
        opened = Directory.open(root)
    except FileNotFoundError:
        return None
    usage = TreeUsage()
    allocated: set[tuple[int, int]] = set()

    def allocation(info: os.stat_result) -> None:
        identity = (info.st_dev, info.st_ino)
        if identity not in allocated:
            allocated.add(identity)
            # Windows reports no allocated blocks; its file size stands in.
            blocks = getattr(info, 'st_blocks', None)
            usage.allocated_bytes += info.st_size if blocks is None else blocks * 512

    def scan(directory: Directory) -> None:
        allocation(directory.stat())
        usage.directories += 1
        for name in directory.names():
            info = directory.stat(name)
            if is_link(info):
                allocation(info)
                usage.links += 1
            elif stat.S_ISDIR(info.st_mode):
                with directory.child(name) as nested:
                    scan(nested)
            else:
                allocation(info)
                if stat.S_ISREG(info.st_mode):
                    usage.files += 1
                    usage.file_bytes += info.st_size
                    if info.st_nlink > 1:
                        usage.hardlinked_files += 1
                else:
                    usage.special_files += 1

    with opened:
        scan(opened)
    return usage


def storage_usage(settings: WorkerSettings, scene: str, task_id: int) -> list[dict]:
    roots = (
        ('workspace', settings.workspace_root / scene_directory(scene) / 'tasks' / str(task_id)),
        ('runtime', settings.runtime_root / scene_directory(scene) / str(task_id)),
        ('deliveries', settings.delivery_root / scene_directory(scene) / str(task_id)),
    )
    result = []
    for kind, path in roots:
        try:
            usage = directory_usage(path)
        except (OSError, RuntimeError) as error:
            raise ValueError(f'Task storage scan failed at {path}: {type(error).__name__}: {error}') from error
        result.append({'kind': kind, 'path': str(path), 'exists': usage is not None,
                       'usage': None if usage is None else asdict(usage)})
    return result


def task_tree_bytes(settings: WorkerSettings, scene: str, task_id: int) -> int:
    """Disk space the task's workspace and runtime directories occupy; deliveries are counted separately."""
    total = 0
    for root in (settings.workspace_root / scene_directory(scene) / 'tasks' / str(task_id), settings.runtime_root / scene_directory(scene) / str(task_id)):
        usage = directory_usage(root)
        total += 0 if usage is None else usage.allocated_bytes
    return total


def disk_free(settings: WorkerSettings) -> int:
    """Free bytes on the emptier of the workspace and runtime file systems, before either directory exists too."""
    def existing(path: Path) -> Path:
        while not path.exists():
            path = path.parent
        return path
    return min(shutil.disk_usage(existing(root)).free for root in (settings.workspace_root, settings.runtime_root))


def discard_task_trees(workspace: Path, runtime: Path, progress: dict) -> None:
    # Windows rmtree removes links and junctions without entering them but works by name; callers only
    # discard trees of ended tasks whose container is gone, so nothing writes to them meanwhile.
    if not shutil.rmtree.avoids_symlink_attacks and sys.platform != 'win32':
        raise RuntimeError('Current platform does not support descriptor-based task-tree removal')
    present = []
    for path in (workspace, runtime):
        if path.resolve(strict=False) != path:
            raise ValueError(f'Task removal root must not traverse a symbolic link: {path}')
        try:
            info = path.lstat()
        except FileNotFoundError:
            progress['absent'].append(str(path))
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f'Task removal root must be an actual directory: {path}; mode={oct(info.st_mode)}')
        present.append(path)
    for path in present:
        progress['active_root'] = str(path)
        shutil.rmtree(path)
        progress['removed'].append(str(path))
    progress['active_root'] = None
    progress['complete'] = True
