"""Hold one host child; only an explicit, clean restart launches another."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from .runtime.lifecycle import RESTART_EXIT


def wait(child: subprocess.Popen) -> int:
    """Wait in short steps: on Windows an untimed wait blocks signal handlers, so a stop could not be passed on."""
    while True:
        try:
            return child.wait(0.5)
        except subprocess.TimeoutExpired:
            pass


def run(*, container: bool = False) -> int:
    root = Path.cwd()
    project = Path(__file__).resolve().parents[3]
    source_panel = not container and (project / '.git').exists() and (project / 'src/len_bot/web/frontend').is_dir()
    child: subprocess.Popen | None = None
    stopping = False

    def stop(signum, frame) -> None:
        nonlocal stopping
        stopping = True
        if child is not None:
            child.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signum)

    signals = (signal.SIGINT, signal.SIGTERM) if sys.platform != 'win32' else (signal.SIGINT, signal.SIGTERM, signal.SIGBREAK)
    previous = {sig: signal.signal(sig, stop) for sig in signals}

    def launch(command: list[str], cwd: Path = root) -> int:
        nonlocal child
        child = subprocess.Popen(command, cwd=cwd, start_new_session=sys.platform != 'win32',
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0)
        if stopping:
            child.terminate()
        code = wait(child)
        child = None
        return code

    try:
        while not stopping:
            if source_panel:
                code = launch(['node', str(project / 'scripts/frontend_build.cjs')], project)
                if stopping or code != 0:
                    return code if code >= 0 else 128 - code
            # This argument enables lifecycle control only; all settings come from the root file.
            code = launch(
                [sys.executable, '-c', f'from len_bot.next.host import main; main(restartable=True, container={container!r})'],
            )
            if stopping or code != RESTART_EXIT:
                return code if code >= 0 else 128 - code
            print('LenBot：旧宿主已退出，应用已选插件候选版本。', flush=True)
            code = launch([sys.executable, '-m', 'len_bot.next.maintenance.apply_plugins'])
            if stopping or code != 0:
                return code if code >= 0 else 128 - code
            print('LenBot：按根配置重新启动。', flush=True)
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def parse_arguments(argv: list[str] | None, *, container: bool = False) -> None:
    """Only --help and --version; everything else lives in the root file. Exits for those and bad options."""
    import argparse
    from importlib.metadata import PackageNotFoundError, version
    try:
        current = version('len-bot')
    except PackageNotFoundError:
        current = 'unknown'
    parser = argparse.ArgumentParser(
        prog='lenbot-container' if container else 'len-bot',
        description='启动 LenBot。当前目录为实例根目录，设置保存在 lenbot.config.json；'
                    '首次启动时打开配置向导。')
    parser.add_argument('--version', action='version', version=f'LenBot {current}')
    parser.parse_args(argv)


def announce_root(root: Path) -> None:
    if not (root / 'lenbot.config.json').exists():
        print(f'LenBot：首次配置，实例目录：{root}', flush=True)


def main(argv: list[str] | None = None) -> None:
    parse_arguments(argv)
    announce_root(Path.cwd())
    raise SystemExit(run())


# The image's lenbot user; the host container starts as root only to join the Docker socket's group.
CONTAINER_USER = 10000
DOCKER_SOCKET = Path('/var/run/docker.sock')


def drop_container_root(socket: Path = DOCKER_SOCKET) -> None:
    """Join the group of a mounted Docker socket, then run as the image's lenbot user."""
    if os.name != 'posix' or os.getuid() != 0:
        return
    groups = {CONTAINER_USER}
    try:
        groups.add(socket.stat().st_gid)
    except FileNotFoundError:
        pass
    os.setgroups(sorted(groups))
    os.setgid(CONTAINER_USER)
    os.setuid(CONTAINER_USER)
    # A plain `docker run` leaves root's HOME; the lenbot user's home is the instance root.
    if os.environ.get('HOME') in (None, '', '/root'):
        import pwd
        os.environ['HOME'] = pwd.getpwuid(CONTAINER_USER).pw_dir


def migrate_container_volume(root: Path) -> None:
    """A new image on an existing data volume: snapshot beside the instance, then migrate before the first start.

    The volume is mounted at the instance's parent, so snapshots in backups/ stay outside the saved paths.
    """
    from packaging.version import InvalidVersion, Version
    import secrets
    import time
    from .maintenance.upgrade import installed_release, record_release, recorded_release, upgrade_instance
    current = installed_release()
    if not (root / 'lenbot.config.json').exists():
        record_release(root)
        return
    previous = recorded_release(root)
    if previous == current:
        return
    try:
        newer = previous is not None and Version(previous) > Version(current)
    except InvalidVersion:
        newer = False
    if newer:
        raise SystemExit(f'LenBot：数据卷已由 {previous} 使用，当前镜像是 {current}。'
                         f'回到旧版本需要从 {root.parent / "backups"} 中的快照恢复，或改用 {previous} 的镜像。')
    snapshot = root.parent / 'backups' / (time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4))
    print(f'LenBot：实例数据来自{f" {previous}" if previous else "更早的版本"}，先保存快照 {snapshot}，再迁移到 {current}。', flush=True)
    upgrade_instance(root, snapshot)
    follow_release_worker(root, current)
    print('LenBot：迁移完成。', flush=True)


OFFICIAL_WORKERS = ('ghcr.io/lendevs/lenbot-worker', 'docker.io/lendevs/lenbot-worker', 'lendevs/lenbot-worker')


def follow_release_worker(root: Path, release: str) -> None:
    """An official task image follows the host's version, as the updater switches it; other images stay."""
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    worker = source.get('worker')
    if worker is None or worker.get('sandbox', 'docker') != 'docker':
        return
    name = worker['image'].split('@', 1)[0]
    head, slash, last = name.rpartition('/')
    repository = head + slash + last.split(':', 1)[0]
    if repository not in OFFICIAL_WORKERS or worker['image'] == f'{repository}:{release}':
        return
    worker['image'] = f'{repository}:{release}'
    from .storage.files import atomic_text
    atomic_text(path, json.dumps(source, ensure_ascii=False, indent=2) + '\n')
    print(f'LenBot：任务镜像改为 {worker["image"]}。', flush=True)


def container_main(argv: list[str] | None = None) -> None:
    drop_container_root()
    parse_arguments(argv, container=True)
    announce_root(Path.cwd())
    migrate_container_volume(Path.cwd())
    raise SystemExit(run(container=True))


if __name__ == '__main__':
    main()
