"""The task settings tab fills a first setup from this host and turns every group's delegation off with the worker."""

import json
from pathlib import Path
import shutil
import sys

import pytest

from len_bot.next.config import load_host_config
from test_next_panel_acts_as_owner import SCENE, exercise, write_instance


def test_worker_defaults_name_this_instance(tmp_path: Path) -> None:
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client) -> None:
        defaults = (await client.get('/api/host/settings/worker/defaults')).json()
        assert defaults['image'] == 'lenbot-worker:local'  # this checkout is an editable install
        local = sys.platform == 'linux' and shutil.which('bwrap') is not None
        assert defaults['sandbox'] == ('bwrap' if local else 'docker')
        assert defaults['workspace_root'] == str(tmp_path / 'task-workspaces')
        assert {defaults['runtime_root'], defaults['delivery_root']} == {
            str(tmp_path / 'task-runtime'), str(tmp_path / 'deliveries')}
    exercise(tmp_path, check)


@pytest.mark.skipif(sys.platform != 'linux', reason='the local sandbox is Linux only')
@pytest.mark.parametrize('packaged', [True, False])
def test_worker_defaults_fill_the_task_runtime_of_the_running_package(tmp_path: Path, monkeypatch, packaged: bool) -> None:
    write_instance(tmp_path, ['onebot:70001'])
    release = tmp_path / 'lenbot-0.2.0-linux' / 'releases' / '0.2.0'
    runtime = release / 'task-runtime'
    for name in ('node/bin/node', 'node/bin/pi'):
        (runtime / name).parent.mkdir(parents=True, exist_ok=True)
        (runtime / name).touch(mode=0o755)
    (release / 'python').mkdir()
    (release / 'release.json').write_text('{"version": "0.2.0"}')
    bwrap = tmp_path / 'tools' / 'bwrap'
    bwrap.parent.mkdir()
    bwrap.touch(mode=0o755)
    monkeypatch.setenv('PATH', str(bwrap.parent))
    monkeypatch.setattr(sys, 'prefix', str(release / 'python' if packaged else tmp_path / 'venv'))

    async def check(client) -> None:
        defaults = (await client.get('/api/host/settings/worker/defaults')).json()
        assert defaults['sandbox'] == 'bwrap' and defaults['bwrap_binary'] == str(bwrap)
        assert defaults.get('task_runtime') == (str(runtime) if packaged else None)
    exercise(tmp_path, check)


def test_turning_tasks_off_stops_delegation_in_every_group(tmp_path: Path) -> None:
    write_instance(tmp_path, ['onebot:70001'])
    path = tmp_path / 'lenbot.config.json'

    async def check(client) -> None:
        # Saved while this host runs without tasks; the panel edits the root file.
        source = json.loads(path.read_text())
        source['worker'] = {'docker_binary': str(tmp_path / 'docker'), 'docker_host': 'unix:///var/run/docker.sock',
                            'image': 'lenbot-worker:local', 'workspace_root': 'tasks/workspaces',
                            'runtime_root': 'tasks/runtime', 'delivery_root': 'tasks/deliveries',
                            'uid': 1000, 'gid': 1000, 'model_reasoning': True,
                            'compaction_reserve_tokens': 1000, 'compaction_keep_recent_tokens': 2000}
        source['scenes'][SCENE]['tasks'] = {'enabled': True, 'max_running': 2}
        path.write_text(json.dumps(source, ensure_ascii=False))
        response = await client.put('/api/host/settings/worker', json={'worker': None})
        assert response.status_code == 200, response.text
    exercise(tmp_path, check)

    saved = load_host_config(tmp_path)
    assert saved.worker is None
    assert saved.scenes[SCENE].tasks.enabled is False and saved.scenes[SCENE].tasks.max_running == 2


def test_local_sandbox_check_reports_a_missing_bwrap(tmp_path: Path) -> None:
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client) -> None:
        missing = tmp_path / 'no-bwrap'
        response = await client.post('/api/host/settings/worker/check', json={
            'bwrap_binary': str(missing), 'task_runtime': str(tmp_path / 'task-runtime')})
        assert response.status_code == 200, response.text
        assert response.json()['steps'] == [{'step': 'bwrap', 'ok': False, 'detail': f'{missing} 不存在或不可执行'}]
        relative = await client.post('/api/host/settings/worker/check', json={
            'bwrap_binary': 'bwrap', 'task_runtime': str(tmp_path)})
        assert relative.status_code == 422
    exercise(tmp_path, check)



