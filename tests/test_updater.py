"""The panel's update: download and unpack beside the running version, then the launcher's switch and rollback."""

import asyncio
import hashlib
import io
import json
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from len_bot.next import deployment as deployment_module
from len_bot.next.deployment import Deployment, Switch, wait_ready
from len_bot.next.plugins.catalog import CatalogView, SourcedEntry, updates
from len_bot.next.runtime.updater import PROTOCOL, Updater


def _install(deployment: Deployment, version: str, platform: str = 'linux-x64') -> None:
    """A package release directory with a placeholder interpreter."""
    python = deployment.python(version)
    python.parent.mkdir(parents=True)
    python.write_text('')
    (deployment.directory(version) / 'release.json').write_text(json.dumps({'version': version, 'platform': platform}))


def _bundle(version: str, platform: str) -> bytes:
    data = io.BytesIO()
    python = 'python/python.exe' if sys.platform == 'win32' else 'python/bin/python3'
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, content in ((f'releases/{version}/release.json', json.dumps({'version': version, 'platform': platform})),
                              (f'releases/{version}/{python}', '')):
            item = tarfile.TarInfo(f'lenbot-{version}-{platform}/{name}')
            item.size = len(content.encode())
            archive.addfile(item, io.BytesIO(content.encode()))
    return data.getvalue()


class Files:
    """Release assets over HTTP, as GitHub serves them after its redirect."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = outer.files.get(self.path.lstrip('/'))
                self.send_response(404 if body is None else 200)
                self.send_header('Content-Length', str(len(body or b'')))
                self.end_headers()
                self.wfile.write(body or b'')

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/'

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()


def _release(files: Files, version: str, manifest: dict) -> dict:
    return {'tag': 'v' + version, 'version': version,
            'assets': {name: files.url + name for name in [*files.files, 'release-manifest.json']}}


def _manifest(version: str, files: dict[str, bytes], platform: str) -> dict:
    return {'manifest_version': 1, 'updater_protocol': PROTOCOL, 'version': version, 'tag': 'v' + version,
            'bundles': {platform: f'lenbot-{version}-{platform}.tar.gz'},
            'files': {name: {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)} for name, body in files.items()}}


@pytest.mark.asyncio
@pytest.mark.parametrize('tampered', [False, True])
async def test_package_update_unpacks_the_release_writes_the_request_and_exits(tmp_path, tampered):
    deployment = Deployment('package', tmp_path)
    _install(deployment, '0.1.0')
    deployment.select('0.1.0')
    bundle = _bundle('0.2.0', 'linux-x64')
    assets = {'lenbot-0.2.0-linux-x64.tar.gz': bundle}
    manifest = _manifest('0.2.0', assets, 'linux-x64')
    if tampered:
        assets['lenbot-0.2.0-linux-x64.tar.gz'] = bundle[:-1] + bytes([bundle[-1] ^ 1])
    exited = asyncio.Event()

    async def exit_for_update():
        exited.set()

    with Files({**assets, 'release-manifest.json': json.dumps(manifest).encode()}) as files:
        updater = Updater(deployment, '0.1.0', exit_for_update=exit_for_update)
        updater.start(_release(files, '0.2.0', manifest), plugins=True)
        await updater.task
    if tampered:
        assert updater.state()['stage'] == 'failed' and '校验和' in updater.state()['error']
        assert not exited.is_set() and not deployment.installed('0.2.0')
        assert not (deployment.updates / 'request.json').exists()
        return
    assert exited.is_set() and updater.state()['stage'] == 'restart'
    assert deployment.installed('0.2.0') and deployment.selected() == '0.1.0'
    request = json.loads((deployment.updates / 'request.json').read_text())
    assert (request['action'], request['version'], request['from'], request['plugins']) == ('update', '0.2.0', '0.1.0', True)
    assert not (deployment.updates / 'downloads').exists()


@pytest.mark.asyncio
async def test_a_release_for_another_updater_protocol_is_refused_before_downloading(tmp_path):
    deployment = Deployment('package', tmp_path)
    _install(deployment, '0.1.0')
    deployment.select('0.1.0')
    manifest = {**_manifest('0.2.0', {}, 'linux-x64'), 'updater_protocol': PROTOCOL + 1}

    async def exit_for_update():
        raise AssertionError('not reached')

    with Files({'release-manifest.json': json.dumps(manifest).encode()}) as files:
        updater = Updater(deployment, '0.1.0', exit_for_update=exit_for_update)
        updater.start(_release(files, '0.2.0', manifest), plugins=False)
        await updater.task
    assert updater.state()['stage'] == 'failed' and '发行清单格式' in updater.state()['error']


class Recorder(Switch):
    """The launcher's switch with the maintenance commands recorded instead of run."""

    def __init__(self, deployment, failing: set[str] = frozenset()):
        super().__init__(deployment)
        self.calls, self.failing = [], failing

    def maintenance(self, version, action, snapshot=None):
        self.calls.append((version, action))
        if action in self.failing:
            raise RuntimeError(f'{action} failed')
        if action == 'backup':
            snapshot.mkdir(parents=True)


def _deployment(tmp_path) -> Deployment:
    deployment = Deployment('package', tmp_path)
    for version in ('0.0.9', '0.1.0', '0.2.0'):
        _install(deployment, version)
    deployment.select('0.1.0')
    deployment.instance.mkdir()
    (deployment.instance / 'lenbot.config.json').write_text('{}')
    return deployment


