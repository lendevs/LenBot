"""The public readiness answer tells whether the bot is connected to QQ, as the updater checks it."""

import httpx
import pytest

from len_bot.next.panel.app import create_app
from len_bot.web.auth import hash_password
from test_scene_commands_protocol import host, until

PANEL = {'host': '127.0.0.1', 'port': 0, 'username': 'operator',
         'password_hash': hash_password('synthetic-password', salt='synthetic-salt')}


@pytest.mark.asyncio
async def test_ready_reports_the_qq_connection_and_its_loss(tmp_path):
    async with host(tmp_path, panel=PANEL) as (runtime, peer, store):
        app = create_app(runtime.config, runtime, root=tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            ready = (await client.get('/api/host/ready')).json()
            assert ready['ready'] is True
            assert ready['platform'] == {'connected': True, 'connected_since': runtime.connected_since}
            await peer.socket.close()
            await until(lambda: not runtime.platform.connected)
            ready = (await client.get('/api/host/ready')).json()
            assert ready['ready'] is True and ready['platform'] == {'connected': False, 'connected_since': None}
            # The host dials the peer again by itself.
            await until(lambda: runtime.platform.connected, 5)
            assert (await client.get('/api/host/ready')).json()['platform']['connected'] is True


@pytest.mark.asyncio
async def test_ready_without_a_platform_has_no_connection_to_report(tmp_path):
    from len_bot.next.config import load_host_config
    from len_bot.next.models.client import ChatModel
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.runtime.network import NetworkRuntime
    from len_bot.next.storage.store import Store
    from test_scene_commands_protocol import SCENE, write_config

    write_config(tmp_path, onebot=None, delivery='simulated', panel=PANEL)
    config = load_host_config(tmp_path)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as model:
            runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(tmp_path / 'persona'))],
                                     store, model)
            app = create_app(config, runtime, root=tmp_path)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                ready = (await client.get('/api/host/ready')).json()
    assert ready['platform'] is None and 'version' in ready
