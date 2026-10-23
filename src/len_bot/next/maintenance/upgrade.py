"""Offline update inspection and the ordered migrations used by deployment controllers."""

import argparse
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tomllib

from ..config import HostConfig, load_instance_config, load_instance_source
from ..instance_lock import instance_lock
from ..memory.service import LocalMemoryConfig
from ..plugins.manifest import INTERFACE, Manifest, discover
from .migrate import migrate
from .migrate_config import migrate_config, upgraded_config
from .migrate_memory_jobs import migrate_memory_jobs
from .migrate_local_memory import migrate as migrate_local_memory
from .doctor import check
from .plugin_dependencies import install
from .snapshot import create, restore
from ..runtime.logs import run_maintenance


def inspect(root: Path, version: str) -> dict:
    """Read plugin metadata without importing plugin code or editing an old configuration."""
    raw = json.loads((root / 'lenbot.config.json').read_text(encoding='utf-8'))
    plugins = raw.get('plugins')
    blocked, stopped = [], []
    if plugins is not None:
        paths = [Path(value) if Path(value).is_absolute() else root / value for value in plugins.get('paths', ['plugins'])]
        found, errors = discover(paths)
        blocked.extend(errors)
        for name in plugins.keys() - {'paths', 'data_directory', 'disabled'}:
            if name in plugins.get('disabled', []):
                stopped.append(name)
                continue
            try:
                directories = found.get(name, [])
                if len(directories) != 1:
                    raise ValueError(f'{name}: expected one installed plugin directory, found {directories}')
                manifest = Manifest.model_validate(tomllib.loads((directories[0] / 'plugin.toml').read_text()))
                if manifest.interface != INTERFACE:
                    raise ValueError(f'{name}: interface={manifest.interface}, target={INTERFACE}')
                manifest.require_compatible(host=version)
            except (ValueError, OSError) as error:
                blocked.append(f'{name}: {error}')
    return {'blocked_plugins': blocked, 'disabled_plugins': stopped, 'work_enabled': raw.get('worker') is not None}


def data_paths(root: Path) -> list[str]:
    path = root / 'lenbot.config.json'
    config = load_instance_source(path, upgraded_config(json.loads(path.read_text(encoding='utf-8')), path))
    paths = [root, config.database, config.database.with_name(config.database.name + '.memory.sqlite3')]
    if isinstance(config, HostConfig) and config.plugins is not None:
        paths.extend([config.plugins.data_directory, *config.plugins.paths])
    if isinstance(config.memory, LocalMemoryConfig):
        paths.append(config.memory.local.directory)
    if config.worker is not None:
        paths.extend([config.worker.workspace_root, config.worker.runtime_root, config.worker.delivery_root])
    if isinstance(config, HostConfig):
        paths.extend(value.persona for value in config.scenes.values())
    else:
        paths.append(config.persona)
    outside = set()
    for path in paths:
        absolute = path.resolve()
        if not absolute.is_relative_to(root):
            outside.add(absolute)
            if absolute == config.database.resolve() or absolute.name.endswith('.sqlite3'):
                # Listed even when absent, so restore removes a journal the failed new version left behind.
                outside.update(absolute.with_name(absolute.name + suffix) for suffix in ('-wal', '-shm', '-journal'))
    return [str(root), *(str(path) for path in sorted(outside) if not any(parent in outside for parent in path.parents))]


def _trial_roots(root: Path) -> list[Path]:
    return [path.parent for path in sorted((root / '.runtime/chat-tests').glob('*/lenbot.config.json'))]


def _migrate_locked(root: Path, trials: list[Path]) -> None:
    for directory in (root, *trials):
        migrate_config(directory / 'lenbot.config.json', backup=False)
        config = load_instance_config(directory)
        if config.database.exists():
            migrate(config.database, backup=False)
        jobs = config.database.with_name(config.database.name + '.memory.sqlite3')
        if jobs.exists():
            migrate_memory_jobs(jobs, backup=False)
        if isinstance(config.memory, LocalMemoryConfig):
            migrate_local_memory(config.memory.local.directory, backup=False)
        if isinstance(config, HostConfig):
            asyncio.run(install(directory))
        failed = [item for item in check(directory) if item['status'] == 'error']
        if failed:
            raise ValueError('升级后的实例检查未通过：\n'
                             + '\n'.join(f"{item['check']}: {item['detail']}" for item in failed))


def migrate_instance(root: Path) -> None:
    """Migrate after the deployment controller has taken its snapshot."""
    with ExitStack() as locks:
        locks.enter_context(instance_lock(root))
        trials = _trial_roots(root)
        for directory in trials:
            locks.enter_context(instance_lock(directory))
        _migrate_locked(root, trials)


def upgrade_instance(root: Path, snapshot: Path) -> None:
    """Back up, migrate and check a stopped source installation, restoring on failure."""
    with ExitStack() as locks:
        locks.enter_context(instance_lock(root))
        trials = _trial_roots(root)
        for directory in trials:
            locks.enter_context(instance_lock(directory))
        paths = {Path(value) for directory in (root, *trials) for value in data_paths(directory)}
        saved = sorted(path for path in paths if not any(parent in paths for parent in path.parents))
        create([str(path) for path in saved], snapshot)
        try:
            _migrate_locked(root, trials)
        except BaseException:
            restore(root, snapshot)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'paths', 'apply', 'backup', 'restore', 'run'))
    parser.add_argument('--version')
    parser.add_argument('--snapshot', type=Path)
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == 'inspect':
        if args.version is None:
            parser.error('inspect requires --version')
        print(json.dumps(inspect(root, args.version), ensure_ascii=False))
    elif args.action == 'paths':
        print(json.dumps(data_paths(root), ensure_ascii=False))
    elif args.action == 'run':
        if args.snapshot is None:
            parser.error('run requires --snapshot pointing outside the instance')
        upgrade_instance(root, args.snapshot.resolve())
        print(json.dumps({'status': 'ok', 'snapshot': str(args.snapshot.resolve())}, ensure_ascii=False))
    elif args.action == 'apply':
        migrate_instance(root)
    else:
        if args.snapshot is None:
            parser.error('backup and restore require --snapshot')
        with instance_lock(root):
            if args.action == 'backup':
                create(data_paths(root), args.snapshot)
            else:
                restore(root, args.snapshot)


if __name__ == '__main__':
    if sys.argv[1:2] in (['inspect'], ['paths'], ['restore'], ['run']):
        # inspect and paths only read, and the container updater mounts the instance read-only for them;
        # restore replaces the instance, log files included, and Windows cannot remove a file held open.
        # The updater records these steps in its own log.
        main()
    else:
        run_maintenance(main, 'upgrade')
