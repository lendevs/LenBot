"""A Telegram host can save its connection page from the panel without leaking the bot token (review ZR-6)."""
import asyncio
import json

import httpx

from len_bot.next.storage.store import Store

GROUP = 'telegram:group:-1001'
TOKEN = '123456:synthetic-token'


def _root(tmp_path):
    from len_bot.web.auth import hash_password
    from test_next_persona_permissions import _package
    root = tmp_path / 'host'; root.mkdir()
    package = _package(root, 'persona', tools=[], documents={})
    (root / 'lenbot.config.json').write_text(json.dumps({'compaction': {'input_tokens': 2000},
        'mode': 'isolated-multi', 'bot_id': 'telegram:90001', 'timezone': 'UTC', 'database': 'host.sqlite3',
        'delivery': 'telegram', 'onebot': None, 'telegram': {'bot_token': TOKEN}, 'logging': {'directory': 'logs'},
        'panel': {'host': '127.0.0.1', 'port': 0, 'username': 'operator',
                  'password_hash': hash_password('synthetic-password', salt='synthetic-salt')},
        'models': {'providers': {'local': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'unused'}},
                   'roles': {'mind': {'provider': 'local', 'model': 'synthetic-mind', 'context_window_tokens': 8192}}},
        'scenes': {GROUP: {'persona': 'persona'}}}))
    return root, package


def test_telegram_connection_page_round_trips(tmp_path):
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
                    snapshot = (await client.get('/api/host/settings')).json()
                    assert TOKEN not in json.dumps(snapshot, ensure_ascii=False)
                    connection = snapshot['saved']['connection']
                    assert connection['delivery'] == 'telegram'
                    assert connection['telegram']['bot_token_configured'] is True
                    body = {key: connection[key] for key in ('onebot', 'owners', 'timezone', 'delivery', 'max_steps',
                                                             'turn_timeout_seconds', 'max_model_requests', 'text_delivery')}
                    body['owners'] = ['telegram:7001']
                    response = await client.put('/api/host/settings/connection', json=body)
                    assert response.status_code == 200, response.text
                    assert response.json()['restart_required']['connection'] is True
                    saved = json.loads((root / 'lenbot.config.json').read_text())
                    assert saved['owners'] == ['telegram:7001'] and saved['delivery'] == 'telegram'
                    assert saved['telegram']['bot_token'] == TOKEN
    asyncio.run(exercise())
