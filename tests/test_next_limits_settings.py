"""Saving limits from the panel changes only what was sent and refuses stale snapshots (audit B-2)."""
import asyncio
import json

import httpx

from len_bot.next.storage.store import Store

GROUP = 'onebot:group:80001'


def _root(tmp_path):
    from len_bot.web.auth import hash_password
    from test_next_persona_permissions import _package
    root = tmp_path / 'host'; root.mkdir()
    package = _package(root, 'persona', tools=[], documents={})
    (root / 'lenbot.config.json').write_text(json.dumps({'compaction': {'input_tokens': 2000},
        'mode': 'isolated-multi', 'bot_id': 'onebot:90001', 'timezone': 'UTC', 'database': 'host.sqlite3',
        'delivery': 'simulated', 'onebot': None, 'logging': {'directory': 'logs'},
        'panel': {'host': '127.0.0.1', 'port': 0, 'username': 'operator',
                  'password_hash': hash_password('synthetic-password', salt='synthetic-salt')},
        'models': {'providers': {'local': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'unused'}},
                   'roles': {'mind': {'provider': 'local', 'model': 'synthetic-mind', 'context_window_tokens': 8192}}},
        'scenes': {GROUP: {'persona': 'persona'}}}))
    return root, package


def _panel(tmp_path, body):
    from len_bot.next.config import load_host_config
    from len_bot.next.models.client import ChatModel
    from len_bot.next.panel.app import create_app
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.runtime.network import NetworkRuntime
    root, package = _root(tmp_path)
    config = load_host_config(root)
    persona = load_persona(package)

    async def exercise():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                runtime = NetworkRuntime(config, [(config.scene_config(s), persona) for s in config.scenes], store, mind)
                app = create_app(config, runtime, root=root)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    assert (await client.post('/api/auth/login', json={'username': 'operator',
                                                                         'password': 'synthetic-password'})).status_code == 200
                    await body(client, root)
    asyncio.run(exercise())


def _saved(root):
    return json.loads((root / 'lenbot.config.json').read_text())['limits']


def test_partial_limits_save_keeps_fields_it_did_not_send(tmp_path):
    async def body(client, root):
        put = lambda value: client.put('/api/host/settings/limits', json=value)
        assert (await put({'direct_reserve': 1, 'speech_notice_text': '满了', 'daily_tokens': 5000})).status_code == 200
        assert (await client.put(f'/api/host/settings/limits/scenes/{GROUP}',
                                 json={'mode': 'custom', 'value': 5})).status_code == 200
        snapshot = (await put({'messages_per_hour': 60})).json()
        limits = snapshot['saved']['limits']
        assert limits['direct_reserve'] == 1 and limits['speech_notice_text'] == '满了'
        assert limits['daily_tokens'] == 5000 and limits['scene_messages_per_hour'] == {GROUP: 5}
        assert _saved(root)['scene_messages_per_hour'] == {GROUP: 5}
        # Explicit null still clears an optional value; invalid merged values are refused.
        assert (await put({'speech_notice_text': None})).json()['saved']['limits']['speech_notice_text'] is None
        assert (await put({'direct_reserve': None})).status_code == 422
        assert (await put({'messages_per_hour': 0})).status_code == 422
        assert (await put({'unknown': 1})).status_code == 422
    _panel(tmp_path, body)


def test_stale_tab_cannot_wipe_per_group_settings(tmp_path):
    """Tab B opens settings, tab A saves a group limit, then tab B saves the global limit."""
    async def body(client, root):
        tab_b = (await client.get('/api/host/settings')).json()
        tab_a = await client.put(f'/api/host/settings/limits/scenes/{GROUP}', json={'mode': 'custom', 'value': 5})
        assert tab_a.status_code == 200
        # Even the old whole-snapshot body (what the panel used to send) is refused when stale.
        stale = {**tab_b['saved']['limits'], 'messages_per_hour': 30, 'version': tab_b['versions']['limits']}
        response = await client.put('/api/host/settings/limits', json=stale)
        assert response.status_code == 409
        detail = response.json()['detail']
        assert '重新载入' in detail['message']
        assert detail['data']['snapshot']['saved']['limits']['scene_messages_per_hour'] == {GROUP: 5}
        assert _saved(root)['scene_messages_per_hour'] == {GROUP: 5} and _saved(root).get('messages_per_hour', 60) == 60
        # After reloading, the same edit goes through and keeps the group setting.
        fresh = detail['data']['snapshot']['versions']['limits']
        saved = await client.put('/api/host/settings/limits', json={'messages_per_hour': 30, 'version': fresh})
        assert saved.status_code == 200
        assert saved.json()['saved']['limits']['scene_messages_per_hour'] == {GROUP: 5}
        assert saved.json()['versions']['limits'] != fresh
        # Token-limit section: same route, same protection.
        token = await client.put('/api/host/settings/limits', json={'daily_tokens': 1000, 'scene_daily_tokens': {},
                                                                    'version': fresh})
        assert token.status_code == 409
        token = await client.put('/api/host/settings/limits', json={'daily_tokens': 1000, 'scene_daily_tokens': {},
                                                                    'version': saved.json()['versions']['limits']})
        assert token.status_code == 200
        limits = _saved(root)
        assert limits['daily_tokens'] == 1000 and limits['messages_per_hour'] == 30
        assert limits['scene_messages_per_hour'] == {GROUP: 5}
    _panel(tmp_path, body)