def test_task_space_reports_free_disk_without_a_storage_pool(tmp_path: Path) -> None:
    import asyncio

    import httpx

    from len_bot.next.configuration.tasks import WorkerSettings
    from len_bot.next.models.client import ChatModel
    from len_bot.next.panel.app import create_app
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.runtime.network import NetworkRuntime
    from len_bot.next.storage.store import Store

    write_instance(tmp_path, ['onebot:70001'])
    config = load_host_config(tmp_path)
    worker = WorkerSettings.model_validate({
        'docker_binary': tmp_path / 'docker', 'docker_host': 'unix:///var/run/docker.sock',
        'image': 'lenbot-worker:local', 'workspace_root': tmp_path / 'tasks/workspaces',
        'runtime_root': tmp_path / 'tasks/runtime', 'delivery_root': tmp_path / 'tasks/deliveries',
        'uid': 1000, 'gid': 1000, 'model_reasoning': True})

    async def run() -> None:
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona))],
                                         store, mind)
                # 只读接口在请求时读取 worker 配置，不需要启动任务服务。
                runtime.config = config.model_copy(update={'worker': worker})
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    await client.post('/api/auth/login', json={'username': 'host-operator', 'password': 'synthetic-password'})
                    response = await client.get('/api/host/task-storage/pool')
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body['configured'], body['usage']) == (False, None)
        assert body['disk']['free_bytes'] > 0
        assert (body['disk']['reserve_bytes'], body['disk']['stop_bytes']) == (5 * 1024 ** 3, 2 * 1024 ** 3)
    asyncio.run(run())


def test_docker_host_accepts_a_local_socket_or_named_pipe() -> None:
    import pytest
    from pydantic import ValidationError

    from len_bot.next.configuration.tasks import WorkerSettings

    def worker(host: str) -> WorkerSettings:
        root = Path('/srv/lenbot').resolve()
        return WorkerSettings.model_validate({
            'docker_binary': root / 'docker', 'docker_host': host, 'image': 'lenbot-worker:local',
            'workspace_root': root / 'workspaces', 'runtime_root': root / 'runtime',
            'delivery_root': root / 'deliveries', 'uid': 10000, 'gid': 10000, 'model_reasoning': True})

    assert worker('npipe:////./pipe/docker_engine').docker_host == 'npipe:////./pipe/docker_engine'
    assert worker('unix:///var/run/docker.sock').docker_host == 'unix:///var/run/docker.sock'
    for host in ('tcp://127.0.0.1:2375', 'npipe:////remote/pipe/docker_engine', 'unix://relative.sock'):
        with pytest.raises(ValidationError):
            worker(host)


def test_readiness_names_what_delegation_still_needs(tmp_path: Path) -> None:
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client) -> None:
        response = await client.get('/api/host/settings/worker/readiness')
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body['worker'], body['running'], body['sandbox'], body['delivery']) == (False, False, None, 'simulated')
        assert body['scenes'] == [{'scene': SCENE, 'enabled': False, 'delegate_roles': ['owner', 'admin', 'whitelist'],
                                   'persona': 'synthetic-owner', 'missing_tools': ['delegate', 'task', 'send_file']}]
    exercise(tmp_path, check)


def test_a_release_installation_defaults_to_the_same_version_official_worker(tmp_path: Path) -> None:
    from importlib.metadata import version

    write_instance(tmp_path, ['onebot:70001'])
    (tmp_path / '.runtime').mkdir()
    (tmp_path / '.runtime' / 'update-control.json').write_text('{}', encoding='utf-8')

    async def check(client) -> None:
        defaults = (await client.get('/api/host/settings/worker/defaults')).json()
        assert defaults['image'] == f"ghcr.io/lendevs/lenbot-worker:{version('len-bot')}"
    exercise(tmp_path, check)


def test_docker_check_reports_a_missing_cli_and_rejects_a_remote_daemon(tmp_path: Path) -> None:
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client) -> None:
        missing = tmp_path / 'no-docker'
        response = await client.post('/api/host/settings/worker/docker-check', json={
            'docker_binary': str(missing), 'docker_host': 'unix:///var/run/docker.sock', 'image': 'lenbot-worker:local'})
        assert response.status_code == 200, response.text
        [step] = response.json()['steps']
        assert (step['step'], step['ok']) == ('docker', False) and str(missing) in step['detail']
        remote = await client.post('/api/host/settings/worker/docker-check', json={
            'docker_binary': str(missing), 'docker_host': 'tcp://192.0.2.1:2375', 'image': 'lenbot-worker:local'})
        assert remote.status_code == 422
    exercise(tmp_path, check)
