"""The task settings tab fills a first setup from this host and turns every group's delegation off with the worker."""

import json
from pathlib import Path

from len_bot.next.config import load_host_config
from test_next_panel_acts_as_owner import SCENE, exercise, write_instance


def test_worker_defaults_name_this_instance(tmp_path: Path) -> None:
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client) -> None:
        defaults = (await client.get('/api/host/settings/worker/defaults')).json()
        assert defaults['image'] == 'lenbot-worker:local'
        assert defaults['workspace_root'] == str(tmp_path / 'task-workspaces')
        assert {defaults['runtime_root'], defaults['delivery_root']} == {
            str(tmp_path / 'task-runtime'), str(tmp_path / 'deliveries')}
    exercise(tmp_path, check)


def test_turning_tasks_off_stops_delegation_in_every_group(tmp_path: Path) -> None:
    write_instance(tmp_path, ['onebot:70001'])
    path = tmp_path / 'lenbot.config.json'

    async def check(client) -> None:
        # Saved while this host runs without tasks; the panel edits the root file.
        source = json.loads(path.read_text())
        source['worker'] = {'docker_binary': '/usr/bin/docker', 'docker_host': 'unix:///var/run/docker.sock',
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
