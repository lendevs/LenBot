"""Every update failure leaves the user one concrete next action; a failure after the snapshot is rolled back."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/updater'))
import controller as updater
from common import write_json
from native import Native

SHA = 'a' * 64
MANIFEST = {'manifest_version': 1, 'updater_protocol': 1, 'version': '0.2.0', 'tag': 'v0.2.0',
            'bundles': {'linux': 'lenbot-0.2.0-linux.tar.gz'},
            'files': {'lenbot-0.2.0-linux.tar.gz': {'sha256': SHA, 'bytes': 1}}}
RELEASES = [{'tag_name': 'v0.2.0', 'draft': False, 'prerelease': False, 'body': '说明', 'assets': [
    {'name': 'release-manifest.json', 'browser_download_url': 'manifest'},
    {'name': 'lenbot-0.2.0-linux.tar.gz', 'browser_download_url': 'bundle'}]}]


class Backend:
    """Records each step; ``fail`` names the steps that raise.

    Starting and readiness of the previous program are recorded as ``start_previous`` and
    ``ready_previous``, so a test can break the new version and its rollback separately.
    """

    def __init__(self, fail: str | tuple[str, ...] | None = None, blocked: list[str] | None = None,
                 platform: dict | None = None):
        self.fail, self.blocked = fail, blocked or []
        self.current = {'version': '0.1.0'}
        self.running, self.calls, self.discarded = True, [], []
        # Per version: the QQ connection its readiness answer reports (None: no platform, 'absent': does not say),
        # or an int n: not connected for the first n reads, then connected.
        self.platform, self.reads = platform or {}, 0

    def host_status(self):
        if not self.running:
            return None
        value = self.platform.get(self.current['version'])
        if value == 'absent':
            return {'version': self.current['version'], 'ready': True}
        if isinstance(value, int) and not isinstance(value, bool):
            self.reads += 1
            value = self.reads > value
        return {'version': self.current['version'], 'ready': True,
                'platform': None if value is None else {'connected': value, 'connected_since': None}}

    def step(self, name: str) -> None:
        self.calls.append(name)
        if name in ((self.fail,) if isinstance(self.fail, str) else self.fail or ()):
            raise RuntimeError(f'synthetic {name} failure')

    def previous(self, name: str, version: str) -> str:
        return name + ('_previous' if version == '0.1.0' else '')

    def metadata(self):
        return self.current

    def prepare(self, manifest, archive, work):
        self.step('prepare')
        return {'version': manifest['version']}

    def inspect(self, target):
        self.step('inspect')
        return {'blocked_plugins': self.blocked, 'disabled_plugins': [], 'work_enabled': False}

    def discard(self, target):
        self.discarded.append(target['version'])

    def stop(self):
        self.step('stop')
        self.running = False

    def backup(self, snapshot):
        self.step('backup')

    def migrate(self, target):
        self.step('migrate')

    def select(self, target):
        self.step('select')
        self.current = target

    def start(self):
        self.step(self.previous('start', self.current['version']))
        self.running = True

    def ready(self, target):
        self.step(self.previous('ready', target['version']))

    def restore(self, old, snapshot):
        self.step('restore')
        self.current = old


@pytest.fixture
def make(tmp_path, monkeypatch):
    write_json(tmp_path / 'deployment.json', {'mode': 'native', 'platform': 'linux', 'uv': 'uv', 'release_api': 'releases'})
    write_json(tmp_path / 'current.json', {'version': '0.1.0'})
    sources = {'releases': RELEASES, 'manifest': MANIFEST}
    monkeypatch.setattr(updater, 'fetch_json', lambda url: sources[url])
    monkeypatch.setattr(updater, 'download', lambda url, path, expected: path.write_bytes(b'x'))
    made = []

    def build(backend: Backend) -> updater.Controller:
        controller = updater.Controller(tmp_path)
        controller.backend = backend
        made.append(controller)
        return controller
    yield build
    for controller in made:
        controller.log.close()


def run(controller: updater.Controller, action: str, payload: dict | None = None) -> dict:
    controller.submit(action, payload or {})
    deadline = time.monotonic() + 5
    while controller.operation.locked():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    return controller.status()


def test_full_update_then_restore_then_start(make):
    backend = Backend()
    controller = make(backend)
    assert controller.status()['actions'] == ['prepare']
    assert run(controller, 'prepare', {'tag': 'v0.2.0'})['actions'] == ['prepare', 'apply']
    assert not list((controller.root / 'updates').glob('candidate-*'))
    done = run(controller, 'apply')
    assert done['status'] == 'complete' and done['current_version'] == '0.2.0' and not done['stopped']
    assert done['actions'] == ['prepare', 'restore']
    restored = run(controller, 'restore')
    assert restored['current_version'] == '0.1.0' and restored['actions'] == ['start']
    assert run(controller, 'start')['status'] == 'complete' and backend.running


def test_download_failure_keeps_host_running_and_removes_candidate(make, monkeypatch):
    def broken(url, path, expected):
        path.write_bytes(b'partial')
        raise ValueError('Download checksum or length differs')
    monkeypatch.setattr(updater, 'download', broken)
    backend = Backend()
    controller = make(backend)
    state = run(controller, 'prepare', {'tag': 'v0.2.0'})
    assert state['status'] == 'failed' and 'checksum' in state['error']
    assert state['actions'] == ['prepare'] and backend.running and 'stop' not in backend.calls
    assert not list((controller.root / 'updates').glob('candidate-*'))


@pytest.mark.parametrize('fail', ['prepare', 'inspect'])
def test_environment_or_compatibility_failure_discards_only_what_was_prepared(make, fail):
    backend = Backend(fail=fail)
    controller = make(backend)
    state = run(controller, 'prepare', {'tag': 'v0.2.0'})
    assert state['actions'] == ['prepare'] and backend.running
    assert backend.discarded == ([] if fail == 'prepare' else ['0.2.0'])


def test_blocked_plugin_is_listed_and_preparing_again_replaces_the_candidate(make):
    backend = Backend(blocked=['fixture: requires host >=0.1,<0.2'])
    controller = make(backend)
    state = run(controller, 'prepare', {'tag': 'v0.2.0'})
    assert 'fixture' in state['error'] and state['actions'] == ['prepare']
    backend.blocked = []
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    backend.discarded.clear()
    assert run(controller, 'prepare', {'tag': 'v0.2.0'})['status'] == 'prepared'
    assert backend.discarded == ['0.2.0']


@pytest.mark.parametrize('fail', ['stop'])
def test_failure_before_snapshot_offers_starting_the_unchanged_program(make, fail):
    backend = Backend(fail=fail)
    controller = make(backend)
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'failed' and state['stopped'] and not state['snapshot_complete']
    assert state['actions'] == ['start'] and state['current_version'] == '0.1.0'
    with pytest.raises(ValueError, match='当前不能恢复快照；可执行：启动程序'):
        controller.submit('restore', {})
    backend.fail = None
    assert run(controller, 'start')['status'] == 'complete' and backend.running


def test_backup_failure_restarts_the_previous_program_and_removes_the_partial_snapshot(make):
    backend = Backend(fail='backup')
    def backup(snapshot):
        (snapshot / '0').mkdir(parents=True)
        (snapshot / '0/lenbot.db').write_bytes(b'partial')
        backend.step('backup')
    backend.backup = backup
    controller = make(backend)
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'rolled_back' and not state['stopped'] and not state['snapshot_complete']
    assert not Path(state['snapshot']).exists() and controller.snapshots() == []
    assert state['current_version'] == '0.1.0' and backend.running and state['actions'] == ['prepare']
    assert state['error'] == '快照失败，已重新启动 0.1.0：RuntimeError: synthetic backup failure'
    assert backend.calls[backend.calls.index('backup'):] == ['backup', 'start_previous', 'ready_previous']


@pytest.mark.parametrize('fail', ['start_previous', 'ready_previous'])
def test_backup_failure_with_failed_restart_keeps_both_errors_and_manual_start(make, fail):
    backend = Backend(fail=('backup', fail))
    controller = make(backend)
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'failed' and state['actions'] == ['start'] and not state['snapshot_complete']
    assert 'synthetic backup failure' in state['error'] and f'synthetic {fail} failure' in state['error']
    backend.fail = None
    assert run(controller, 'start')['status'] == 'complete' and backend.running


@pytest.mark.parametrize('fail', ['migrate', 'select', 'start', 'ready'])
def test_failure_after_snapshot_rolls_back_and_starts_the_previous_program(make, fail):
    backend = Backend(fail=fail)
    controller = make(backend)
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'rolled_back' and state['current_version'] == '0.1.0' and backend.running
    assert not state['stopped'] and not state['snapshot_complete'] and state['actions'] == ['prepare']
    stage = 'start' if fail == 'ready' else fail  # readiness is waited for in the start stage
    assert state['failed_stage'] == stage and state['rolled_back_from'] == '0.2.0'
    assert state['error'] == f'更新到 0.2.0 失败，已自动恢复到 0.1.0：RuntimeError: synthetic {fail} failure'
    assert backend.calls[backend.calls.index('restore'):] == ['restore', 'start_previous', 'ready_previous']
    records = [json.loads(line) for line in (controller.root / 'updates/updater.jsonl').read_text().splitlines()]
    assert [entry['stage'] for entry in records if entry['event'] == 'stage'][-3:] == [
        'rollback', 'rollback_start', 'rolled_back']
    assert any(entry['event'] == 'update_failed' and entry['stage'] == stage for entry in records)
    # The failed candidate is discarded when an update is prepared again.
    backend.fail = None
    assert run(controller, 'prepare', {'tag': 'v0.2.0'})['status'] == 'prepared' and backend.discarded == ['0.2.0']


def test_rollback_that_cannot_restore_keeps_the_manual_restore(make):
    backend = Backend(fail=('ready', 'restore'))
    controller = make(backend)
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'failed' and state['stage'] == 'rollback' and state['actions'] == ['restore']
    assert state['snapshot_complete'] and state['stopped']
    assert '自动恢复快照也失败' in state['error'] and 'synthetic ready failure' in state['error']
    with pytest.raises(ValueError, match='当前不能启动程序'):
        controller.submit('start', {})
    backend.fail = None
    restored = run(controller, 'restore')
    assert restored['current_version'] == '0.1.0' and restored['actions'] == ['start']
    assert run(controller, 'start')['status'] == 'complete' and backend.running


def test_rollback_whose_previous_program_does_not_start_offers_start(make):
    backend = Backend(fail=('start', 'ready_previous'))
    controller = make(backend)
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'failed' and state['stage'] == 'rollback_start' and state['actions'] == ['start']
    assert state['current_version'] == '0.1.0' and '已恢复快照，但旧版本未能启动' in state['error']
    backend.fail = None
    assert run(controller, 'start')['status'] == 'complete'


def test_new_version_must_reconnect_to_qq_when_the_old_one_was_connected(make):
    backend = Backend(platform={'0.1.0': True, '0.2.0': 3})
    controller = make(backend)
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'complete' and state['platform_before'] is True and state['warning'] is None
    assert backend.reads == 4
    stages = [json.loads(line).get('stage') for line in (controller.root / 'updates/updater.jsonl').read_text().splitlines()]
    assert stages[-2:] == ['connect', 'complete']
    assert run(controller, 'restore')['status'] == 'restored'  # the snapshot stays available after success


def test_new_version_that_never_reconnects_to_qq_is_rolled_back(make):
    backend = Backend(platform={'0.1.0': True, '0.2.0': False})
    controller = make(backend)
    controller.connect_seconds = 0.3
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'rolled_back' and state['failed_stage'] == 'connect'
    assert state['current_version'] == '0.1.0' and backend.running
    assert state['error'] == ('更新到 0.2.0 失败，已自动恢复到 0.1.0：'
                              'TimeoutError: 新版本 0.3 秒内未连接 QQ（更新前已连接）')


@pytest.mark.parametrize(('before', 'warning'), [(False, '更新前后均未连接 QQ；'),
                                                 (None, '新版本未连接 QQ（更新前的程序未报告连接状态）'),
                                                 ('absent', '新版本未连接 QQ（更新前的程序未报告连接状态）')])
def test_qq_offline_before_the_update_only_warns(make, before, warning):
    backend = Backend(platform={'0.1.0': before, '0.2.0': False})
    controller = make(backend)
    controller.connect_seconds = 0.3
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    state = run(controller, 'apply')
    assert state['status'] == 'complete' and state['current_version'] == '0.2.0'
    assert state['platform_before'] is (False if before is False else None)
    assert state['warning'].startswith(warning) and state['warning'].endswith('请检查 QQ 客户端和连接设置。')
    assert 'connect' not in [json.loads(line).get('stage') for line in
                             (controller.root / 'updates/updater.jsonl').read_text().splitlines()]


def test_native_reads_the_host_readiness_over_http(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Host(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps({'version': '0.2.0', 'ready': True,
                               'platform': {'connected': True, 'connected_since': 1.0}}).encode()
            self.send_response(200 if self.path == '/api/host/ready' else 404)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Host)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    (tmp_path / 'instance').mkdir()
    write_json(tmp_path / 'deployment.json', {'mode': 'native', 'platform': 'linux', 'uv': 'uv'})
    write_json(tmp_path / 'instance/lenbot.config.json', {'panel': {'host': '0.0.0.0', 'port': server.server_port}})
    with (tmp_path / 'log').open('w') as log:
        native = Native(tmp_path, log)
        try:
            assert native.host_status()['platform'] == {'connected': True, 'connected_since': 1.0}
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        assert native.host_status() is None


@pytest.mark.parametrize(('stage', 'stopped', 'snapshot', 'actions'), [
    ('download', False, False, ['prepare']),
    ('backup', True, False, ['start']),
    ('migrate', True, True, ['restore']),
    ('rollback', True, True, ['restore']),
    ('rollback_start', True, False, ['start']),
])
def test_controller_restart_mid_operation_keeps_a_way_out(make, stage, stopped, snapshot, actions):
    controller = make(Backend())
    write_json(controller.state_file, {'status': 'applying', 'stage': stage, 'stopped': stopped,
                                       'snapshot_complete': snapshot, 'old': {'version': '0.1.0'}, 'snapshot': 'x'})
    restarted = make(Backend())
    assert restarted.state['status'] == 'failed' and restarted.status()['actions'] == actions


def test_unknown_and_out_of_order_actions_are_refused(make):
    controller = make(Backend())
    with pytest.raises(ValueError, match='未知'):
        controller.submit('rollback', {})
    with pytest.raises(ValueError, match='当前不能停机升级；可执行：准备更新'):
        controller.submit('apply', {})


@pytest.mark.skipif(sys.platform == 'win32', reason='process group signal')
def test_native_stop_kills_the_process_group_after_the_timeout(tmp_path):
    write_json(tmp_path / 'deployment.json', {'mode': 'native', 'platform': 'linux', 'uv': 'uv'})
    with (tmp_path / 'log').open('w') as log:
        native = Native(tmp_path, log)
        native.stop_seconds = 0.5
        code = ('import signal, subprocess, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                'child = subprocess.Popen([sys.executable, "-c", "import signal, time; '
                'signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"]); print(child.pid, flush=True); time.sleep(60)')
        native.child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True,
                                        start_new_session=True)
        grandchild = int(native.child.stdout.readline())
        native.stop()
    assert native.child.returncode == -signal.SIGKILL
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail('the host child process outlived the forced stop')
    assert '强制结束' in (tmp_path / 'log').read_text()


@pytest.mark.skipif(sys.platform == 'win32', reason='process group signal')
def test_restarted_controller_stops_the_host_left_by_a_killed_one(tmp_path):
    instance = tmp_path / 'instance'
    instance.mkdir()
    write_json(tmp_path / 'deployment.json', {'mode': 'native', 'platform': 'linux', 'uv': 'uv'})
    code = ('import fcntl, sys, time; f = open(".lenbot-instance.lock", "a+b"); fcntl.flock(f, fcntl.LOCK_EX); '
            'print("locked", flush=True); time.sleep(60)')
    with (tmp_path / 'log').open('w') as log:
        first = Native(tmp_path, log)
        orphan = subprocess.Popen([sys.executable, '-c', code], cwd=instance, stdout=subprocess.PIPE, text=True,
                                  start_new_session=True)
        assert orphan.stdout.readline().strip() == 'locked'
        first.pid_file.parent.mkdir()
        first.pid_file.write_text(str(orphan.pid))
        restarted = Native(tmp_path, log)
        restarted.stop()
    assert orphan.wait(5) == -signal.SIGTERM
    assert not restarted.pid_file.exists()
    assert '仍在运行' in (tmp_path / 'log').read_text()


def test_new_updater_protocol_gives_commands_instead_of_preparing(make, monkeypatch):
    sources = {'releases': RELEASES, 'manifest': {**MANIFEST, 'updater_protocol': 2}}
    monkeypatch.setattr(updater, 'fetch_json', lambda url: sources[url])
    backend = Backend()
    controller = make(backend)
    state = run(controller, 'prepare', {'tag': 'v0.2.0'})
    assert '运行新目录中的 run' in state['error'] and 'prepare' not in backend.calls and backend.running


def test_docker_updater_switch_changes_only_the_updater_image(tmp_path):
    import init
    write_json(tmp_path / 'deployment.json', {'mode': 'docker', 'project': 'lenbot'})
    write_json(tmp_path / 'current.json', {'version': '0.2.0', 'host_image': 'ghcr.io/lendevs/lenbot@sha256:' + SHA})
    (tmp_path / 'host.updater.compose.yaml').write_text(json.dumps(
        {'services': {'lenbot-updater': {'image': 'ghcr.io/lendevs/lenbot-updater:0.2.0', 'ports': ['x']}}}))
    init.switch_updater(tmp_path, '0.3.0')
    service = json.loads((tmp_path / 'host.updater.compose.yaml').read_text())['services']['lenbot-updater']
    assert service == {'image': 'ghcr.io/lendevs/lenbot-updater:0.3.0', 'ports': ['x']}
    assert json.loads((tmp_path / 'current.json').read_text())['host_image'].endswith(SHA)


@pytest.mark.parametrize(('reference', 'name'), [
    ('ghcr.io/lendevs/lenbot:0.2.0', 'ghcr.io/lendevs/lenbot'),
    ('ghcr.io/lendevs/lenbot@sha256:' + SHA, 'ghcr.io/lendevs/lenbot'),
    ('127.0.0.1:5000/lenbot:0.0.0', '127.0.0.1:5000/lenbot'),
    ('lenbot-current:local', 'lenbot-current'),
])
def test_image_repository(reference, name):
    from common import repository
    assert repository(reference) == name


@pytest.mark.parametrize(('image', 'follows'), [
    ('ghcr.io/lendevs/lenbot-worker:0.1.0', 'ghcr.io/lendevs/lenbot-worker:0.2.0'),
    ('lenbot-worker:local', None),
])
def test_native_task_image_follows_only_official_release_images(tmp_path, image, follows):
    (tmp_path / 'instance').mkdir()
    write_json(tmp_path / 'deployment.json', {'mode': 'native', 'platform': 'linux', 'uv': 'uv'})
    write_json(tmp_path / 'instance/lenbot.config.json', {'worker': {'image': image, 'docker_binary': '/usr/bin/docker'}})
    with (tmp_path / 'log').open('w') as log:
        native = Native(tmp_path, log)
        commands = []
        native.maintenance = lambda action, **kwargs: '{"blocked_plugins": [], "work_enabled": true}'
        native.command = lambda arguments, **kwargs: commands.append(arguments)
        check = native.inspect({'version': '0.2.0'})
        native.migrate({'version': '0.2.0'})
    assert check['worker_image'] == (follows or image) and check['worker_follows_release'] == (follows is not None)
    assert commands == ([['/usr/bin/docker', 'pull', follows]] if follows else [])
    assert json.loads((tmp_path / 'instance/lenbot.config.json').read_text())['worker']['image'] == (follows or image)


def test_shutdown_endpoint_stops_the_controller_server(make, tmp_path):
    import threading
    import urllib.request
    (tmp_path / 'instance').mkdir()
    controller = make(Backend())
    controller.backend.instance = tmp_path / 'instance'
    http = updater.server(controller)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    reference = json.loads((tmp_path / 'instance/.runtime/update-control.json').read_text())
    request = urllib.request.Request(reference['endpoint'] + '/api/shutdown', data=b'{}', method='POST',
                                     headers={'Authorization': 'Bearer ' + reference['token']})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 202
    thread.join(5)
    http.server_close()
    assert not thread.is_alive()


def test_files_the_root_updater_writes_keep_the_deployment_owner(tmp_path, monkeypatch):
    import common
    import init
    owners = {}
    monkeypatch.setattr(common.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(common.os, 'chown', lambda path, uid, gid: owners.__setitem__(Path(path).name, (uid, gid)), raising=False)
    write_json(tmp_path / 'deployment.json', {'mode': 'docker', 'project': 'lenbot'})
    write_json(tmp_path / 'current.json', {'version': '0.2.0', 'host_image': 'ghcr.io/lendevs/lenbot:0.2.0'})
    (tmp_path / 'host.updater.compose.yaml').write_text(json.dumps({'services': {'lenbot-updater': {'image': 'x'}}}))
    init.switch_updater(tmp_path, '0.3.0')
    expected = (tmp_path.stat().st_uid, tmp_path.stat().st_gid)
    assert owners == {name: expected for name in ('deployment.json', 'current.json', 'host.updater.compose.yaml')}


def test_next_action_waits_for_the_finishing_operation_to_release(make):
    import threading
    controller = make(Backend())
    controller.operation.acquire()
    controller.state.update(status='complete', snapshot_complete=True, old={'version': '0.1.0'}, snapshot='x')
    threading.Timer(0.3, controller.operation.release).start()
    assert controller.submit('restore', {}) == {'accepted': True}
    with controller.operation:
        assert controller.state['status'] == 'restored'


def _snapshot(backups: Path, name: str, data: bytes, *, complete: bool = True) -> Path:
    path = backups / name
    (path / '0').mkdir(parents=True)
    (path / '0/lenbot.db').write_bytes(data)
    if complete:
        (path / 'snapshot.json').write_bytes(b'[]\n')
    return path


def test_snapshots_are_listed_newest_first_and_the_one_a_failed_update_needs_stays(make):
    from datetime import datetime, timezone
    controller = make(Backend())
    backups = controller.root / 'backups'
    older = _snapshot(backups, '20261001-080000-0000000a', b'x' * 10)
    newer = _snapshot(backups, '20261020-093000-0000000b', b'y' * 100, complete=False)
    (backups / 'notes.txt').write_text('其他文件', encoding='utf-8')
    (backups / 'manual-copy').mkdir()
    controller.state.update(status='failed', stage='migrate', snapshot=str(newer), snapshot_complete=True)
    assert controller.snapshots() == [
        {'name': newer.name, 'bytes': 100, 'complete': False, 'restore': True,
         'created': datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc).timestamp()},
        {'name': older.name, 'bytes': 13, 'complete': True, 'restore': False,
         'created': datetime(2026, 10, 1, 8, tzinfo=timezone.utc).timestamp()}]
    with pytest.raises(ValueError, match='恢复需要使用此快照'):
        controller.delete_snapshot(newer.name)
    for name in ('../updates', 'manual-copy', '20261021-000000-0000000c'):
        with pytest.raises(LookupError):
            controller.delete_snapshot(name)
    assert [item['name'] for item in controller.delete_snapshot(older.name)] == [newer.name]
    assert not older.exists() and (backups / 'notes.txt').exists() and (backups / 'manual-copy').exists()
    assert controller.status()['actions'] == ['restore']
    controller.state['status'] = 'restoring'
    with pytest.raises(ValueError, match='正在执行'):
        controller.delete_snapshot(newer.name)


def test_deleting_the_snapshot_of_a_completed_update_removes_its_restore(make):
    controller = make(Backend())
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    done = run(controller, 'apply')
    assert done['actions'] == ['prepare', 'restore']
    snapshot = Path(done['snapshot'])
    _snapshot(snapshot.parent, snapshot.name, b'z')
    assert controller.snapshots()[0]['restore']
    assert controller.delete_snapshot(snapshot.name) == []
    assert controller.status()['actions'] == ['prepare'] and not snapshot.exists()
    assert json.loads(controller.state_file.read_text(encoding='utf-8'))['snapshot_complete'] is False


def test_snapshot_endpoints_list_and_delete(make, tmp_path):
    import threading
    import urllib.error
    import urllib.request
    (tmp_path / 'instance').mkdir()
    controller = make(Backend())
    controller.backend.instance = tmp_path / 'instance'
    kept = _snapshot(tmp_path / 'backups', '20261020-093000-0000000b', b'y')
    _snapshot(tmp_path / 'backups', '20261001-080000-0000000a', b'x')
    controller.state.update(status='failed', snapshot=str(kept), snapshot_complete=True)
    http = updater.server(controller)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    reference = json.loads((tmp_path / 'instance/.runtime/update-control.json').read_text())

    def call(method: str, path: str, token: str = reference['token']) -> tuple[int, object]:
        request = urllib.request.Request(reference['endpoint'] + path, method=method,
                                         headers={'Authorization': 'Bearer ' + token})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
    try:
        assert call('GET', '/api/snapshots', 'wrong')[0] == 401
        assert call('GET', '/api/snapshots', 'é')[0] == 401
        code, listed = call('GET', '/api/snapshots')
        assert code == 200 and [item['name'] for item in listed] == [kept.name, '20261001-080000-0000000a']
        code, refused = call('DELETE', '/api/snapshots/' + kept.name)
        assert code == 409 and '恢复需要使用此快照' in refused['detail']
        assert call('DELETE', '/api/snapshots/20261001-080000-00000000')[0] == 404
        assert call('DELETE', '/api/status')[0] == 404
        code, left = call('DELETE', '/api/snapshots/20261001-080000-0000000a')
        assert code == 200 and [item['name'] for item in left] == [kept.name]
    finally:
        http.shutdown()
        thread.join(5)
        http.server_close()


def test_concurrent_deletes_of_one_snapshot_remove_it_once(make):
    import threading
    controller = make(Backend())
    snapshot = _snapshot(controller.root / 'backups', '20261001-080000-0000000a', b'x')
    results = []

    def delete():
        try:
            results.append(controller.delete_snapshot(snapshot.name))
        except LookupError as error:
            results.append(error)
    controller.operation.acquire()
    threads = [threading.Thread(target=delete) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.1)
    controller.operation.release()
    for thread in threads:
        thread.join(15)
    assert sorted(map(type, results), key=str) == [LookupError, list] and not snapshot.exists()


def test_snapshot_list_skips_other_names_and_files_removed_meanwhile(make, monkeypatch):
    controller = make(Backend())
    backups = controller.root / 'backups'
    kept = _snapshot(backups, '20261001-080000-0000000a', b'x' * 10)
    _snapshot(backups, '20261399-999999-0000000b', b'y')
    _snapshot(backups, '２０２６１００１-０８００００-0000000c', b'z')
    walk = updater.os.walk
    monkeypatch.setattr(updater.os, 'walk', lambda path: [*walk(path), (str(path), [], ['removed-meanwhile'])])
    assert [(item['name'], item['bytes']) for item in controller.snapshots()] == [(kept.name, 13)]


def test_a_removal_that_stops_halfway_keeps_the_restore_off_and_can_be_repeated(make, monkeypatch):
    controller = make(Backend())
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    snapshot = Path(run(controller, 'apply')['snapshot'])
    _snapshot(snapshot.parent, snapshot.name, b'z')
    remove_tree = updater.remove_tree

    def halfway(path):
        (path / 'snapshot.json').unlink()
        raise PermissionError('synthetic removal failure')
    monkeypatch.setattr(updater, 'remove_tree', halfway)
    with pytest.raises(PermissionError):
        controller.delete_snapshot(snapshot.name)
    assert controller.status()['actions'] == ['prepare'] and not snapshot.exists()
    listed, = controller.snapshots()
    assert listed['name'] == snapshot.name and not listed['complete'] and not listed['restore']
    monkeypatch.setattr(updater, 'remove_tree', remove_tree)
    assert controller.delete_snapshot(snapshot.name) == [] and not list(snapshot.parent.iterdir())


def test_a_snapshot_that_cannot_be_moved_keeps_its_restore(make, monkeypatch):
    controller = make(Backend())
    run(controller, 'prepare', {'tag': 'v0.2.0'})
    snapshot = Path(run(controller, 'apply')['snapshot'])
    _snapshot(snapshot.parent, snapshot.name, b'z')

    def refused(self, target):
        raise PermissionError('synthetic rename failure')
    monkeypatch.setattr(updater.Path, 'rename', refused)
    with pytest.raises(PermissionError):
        controller.delete_snapshot(snapshot.name)
    assert controller.status()['actions'] == ['prepare', 'restore'] and snapshot.is_dir()
    assert json.loads(controller.state_file.read_text(encoding='utf-8'))['snapshot_complete'] is True


def test_read_only_files_are_removed_with_their_snapshot(make, monkeypatch):
    import stat
    controller = make(Backend())
    snapshot = _snapshot(controller.root / 'backups', '20261001-080000-0000000a', b'x')
    (snapshot / '0/lenbot.db').chmod(stat.S_IREAD)
    unlink = os.unlink

    def windows_unlink(path, *, dir_fd=None):
        # Windows refuses to delete a file with the read-only attribute.
        if not os.stat(path, dir_fd=dir_fd).st_mode & stat.S_IWRITE:
            raise PermissionError(13, 'Access is denied', path)
        unlink(path, dir_fd=dir_fd)
    monkeypatch.setattr(os, 'unlink', windows_unlink)
    assert controller.delete_snapshot(snapshot.name) == [] and not snapshot.exists()


def test_requests_with_a_bad_length_or_body_are_answered_4xx(make, tmp_path):
    import socket
    import threading
    (tmp_path / 'instance').mkdir()
    controller = make(Backend())
    controller.backend.instance = tmp_path / 'instance'
    http = updater.server(controller)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    reference = json.loads((tmp_path / 'instance/.runtime/update-control.json').read_text())

    def post(length: str | None, body: bytes = b'') -> int:
        lines = ['POST /api/prepare HTTP/1.1', 'Host: 127.0.0.1', 'Authorization: Bearer ' + reference['token'],
                 'Connection: close']
        if length is not None:
            lines.append('Content-Length: ' + length)
        with socket.create_connection(('127.0.0.1', http.server_port), timeout=5) as connection:
            connection.sendall('\r\n'.join(lines).encode() + b'\r\n\r\n' + body)
            reply = b''
            while block := connection.recv(4096):
                reply += block
        return int(reply.split(b' ', 2)[1])
    try:
        assert post('-1') == 400
        assert post('abc') == 400
        assert post('1.5') == 400
        assert post('99999999999999999999') == 400
        assert post('5000', b'{}') == 400
        assert post('4', b'nope') == 400
        assert post('2', b'[]') == 400
        assert post('4', b'null') == 400
        assert post('2', b'42') == 400
        assert controller.status()['status'] == 'idle'
        assert post('2', b'{}') == 409
    finally:
        http.shutdown()
        thread.join(5)
        http.server_close()
