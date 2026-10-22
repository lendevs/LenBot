"""The system page saves the global identity lists without going through a group."""
import json

from test_next_limits_settings import _panel


def test_global_identity_lists_save_and_apply_without_restart(tmp_path):
    async def body(client, root):
        path = root / 'lenbot.config.json'
        snapshot = (await client.get('/api/host/settings')).json()
        assert snapshot['saved']['permissions'] == {'admins': [], 'whitelist': [], 'blacklist': []}
        lists = {'admins': ['onebot:10001'], 'whitelist': ['onebot:10002'], 'blacklist': ['onebot:10003']}
        response = await client.put('/api/host/settings/permissions', json={'permissions': lists})
        assert response.status_code == 200, response.text
        assert response.json()['saved']['permissions'] == lists
        assert response.json()['running']['permissions'] == lists
        assert response.json()['restart_required']['permissions'] is False
        assert json.loads(path.read_text())['permissions'] == lists
        for bad in ({'admins': ['10001'], 'whitelist': [], 'blacklist': []},
                    {'admins': ['onebot:1', 'onebot:1'], 'whitelist': [], 'blacklist': []},
                    {'admins': [], 'whitelist': [], 'blacklist': [], 'owners': []}):
            assert (await client.put('/api/host/settings/permissions', json={'permissions': bad})).status_code == 422
        assert (await client.put('/api/host/settings/permissions',
                                 json={'permissions': lists, 'owners': []})).status_code == 422
        assert json.loads(path.read_text())['permissions'] == lists
    _panel(tmp_path, body)
