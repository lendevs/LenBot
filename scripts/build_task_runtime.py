"""Assemble the Linux local sandbox's task runtime: Node, Pi and the task extension.

The directory is mounted read-only at ``/opt/lenbot`` in each bwrap task
sandbox (``worker.task_runtime``). Node and Pi versions match the worker image;
the Node archive is checked against the release's published SHA-256 list.
The task Python libraries (``docker/next-worker/task-python.txt``) go to
``python/`` for the interpreter that runs the host, which the sandbox exposes
as ``python3``; ``--python`` names that interpreter when it is not this one.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NODE = '24.22.1'
PI = '@earendil-works/pi-coding-agent@0.87.1'
ARCHITECTURES = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}
ELF_MACHINES = {'x64': 62, 'arm64': 183}
# Optional packages that exist once per platform are named after it, e.g. @esbuild/linux-arm64.
PLATFORM_NAME = re.compile(r'(?:^|[/-])(?:aix|android|darwin|freebsd|linux|netbsd|openbsd|openharmony|sunos|win32)-[a-z0-9_]+')


def npm_platform(architecture: str, npm: str = 'npm') -> list[str]:
    """npm flags that resolve optional dependencies for the package's platform, not the build machine's.

    ``--libc`` exists from some npm 10 releases on; where npm does not list it, it is left out.
    """
    options = json.loads(subprocess.run([npm, 'config', 'list', '--long', '--json'], check=True,
                                        capture_output=True, text=True).stdout)
    return ['--os=linux', f'--cpu={architecture}', *(['--libc=glibc'] if 'libc' in options else [])]


def prune_node_modules(root: Path, architecture: str) -> None:
    """Keep only the binaries of linux-<architecture>: other esbuild packages and Pi's native prebuilds."""
    for directory in list(root.rglob('node_modules/@esbuild/*')):
        if directory.is_dir() and directory.name != f'linux-{architecture}':
            shutil.rmtree(directory)
    for prebuilds in list(root.rglob('prebuilds')):
        if prebuilds.is_dir() and 'node_modules' in prebuilds.parts:
            for directory in list(prebuilds.iterdir()):
                if directory.is_dir() and PLATFORM_NAME.search(directory.name) and directory.name != f'linux-{architecture}':
                    shutil.rmtree(directory)


def _package(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def missing_platform_packages(root: Path, architecture: str) -> list[str]:
    """Packages in the tree that list per-platform optional dependencies but have none for linux-<architecture>.

    npm skips optional packages that do not fit the platform it resolves for, and reports nothing when that
    platform is wrong; a runtime built that way starts and then fails when it first needs the binary.
    """
    installed: dict[str, list[dict]] = {}
    owners: dict[str, set[str]] = {}
    for manifest in root.rglob('package.json'):
        if 'node_modules' not in manifest.parts or (package := _package(manifest)) is None:
            continue
        if isinstance(name := package.get('name'), str):
            installed.setdefault(name, []).append(package)
            platform_names = {optional for optional in package.get('optionalDependencies') or {}
                              if PLATFORM_NAME.search(optional)}
            if platform_names:
                owners.setdefault(name, set()).update(platform_names)

    def fits(package: dict) -> bool:
        return (architecture in (package.get('cpu') or []) and 'linux' in (package.get('os') or [])
                and (not package.get('libc') or 'glibc' in package['libc']))
    return sorted(f'{owner}: no package for linux-{architecture}' for owner, names in owners.items()
                  if not any(fits(package) for name in names for package in installed.get(name, [])))


def elf_machine(path: Path) -> int | None:
    """The ELF ``e_machine`` of a file, or None when it is not an ELF file."""
    with path.open('rb') as file:
        header = file.read(20)
    if len(header) < 20 or header[:4] != b'\x7fELF':
        return None
    return int.from_bytes(header[18:20], 'big' if header[5] == 2 else 'little')


def wrong_architecture(*roots: Path, architecture: str) -> list[str]:
    """ELF files (executables, .so, .node) under the roots built for another machine type."""
    expected = ELF_MACHINES[architecture]
    problems = []
    for root in roots:
        for directory, _, names in os.walk(root):
            for name in names:
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    continue
                if (machine := elf_machine(path)) not in (None, expected):
                    problems.append(f'{path}: ELF machine {machine}, linux-{architecture} needs {expected}')
    return sorted(problems)


def check_runtime(runtime: Path, architecture: str, *others: Path) -> None:
    """Fail the build when the runtime would carry another platform's binaries or lack its own."""
    problems = missing_platform_packages(runtime, architecture) + wrong_architecture(
        runtime, *others, architecture=architecture)
    if problems:
        raise RuntimeError(f'Task runtime does not fit linux-{architecture}:\n' + '\n'.join(problems))


def download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, destination.open('wb') as output:
        shutil.copyfileobj(response, output)


def node_archive(architecture: str, directory: Path) -> Path:
    name = f'node-v{NODE}-linux-{architecture}.tar.xz'
    base = f'https://nodejs.org/dist/v{NODE}/'
    sums, archive = directory / 'SHASUMS256.txt', directory / name
    if not sums.exists():
        download(base + 'SHASUMS256.txt', sums)
    expected = next(line.split()[0] for line in sums.read_text().splitlines() if line.endswith('  ' + name))
    # A directory shared between builds keeps an archive that already matches.
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        download(base + name, archive)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f'{name} SHA-256 {actual} differs from the published {expected}')
    return archive


def build(output: Path, architecture: str, python: Path) -> None:
    if output.exists():
        raise FileExistsError(f'{output} already exists; choose a new directory')
    with tempfile.TemporaryDirectory() as directory:
        archive = node_archive(architecture, Path(directory))
        staging = Path(directory) / 'runtime'
        with tarfile.open(archive) as source:
            source.extractall(staging, filter='tar')
        (staging / f'node-v{NODE}-linux-{architecture}').rename(staging / 'node')
        node = staging / 'node' / 'bin'
        subprocess.run([str(node / 'npm'), 'install', '--global', '--prefix', str(staging / 'node'),
                        '--ignore-scripts', '--no-fund', '--no-audit', *npm_platform(architecture), PI],
                       check=True, env={'PATH': f'{node}:/usr/bin:/bin', 'HOME': directory})
        prune_node_modules(staging / 'node', architecture)
        shutil.copy2(ROOT / 'docker' / 'next-worker' / 'lenbot-extension.ts', staging / 'lenbot-extension.ts')
        uv = shutil.which('uv')
        if uv is None:
            raise FileNotFoundError('uv is required to install the task Python libraries')
        subprocess.run([uv, 'pip', 'install', '--no-cache', '--python', str(python), '--target', str(staging / 'python'),
                        '--requirement', str(ROOT / 'docker' / 'next-worker' / 'task-python.txt')], check=True)
        shutil.copy2(ROOT / 'docker' / 'next-worker' / 'matplotlibrc', staging / 'matplotlibrc')
        (staging / 'bin').mkdir()
        check_runtime(staging, architecture)
        shutil.copytree(staging, output, symlinks=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--architecture', choices=sorted(set(ARCHITECTURES.values())),
                        default=ARCHITECTURES.get(platform.machine().lower()))
    parser.add_argument('--python', type=Path, default=Path(sys.executable),
                        help='interpreter that runs the LenBot host (default: this one)')
    arguments = parser.parse_args()
    build(arguments.output.resolve(), arguments.architecture, arguments.python)
    print(arguments.output.resolve())


if __name__ == '__main__':
    main()
