"""Hold one host child; only an explicit, clean restart launches another."""

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
        description='启动 LenBot 宿主。当前目录就是实例根目录：读取其中的 lenbot.config.json；'
                    '还没有配置时，在当前目录开始首次配置向导。所有设置都写在根配置里，没有其他命令行参数。')
    parser.add_argument('--version', action='version', version=f'LenBot {current}')
    parser.parse_args(argv)


def announce_root(root: Path) -> None:
    if not (root / 'lenbot.config.json').exists():
        print(f'LenBot：实例根目录是 {root}，这里还没有 lenbot.config.json，将在此目录开始首次配置。'
              '如果目录不对，请按 Ctrl+C 停止，换到实例目录后再启动。', flush=True)


def main(argv: list[str] | None = None) -> None:
    parse_arguments(argv)
    announce_root(Path.cwd())
    raise SystemExit(run())


def container_main(argv: list[str] | None = None) -> None:
    parse_arguments(argv, container=True)
    announce_root(Path.cwd())
    raise SystemExit(run(container=True))


if __name__ == '__main__':
    main()
