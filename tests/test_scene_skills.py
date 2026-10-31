"""The skills a scene's tasks get follow the worker's environment, for scenes present at startup and attached later."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.panel.app import create_app
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from len_bot.next.tools.skills import select_skills, worker_catalog
from len_bot.next.work.service import WorkTasks
from test_next_panel_acts_as_owner import SCENE, write_instance

NEW = 'onebot:group:80002'


def instance(root: Path, sandbox: str, egress: str) -> None:
    write_instance(root, ['onebot:70001'])
    persona = root / 'persona' / 'persona.yaml'
    persona.write_text(persona.read_text().replace('skills: []', 'skills: all'))
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    runtime = root / 'task-runtime'
    (runtime / 'bin').mkdir(parents=True)
    (runtime / 'bin' / 'lenbot-render').touch()
    source['worker'] = {
        **({'docker_binary': str(root / 'docker'), 'docker_host': 'unix:///var/run/docker.sock', 'image': 'w:1',
            'uid': 1000, 'gid': 1000} if sandbox == 'docker' else
           {'sandbox': 'bwrap', 'bwrap_binary': str(root / 'bwrap'), 'task_runtime': str(runtime)}),
        'model_reasoning': False, 'workspace_root': str(root / 'workspaces'),
        'runtime_root': str(root / 'runtime'), 'delivery_root': str(root / 'deliveries'),
        'egress': {'mode': egress}}
    source['models']['roles']['mind']['context_window_tokens'] = 65536
    source['scenes'][SCENE]['tasks'] = {'enabled': True}
    path.write_text(json.dumps(source))


@pytest.mark.parametrize('sandbox', ['docker', 'bwrap'])
@pytest.mark.parametrize('egress', ['off', 'public'])
def test_a_scene_attached_while_running_gets_the_skills_a_scene_has_at_startup(tmp_path, sandbox, egress):
    instance(tmp_path, sandbox, egress)
    config = load_host_config(tmp_path)
    persona = load_persona(config.scenes[SCENE].persona)
    expected = {skill.name for skill in worker_catalog(config.worker, SCENE)}
    assert 'pdf' in expected
    assert ('web-research' in expected) == (egress == 'public')
    assert ('public-browser' in expected) == (egress == 'public' and sandbox == 'docker')

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                tasks = WorkTasks(config, store, None, lambda scene: None,
                                  skills={SCENE: select_skills(worker_catalog(config.worker, SCENE), persona.skills)},
                                  memory=None, data_tools={SCENE: []}, skill_permissions={SCENE: persona.skills},
                                  tool_permissions={SCENE: persona.tools})
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), persona)], store, mind, tasks=tasks)
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='http://testserver') as client:
                    login = {'username': 'host-operator', 'password': 'synthetic-password'}
                    assert (await client.post('/api/auth/login', json=login)).status_code == 200
                    added = await client.post('/api/host/settings/scenes',
                                              json={'scene': NEW, 'persona': 'persona'})
                    assert added.status_code == 200, added.text
                    return {scene: {skill.name for skill in tasks.skills[scene]} for scene in (SCENE, NEW)}

    assert asyncio.run(run()) == {SCENE: expected, NEW: expected}


@pytest.mark.parametrize('sandbox', ['docker', 'bwrap'])
def test_the_skill_list_follows_a_saved_egress_change_and_the_running_list_after_restart(tmp_path, sandbox):
    instance(tmp_path, sandbox, 'off')
    config = load_host_config(tmp_path)
    persona = load_persona(config.scenes[SCENE].persona)
    internet = {'web-research', 'public-browser'}

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                tasks = WorkTasks(config, store, None, lambda scene: None,
                                  skills={SCENE: select_skills(worker_catalog(config.worker, SCENE), persona.skills)},
                                  memory=None, data_tools={SCENE: []}, skill_permissions={SCENE: persona.skills},
                                  tool_permissions={SCENE: persona.tools})
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), persona)], store, mind, tasks=tasks)
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='http://testserver') as client:
                    login = {'username': 'host-operator', 'password': 'synthetic-password'}
                    assert (await client.post('/api/auth/login', json=login)).status_code == 200

                    async def listed():
                        answer = await client.get('/api/host/skills', params={'scene': SCENE})
                        assert answer.status_code == 200, answer.text
                        data = answer.json()
                        return ({item['name'] for item in data['catalog']} & internet,
                                {item['name'] for item in data['running']} & internet)

                    before = await listed()
                    worker = json.loads((tmp_path / 'lenbot.config.json').read_text())['worker']
                    saved = await client.put('/api/host/settings/worker',
                                             json={'worker': {**worker, 'egress': {'mode': 'public'}}})
                    assert saved.status_code == 200, saved.text
                    return before, await listed()

    before, after = asyncio.run(run())
    assert before == (set(), set())
    assert after[0] == ({'web-research', 'public-browser'} if sandbox == 'docker' else {'web-research'})
    assert after[1] == set()
    restarted = load_host_config(tmp_path)
    assert {skill.name for skill in worker_catalog(restarted.worker, SCENE)} & internet == after[0]
