"""Assemble the Linux local sandbox's task runtime: Node, Pi and the task extension.

The directory is mounted read-only at ``/opt/lenbot`` in each bwrap task
sandbox (``worker.task_runtime``). Node and Pi versions match the worker image;
the Node archive is checked against the release's published SHA-256 list.
"""

import argparse
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NODE = '24.22.1'
PI = '@earendil-works/pi-coding-agent@0.87.1'
ARCHITECTURES = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}


def download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, destination.open('wb') as output:
        shutil.copyfileobj(response, output)


def node_archive(architecture: str, directory: Path) -> Path:
    name = f'node-v{NODE}-linux-{architecture}.tar.xz'
    base = f'https://nodejs.org/dist/v{NODE}/'
    sums, archive = directory / 'SHASUMS256.txt', directory / name
    download(base + 'SHASUMS256.txt', sums)
    expected = next(line.split()[0] for line in sums.read_text().splitlines() if line.endswith('  ' + name))
    download(base + name, archive)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f'{name} SHA-256 {actual} differs from the published {expected}')
    return archive


def build(output: Path, architecture: str) -> None:
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
                        '--ignore-scripts', '--no-fund', '--no-audit', PI],
                       check=True, env={'PATH': f'{node}:/usr/bin:/bin', 'HOME': directory})
        shutil.copy2(ROOT / 'docker' / 'next-worker' / 'lenbot-extension.ts', staging / 'lenbot-extension.ts')
        (staging / 'bin').mkdir()
        shutil.copytree(staging, output, symlinks=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--architecture', choices=sorted(set(ARCHITECTURES.values())),
                        default=ARCHITECTURES.get(platform.machine().lower()))
    arguments = parser.parse_args()
    build(arguments.output.resolve(), arguments.architecture)
    print(arguments.output.resolve())


if __name__ == '__main__':
    main()
