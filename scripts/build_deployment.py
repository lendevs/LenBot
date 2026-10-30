"""Package the built wheel into deployment packages that start after unpacking.

Each package holds a stand-alone CPython with the host and its locked dependencies installed, uv for plugin
dependencies, the update controller and the start scripts. Linux packages also hold the local sandbox's task
runtime: Node, Pi, the task extension, the task Python libraries and the browser library for the HTML renderer.
Every platform is assembled on this machine from binary wheels and pinned downloads.

    lenbot-<version>-<platform>/
      run, service (Linux) or run.cmd, run.ps1, service.ps1 (Windows)
      releases/<version>/{python, bin/uv, updater, task-runtime, release.json}
"""

import hashlib
import json
from pathlib import Path
import platform as platform_module
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from email.parser import BytesParser

from build_task_runtime import NODE, PI, node_archive

PYTHON, PYTHON_BUILD, UV = '3.13.16', '20261013', '0.12.13'
PLAYWRIGHT = 'playwright-core@1.62.0'
PLATFORMS = {
    'windows-x64': {
        'triple': 'x86_64-pc-windows-msvc',
        'python': '7aba3985d4cee1c7cacb963ca6aa08a5d3e695d7f9609d9fabc56f22ddcf5a06',
        'uv': ('uv-x86_64-pc-windows-msvc.zip', 'a86c9dc7bad9b03f388583b7187c05fe9951c2e0d392217e8fd43d97787f6ec2'),
    },
    'linux-x64': {
        'triple': 'x86_64-unknown-linux-gnu', 'node': 'x64',
        'python': 'd0080766b6b74aeb81e1949ef0d9a20e6c17f7b160fb295a69b936ccb17660be',
        'uv': ('uv-x86_64-unknown-linux-gnu.tar.gz', '745765a3b6e360ad76743599ae5c42e9278c7edf8bbff9fc76d05bf2623a04dd'),
    },
    'linux-arm64': {
        'triple': 'aarch64-unknown-linux-gnu', 'node': 'arm64',
        'python': '69a30ed26198178732c37b8de0b6b5191479fbacfe526954da776befe38f18e7',
        'uv': ('uv-aarch64-unknown-linux-gnu.tar.gz', '2eaa5d94f5db7b3a1a092156b9420459e42ab0217d917fe74a876309cef9b5e9'),
    },
}
SCRIPTS = {'windows': ('run.cmd', 'run.ps1', 'service.ps1'), 'linux': ('run', 'service')}


def bundle_name(version: str, platform: str) -> str:
    return f'lenbot-{version}-{platform}' + ('.zip' if platform.startswith('windows') else '.tar.gz')


def fetch(url: str, destination: Path, sha256: str) -> Path:
    if not destination.exists():
        partial = destination.with_name(destination.name + '.part')
        with urllib.request.urlopen(url, timeout=300) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output)
        partial.rename(destination)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != sha256:
        destination.unlink()
        raise ValueError(f'{destination.name} SHA-256 {actual} differs from the pinned {sha256}')
    return destination


def unpack(archive: Path, destination: Path, *, skip: tuple[str, ...] = ()) -> None:
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as source:
            source.extractall(destination)
    else:
        with tarfile.open(archive) as source:
            members = [item for item in source.getmembers() if not item.name.startswith(skip)]
            source.extractall(destination, members=members, filter='tar')


def site_packages(python: Path, platform: str) -> Path:
    return python / ('Lib/site-packages' if platform.startswith('windows') else f'lib/python{PYTHON.rsplit(".", 1)[0]}/site-packages')


def install(platform: str, target: Path, *requirements: str) -> None:
    """Binary wheels only, resolved for the package's platform rather than this machine's."""
    subprocess.run(['uv', 'pip', 'install', '--no-cache', '--target', str(target),
                    '--python-platform', PLATFORMS[platform]['triple'], '--python-version', PYTHON.rsplit('.', 1)[0],
                    '--only-binary', ':all:', *requirements], check=True)