def test_switch_migrates_with_the_new_version_and_keeps_it_once_ready(tmp_path):
    deployment = _deployment(tmp_path)
    switch = Recorder(deployment)
    trial = switch.prepare({'action': 'update', 'version': '0.2.0', 'plugins': True})
    assert switch.calls == [('0.1.0', 'backup'), ('0.2.0', 'apply')] and deployment.selected() == '0.2.0'
    switch.settle(trial, None)
    result = json.loads(switch.result_path.read_text())
    assert (result['status'], result['from'], result['to'], result['plugins']) == ('complete', '0.1.0', '0.2.0', 'pending')
    # The previous version stays for its snapshot; older ones are removed.
    assert deployment.kept() == {'0.1.0', '0.2.0'}
    snapshot, = deployment.snapshots()
    assert snapshot['version'] == '0.1.0' and snapshot['restorable'] and snapshot['name'] == result['snapshot']
    assert not switch.request_path.exists()


def test_switch_puts_the_previous_version_and_snapshot_back_when_the_new_one_does_not_start(tmp_path):
    deployment = _deployment(tmp_path)
    switch = Recorder(deployment)
    trial = switch.prepare({'action': 'update', 'version': '0.2.0'})
    switch.settle(trial, '新版本退出，退出码 1')
    result = json.loads(switch.result_path.read_text())
    assert result['status'] == 'rolled_back' and result['error'] == '新版本退出，退出码 1'
    assert switch.calls[-1] == ('0.1.0', 'restore') and deployment.selected() == '0.1.0'
    assert '0.2.0' not in deployment.kept()


def test_failed_migration_rolls_back_before_any_start_and_a_failed_snapshot_changes_nothing(tmp_path):
    deployment = _deployment(tmp_path)
    switch = Recorder(deployment, failing={'apply'})
    assert switch.prepare({'action': 'update', 'version': '0.2.0'}) == {}
    result = json.loads(switch.result_path.read_text())
    assert result['status'] == 'rolled_back' and 'apply failed' in result['error']
    assert deployment.selected() == '0.1.0' and switch.calls[-1] == ('0.1.0', 'restore')

    switch = Recorder(deployment, failing={'backup'})
    assert switch.prepare({'action': 'update', 'version': '0.2.0'}) == {}
    assert json.loads(switch.result_path.read_text())['status'] == 'failed'
    assert switch.calls == [('0.1.0', 'backup')] and deployment.selected() == '0.1.0'


def test_restoring_a_snapshot_runs_its_own_version(tmp_path):
    deployment = _deployment(tmp_path)
    switch = Recorder(deployment)
    switch.settle(switch.prepare({'action': 'update', 'version': '0.2.0'}), None)
    name = deployment.snapshots()[0]['name']
    switch.calls.clear()
    assert switch.prepare({'action': 'restore', 'snapshot': name}) == {}
    assert switch.calls == [('0.1.0', 'restore')] and deployment.selected() == '0.1.0'
    assert json.loads(switch.result_path.read_text())['action'] == 'restore'


def test_docker_runs_the_newer_of_the_image_and_the_volume_version(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment_module, 'image_version', lambda: '0.2.0')
    deployment = Deployment('docker', tmp_path)
    assert deployment.selected() == '0.2.0'
    assert deployment.python('0.2.0') == deployment_module.IMAGE_ENVIRONMENT / 'bin/python'
    python = deployment.python('0.3.0')
    python.parent.mkdir(parents=True)
    python.write_text('')
    deployment.select('0.3.0')
    assert deployment.selected() == '0.3.0'
    monkeypatch.setattr(deployment_module, 'image_version', lambda: '0.3.1')
    assert deployment.selected() == '0.3.1'


def test_wait_ready_needs_the_new_version_and_reports_an_exit(tmp_path):
    answers = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(answers.pop(0) if len(answers) > 1 else answers[0]).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        (tmp_path / 'lenbot.config.json').write_text(json.dumps({'panel': {'host': '0.0.0.0', 'port': server.server_address[1]}}))
        answers[:] = [{'version': '0.2.0', 'status': 'starting', 'ready': False},
                      {'version': '0.2.0', 'status': 'running', 'ready': True}]
        assert wait_ready(tmp_path, '0.2.0', lambda: None, lambda: False, 5) is None
        answers[:] = [{'version': '0.1.0', 'status': 'running', 'ready': True}]
        assert '0.1.0' in wait_ready(tmp_path, '0.2.0', lambda: None, lambda: False, 5)
        assert wait_ready(tmp_path, '0.2.0', lambda: 3, lambda: False, 5) == '新版本退出，退出码 3'
    finally:
        server.shutdown()
        server.server_close()


def _entry(name: str, version: str, **extra) -> SourcedEntry:
    return SourcedEntry(name=name, title=name.title(), description='说明', authors=['LEN'], license='MIT',
                        version=version, interface=1, category='工具', install='git',
                        repository=f'https://example.test/{name}', ref='a' * 40, source='official', **extra)


def test_installed_plugins_with_a_newer_catalog_version_are_listed_with_compatibility():
    view = CatalogView(url=None, sources=[], entries=[
        _entry('bilibili', '1.3.0'), _entry('digest', '1.3.5', requires_lenbot='>=9'),
        _entry('same', '1.0.0'), _entry('missing', '2.0.0')])
    found = updates(view, {'bilibili': '1.2.0', 'digest': '1.3.4', 'same': '1.0.0', 'local': '0.1.0'}, host='0.2.3')
    assert [(item.name, item.installed_version, item.version, item.compatible) for item in found] == [
        ('bilibili', '1.2.0', '1.3.0', True), ('digest', '1.3.4', '1.3.5', False)]
    assert '9' in found[1].incompatible_reason
