"""Tool and skill permissions edited by role, whether or not a group uses the role."""

from pathlib import Path

import yaml

from test_next_persona_switch import SCENE, run_host


def test_role_tools_are_read_and_saved_by_key(tmp_path):
    async def exercise(client, runtime, store):
        created = (await client.post('/api/host/personas', json={'folder': 'second', 'name': '第二角色'})).json()
        directory = created['path']

        unused = await client.get('/api/host/personas/second/abilities')
        assert unused.status_code == 200, unused.text
        body = unused.json()
        assert (body['scene'], body['affected_scenes'], body['directory']) == (SCENE, [], directory)
        names = {tool['name'] for tool in body['tools']['catalog']}
        assert 'say' in names
        assert all('角色没有允许这个工具' not in tool['reasons'] for tool in body['tools']['catalog'])
        assert isinstance(body['skills']['catalog'], list)

        # An unused role is still checked against a group: web reading is off here.
        refused = await client.put('/api/host/personas/second/tools', json={'directory': directory, 'tools': ['say', 'web_read']})
        assert refused.status_code == 422 and 'web_read' in refused.text
        stale = await client.put('/api/host/personas/second/tools', json={'directory': '/elsewhere', 'tools': ['say']})
        assert stale.status_code == 422
        saved = await client.put('/api/host/personas/second/tools', json={'directory': directory, 'tools': ['say']})
        assert saved.status_code == 200, saved.text
        assert saved.json()['saved'] == ['say'] and saved.json()['affected_scenes'] == []
        assert yaml.safe_load((Path(directory) / 'persona.yaml').read_text())['tools'] == ['say']
        assert (await client.get('/api/host/personas/second/abilities')).json()['tools']['saved'] == ['say']
        assert runtime.chats[SCENE].persona.id == 'fixture'

        # The role a group runs takes the change right away.
        fixture = (await client.get('/api/host/personas/fixture/abilities')).json()
        assert fixture['affected_scenes'] == [SCENE]
        changed = await client.put('/api/host/personas/fixture/tools',
                                   json={'directory': fixture['directory'], 'tools': ['say', 'recall_chat']})
        assert changed.status_code == 200, changed.text
        assert changed.json()['applied'] is True
        assert runtime.chats[SCENE].persona.tools == ['say', 'recall_chat']

        skills = await client.put('/api/host/personas/fixture/skills', json={'directory': fixture['directory'], 'skills': []})
        assert skills.status_code == 200, skills.text
        assert skills.json()['saved'] == []
        assert (await client.get('/api/host/personas/missing/abilities')).status_code == 404
        assert (await client.get('/api/host/personas/second/abilities', params={'scene': 'onebot:group:1'})).status_code == 404

    run_host(tmp_path, exercise)