def task_runtime(project: Path, platform: str, downloads: Path, destination: Path) -> None:
    """The directory bwrap mounts read-only at /opt/lenbot; the same programs as the worker image."""
    architecture = PLATFORMS[platform]['node']
    node = node_archive(architecture, downloads)
    with tempfile.TemporaryDirectory() as directory:
        unpack(node, Path(directory))
        shutil.move(Path(directory) / f'node-v{NODE}-linux-{architecture}', destination / 'node')
    # Node packages are JavaScript only; this machine's npm installs them for any architecture.
    subprocess.run(['npm', 'install', '--global', '--prefix', str(destination / 'node'), '--ignore-scripts',
                    '--no-fund', '--no-audit', PI], check=True)
    # npm installs esbuild's binaries for every platform; only this package's one can run.
    for binary in list((destination / 'node/lib/node_modules').rglob('@esbuild/*')):
        if binary.is_dir() and binary.parent.name == '@esbuild' and binary.name != f'linux-{architecture}':
            shutil.rmtree(binary)
    subprocess.run(['npm', 'install', '--prefix', str(destination / 'browser'), '--ignore-scripts', '--no-fund',
                    '--no-audit', '--save-exact', PLAYWRIGHT], check=True)
    worker = project / 'docker/next-worker'
    for name in ('lenbot-extension.ts', 'matplotlibrc', 'browser-files.cjs'):
        shutil.copy2(worker / name, destination / name)
    # bin/ lists the programs a task can call; lenbot-render joins it once a Chromium is available.
    (destination / 'bin').mkdir()
    shutil.copy2(worker / 'lenbot-render.cjs', destination / 'lenbot-render.cjs')
    install(platform, destination / 'python', '--requirement', str(worker / 'task-python.txt'))


def release_directory(wheel: Path, requirements: Path, project: Path, platform: str, version: str,
                      downloads: Path, release: Path) -> None:
    triple = PLATFORMS[platform]['triple']
    name = f'cpython-{PYTHON}+{PYTHON_BUILD}-{triple}-install_only_stripped.tar.gz'
    archive = fetch(f'https://github.com/astral-sh/python-build-standalone/releases/download/{PYTHON_BUILD}/{name}',
                    downloads / name, PLATFORMS[platform]['python'])
    # Terminal descriptions serve curses only, and differ just by case on case-insensitive build machines.
    unpack(archive, release, skip=('python/share/terminfo/',))
    install(platform, site_packages(release / 'python', platform), '--requirement', str(requirements), str(wheel))
    uv_name, uv_sha = PLATFORMS[platform]['uv']
    uv_archive = fetch(f'https://github.com/astral-sh/uv/releases/download/{UV}/{uv_name}', downloads / uv_name, uv_sha)
    with tempfile.TemporaryDirectory() as directory:
        unpack(uv_archive, Path(directory))
        (release / 'bin').mkdir()
        for program in Path(directory).rglob('uv*'):
            if program.is_file() and program.name in ('uv', 'uv.exe'):
                shutil.copy2(program, release / 'bin' / program.name)
    shutil.copytree(project / 'deploy/updater', release / 'updater', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if platform.startswith('linux'):
        (release / 'task-runtime').mkdir()
        task_runtime(project, platform, downloads, release / 'task-runtime')
    for resource in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(project / resource, release / resource)
    (release / 'release.json').write_text(json.dumps({
        'version': version, 'platform': platform, 'python': PYTHON, 'uv': UV, 'wheel': wheel.name,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def current_platform() -> str | None:
    """This machine's package platform, or None where no package is published (macOS)."""
    machine = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform_module.machine().lower())
    name = {'linux': 'linux', 'win32': 'windows'}.get(sys.platform)
    return f'{name}-{machine}' if name and machine and f'{name}-{machine}' in PLATFORMS else None


def build_deployments(wheel: Path, project: Path, output: Path, requirements: Path,
                      downloads: Path | None = None, platforms: tuple[str, ...] = tuple(PLATFORMS)) -> list[Path]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_path, = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        version = BytesParser().parsebytes(archive.read(metadata_path))['Version']
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        downloads = Path(temporary) / 'downloads' if downloads is None else downloads
        downloads.mkdir(parents=True, exist_ok=True)
        for platform in platforms:
            name = f'lenbot-{version}-{platform}'
            bundle = Path(temporary) / name
            release = bundle / 'releases' / version
            release.mkdir(parents=True)
            release_directory(wheel, requirements, project, platform, version, downloads, release)
            for script in SCRIPTS[platform.split('-')[0]]:
                target = bundle / script
                target.write_bytes((project / 'deploy/package' / script).read_bytes().replace(b'@VERSION@', version.encode()))
                target.chmod(0o755 if '.' not in script else 0o644)
            for resource in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
                shutil.copy2(project / resource, bundle / resource)
            destination = output / bundle_name(version, platform)
            if platform.startswith('windows'):
                with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
                    for file in sorted(bundle.rglob('*')):
                        if file.is_file():
                            archive.write(file, file.relative_to(bundle.parent).as_posix())
            else:
                with tarfile.open(destination, 'x:gz') as archive:
                    archive.add(bundle, arcname=name)
            shutil.rmtree(bundle)
            results.append(destination)
    return results
