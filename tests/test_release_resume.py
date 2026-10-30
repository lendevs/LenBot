"""Run the publisher through a filesystem-backed GitHub CLI peer, then download its release over HTTP."""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import threading

import pytest

from test_release_scripts import load, SCRIPTS

# The publisher runs in the Linux release job; its GitHub CLI peer here is a script started through its shebang.
pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='the fake gh peer is a POSIX executable script')


@pytest.fixture
def release_peer(tmp_path):
    remote = tmp_path / 'remote'
    remote.mkdir()
    (remote / 'uploads').mkdir()
    executable = tmp_path / 'bin/gh'
    executable.parent.mkdir()
    executable.write_text(f'#!{sys.executable}\n' + '''
import hashlib, json, os, shutil, sys
from pathlib import Path
root = Path(os.environ['RELEASE_PEER'])
state = root / 'release.json'
args = sys.argv[1:]
with (root / 'commands.jsonl').open('a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:4] == ['api', '--paginate', '--slurp', 'repos/example/project/releases']:
    print(json.dumps([[json.loads(state.read_text())] if state.exists() else []]))
elif args[:2] == ['release', 'create']:
    assert not state.exists()
    state.write_text(json.dumps({'tag_name': args[2], 'prerelease': '--prerelease' in args, 'draft': False, 'assets': []}))
elif args[:2] == ['release', 'upload']:
    source = Path(args[3])
    destination = root / 'uploads' / source.name
    assert not destination.exists(), 'the CLI must never replace an asset'
    shutil.copyfile(source, destination)
    release = json.loads(state.read_text())
    release['assets'].append({'name': source.name, 'size': source.stat().st_size,
                             'digest': 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()})
    state.write_text(json.dumps(release))
    stop = root / 'interrupt-after'
    if stop.exists() and stop.read_text() == source.name:
        stop.unlink()
        sys.exit('connection lost after the server accepted the upload')
else:
    sys.exit('unexpected CLI command: ' + repr(args))
''')
    executable.chmod(0o755)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    version = '0.2.0'
    bundle = artifacts / f'lenbot-{version}-linux.tar.gz'
    with tarfile.open(bundle, 'w:gz') as archive:
        data = json.dumps({'version': version, 'platform': 'linux'}).encode()
        info = tarfile.TarInfo(f'lenbot-{version}-linux/release.json')
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    (artifacts / 'release-notes.md').write_text('# LenBot 0.2.0\n\n本版说明。\n')
    (artifacts / 'source-revision.txt').write_text('synthetic-fixed-revision\n')
    metadata = load('release_metadata')
    # Use the actual manifest writer with this small release project, not another manifest format.
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'pyproject.toml').write_text('[project]\nversion="0.2.0"\n')
    for name in ('plugin.py', 'next/config.py', 'next/storage/store.py', 'next/memory/jobs.py', 'next/memory/local.py'):
        source = SCRIPTS.parent / 'src/len_bot' / name
        target = project / 'src/len_bot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    def manifest():
        return metadata.write_manifest(project, artifacts, revision='synthetic-fixed-revision')

    manifest()
    environment = {**os.environ, 'PATH': str(executable.parent) + os.pathsep + os.environ['PATH'],
                   'RELEASE_PEER': str(remote), 'GITHUB_REPOSITORY': 'example/project'}

    def publish():
        return subprocess.run([sys.executable, str(SCRIPTS / 'publish_release.py'), str(artifacts)],
                              env=environment, text=True, capture_output=True, timeout=10)

    return artifacts, remote, manifest, publish


