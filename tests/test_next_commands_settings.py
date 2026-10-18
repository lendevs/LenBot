"""The panel switches whether group managers may use /chat and /reset, keeping the other command settings."""
import json

from test_next_limits_settings import _panel


def test_group_managers_switch_saves_and_keeps_other_command_settings(tmp_path):
    async def body(client, root):
        path = root / 'lenbot.config.json'
        config = json.loads(path.read_text())
        config['commands'] = {'disabled': ['model']}
        path.write_text(json.dumps(config))
        snapshot = (await client.get('/api/host/settings')).json()
        assert snapshot['saved']['commands']['group_managers_chat_reset'] is False
        response = await client.put('/api/host/settings/commands', json={'group_managers_chat_reset': True})
        assert response.status_code == 200, response.text
        assert response.json()['saved']['commands']['group_managers_chat_reset'] is True
        assert response.json()['restart_required']['commands'] is True
        saved = json.loads(path.read_text())['commands']
        assert saved['group_managers_chat_reset'] is True and saved['disabled'] == ['model']
        assert (await client.put('/api/host/settings/commands', json={'group_managers_chat_reset': 'yes'})).status_code == 422
        assert (await client.put('/api/host/settings/commands', json={'enabled': False,
                                                                      'group_managers_chat_reset': False})).status_code == 422
    _panel(tmp_path, body)
