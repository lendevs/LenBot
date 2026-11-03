"""Hold one host child; a clean restart or a requested version switch launches the next one."""

import os
from pathlib import Path
import signal
import subprocess
import sys

from .deployment import STOPPING, Deployment, Switch, image_version, wait_ready
from .runtime.lifecycle import RESTART_EXIT, UPDATE_EXIT

# Windows has no signal another program can send to a console process; service.ps1 stop writes this file.
STOP_FILE = 'stop'


def run(*, container: bool = False, deployment: Deployment | None = None) -> int:
    root = Path.cwd()
    project = Path(__file__).resolve().parents[3]
    source_panel = deployment is None and not container and (project / '.git').exists() \
        and (project / 'src/len_bot/web/frontend').is_dir()
    child: subprocess.Popen | None = None
    stopping = False
    stop_file = None if deployment is None else deployment.updates / STOP_FILE
    if stop_file is not None:
        stop_file.unlink(missing_ok=True)

    def stop(signum, frame) -> None:
        nonlocal stopping
        stopping = True
        if child is not None:
            child.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signum)

    signals = (signal.SIGINT, signal.SIGTERM) if sys.platform != 'win32' else (signal.SIGINT, signal.SIGTERM, signal.SIGBREAK)
    previous = {sig: signal.signal(sig, stop) for sig in signals}

    def stop_requested() -> bool:
        if stop_file is not None and stop_file.exists():
            stop_file.unlink(missing_ok=True)
            stop(signal.SIGTERM, None)
        return stopping

    def wait(process: subprocess.Popen) -> int:
        """Wait in short steps: on Windows an untimed wait blocks signal handlers, so a stop could not be passed on."""
        while True:
            try:
                return process.wait(0.5)
            except subprocess.TimeoutExpired:
                stop_requested()

    def start(command: list[str], cwd: Path = root, env: dict | None = None) -> subprocess.Popen:
        nonlocal child
        child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=sys.platform != 'win32',
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0)
        if stopping:
            child.terminate()
        return child

    def finish(process: subprocess.Popen) -> int:
        nonlocal child
        code = wait(process)
        child = None
        return code

    def end(process: subprocess.Popen) -> None:
        """Stop a host that started but did not become ready."""
        process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM)
        try:
            process.wait(180)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    switch = None if deployment is None else Switch(deployment)
    trial: dict = {}
    try:
        while not stopping:
            if source_panel:
                code = finish(start(['node', str(project / 'scripts/frontend_build.cjs')], project))
                if stopping or code != 0:
                    return code if code >= 0 else 128 - code
            version = None if deployment is None else deployment.selected()
            python = sys.executable if deployment is None else str(deployment.python(version))
            env = None if deployment is None else deployment.environment(version)
            # This argument enables lifecycle control only; all settings come from the root file.
            host = start([python, '-c', f'from len_bot.next.host import main; main(restartable=True, container={container!r})'],
                         env=env)
            if trial:
                problem = wait_ready(root, trial['version'], host.poll, stop_requested)
                if problem == STOPPING:
                    code = finish(host)
                    switch.interrupted(trial)
                    return code if code >= 0 else 128 - code
                if problem is not None:
                    end(host)
                    child = None
                switch.settle(trial, problem)
                trial = {}
                if problem is not None:
                    continue
            code = finish(host)
            if stopping:
                return code if code >= 0 else 128 - code
            if code == UPDATE_EXIT and switch is not None and (request := switch.pending()) is not None:
                trial = switch.prepare(request)
                continue
            if code != RESTART_EXIT:
                return code if code >= 0 else 128 - code
            print('LenBot：旧宿主已退出，应用已选插件候选版本。', flush=True)
            code = finish(start([python, '-m', 'len_bot.next.maintenance.apply_plugins'], env=env))
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
    from .deployment import follow_release
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
    upgrade_instance(root, snapshot, discard_restored=True)
    follow_release(Deployment('docker', root.parent), previous or '', current)
    print('LenBot：迁移完成。', flush=True)


def container_main(argv: list[str] | None = None) -> None:
    drop_container_root()
    parse_arguments(argv, container=True)
    # Outside the image (a development run of this entry point) there is no version to choose between.
    deployment = Deployment('docker', Path.cwd().parent) if image_version() is not None else None
    selected = None if deployment is None else deployment.selected()
    python = None if deployment is None else deployment.python(selected)
    if python is not None and Path(sys.prefix).resolve() != python.parent.parent.resolve():
        # A version the panel installed into the volume is newer than the image: its launcher runs instead.
        os.execv(python, [str(python), '-B', '-c', 'from len_bot.next.launcher import container_main; container_main()',
                          *(sys.argv[1:] if argv is None else argv)])
    if deployment is not None and deployment.pointer.exists() and selected == image_version():
        # The image caught up with (or passed) what the panel installed; the volume copies are no longer used.
        deployment.prune(set())
        deployment.pointer.unlink(missing_ok=True)
    announce_root(Path.cwd())
    migrate_container_volume(Path.cwd())
    raise SystemExit(run(container=True, deployment=deployment))


def package_main(argv: list[str] | None = None) -> None:
    """Start from an unpacked deployment package: ``python -m len_bot.next.launcher <package directory>``."""
    arguments = sys.argv[1:] if argv is None else argv
    parse_arguments(arguments[1:])
    deployment = Deployment('package', Path(arguments[0]).resolve())
    if not deployment.pointer.exists():
        # First start: the release this interpreter belongs to (releases/<version>/python/...).
        # The interpreter itself may be a link; its directory is inside the release.
        release = next(path for path in Path(sys.executable).parent.resolve().parents
                       if path.parent == deployment.versions.resolve())
        deployment.select(release.name)
    deployment.instance.mkdir(mode=0o700, exist_ok=True)
    os.chdir(deployment.instance)
    announce_root(deployment.instance)
    raise SystemExit(run(deployment=deployment))


if __name__ == '__main__':
    package_main()