@contextmanager
def downloads(directory):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_interrupted_upload_resumes_without_replacing_assets_and_finishes_install_manifest(release_peer, tmp_path):
    artifacts, remote, _, publish = release_peer
    (remote / 'interrupt-after').write_text('release-notes.md')
    failed = publish()
    assert failed.returncode != 0 and 'connection lost' in failed.stderr
    assert sorted(path.name for path in (remote / 'uploads').iterdir()) == [
        'lenbot-0.2.0-linux.tar.gz', 'release-notes.md']
    resumed = publish()
    assert resumed.returncode == 0, resumed.stderr
    assert 'Retaining matching Release asset: lenbot-0.2.0-linux.tar.gz' in resumed.stdout
    commands = [json.loads(line) for line in (remote / 'commands.jsonl').read_text().splitlines()]
    uploads = [Path(command[3]).name for command in commands if command[:2] == ['release', 'upload']]
    assert uploads == ['lenbot-0.2.0-linux.tar.gz', 'release-notes.md', 'source-revision.txt', 'release-manifest.json']
    assert len([command for command in commands if command[:2] == ['release', 'create']]) == 1
    assert publish().returncode == 0
    assert all((remote / 'uploads' / path.name).read_bytes() == path.read_bytes() for path in artifacts.iterdir())

    sys.path.insert(0, str(SCRIPTS.parent / 'deploy/updater'))
    from common import download, fetch_json, release_manifest
    destination = tmp_path / 'downloaded'
    destination.mkdir()
    with downloads(remote / 'uploads') as base:
        manifest = release_manifest(fetch_json(base + '/release-manifest.json'))
        for name, expected in manifest['files'].items():
            download(base + '/' + name, destination / name, expected)
    bundle = destination / manifest['bundles']['linux']
    with tarfile.open(bundle) as archive:
        archive.extractall(destination / 'unpacked', filter='data')
    assert json.loads((destination / 'unpacked/lenbot-0.2.0-linux/release.json').read_text()) == {
        'version': manifest['version'], 'platform': 'linux'}


@pytest.mark.parametrize('conflict', ['content', 'channel', 'draft', 'extra'])
def test_existing_release_conflicts_are_rejected_before_any_missing_upload(release_peer, conflict):
    artifacts, remote, manifest, publish = release_peer
    (remote / 'interrupt-after').write_text('release-notes.md')
    assert publish().returncode != 0
    if conflict == 'content':
        (artifacts / 'release-notes.md').write_text('另一次构建的内容')
        manifest()
        state = remote / 'release.json'
        release = json.loads(state.read_text())
        release['assets'] = [asset for asset in release['assets'] if asset['name'] != 'lenbot-0.2.0-linux.tar.gz']
        state.write_text(json.dumps(release))
        (remote / 'uploads/lenbot-0.2.0-linux.tar.gz').unlink()
    else:
        state = remote / 'release.json'
        release = json.loads(state.read_text())
        if conflict == 'extra':
            release['assets'].append({'name': 'other-batch.bin', 'digest': 'sha256:' + 'a' * 64})
        else:
            release['prerelease' if conflict == 'channel' else 'draft'] = True
        state.write_text(json.dumps(release))
    before = (remote / 'commands.jsonl').read_text().splitlines()
    refused = publish()
    assert refused.returncode != 0 and ('differs' in refused.stderr)
    after = (remote / 'commands.jsonl').read_text().splitlines()
    assert len(after) == len(before) + 1  # Only the release listing, no new upload.
    assert not (remote / 'uploads/source-revision.txt').exists()


@pytest.mark.parametrize('invalid', ['changed', 'missing', 'extra'])
def test_incomplete_or_changed_local_batch_never_creates_release(release_peer, invalid):
    artifacts, remote, _, publish = release_peer
    path = artifacts / 'source-revision.txt'
    if invalid == 'changed':
        path.write_text('different revision\n')
    elif invalid == 'missing':
        path.unlink()
    else:
        (artifacts / 'unlisted.bin').write_bytes(b'extra')
    result = publish()
    assert result.returncode != 0 and 'manifest' in result.stderr
    assert not (remote / 'release.json').exists()
    assert not (remote / 'commands.jsonl').exists()
