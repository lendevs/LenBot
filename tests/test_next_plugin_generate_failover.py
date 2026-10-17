"""A plugin's one-shot generation follows the role's fallbacks, like the host's own requests."""

import json
import logging

import pytest

from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.models.failover import HEALTH
from len_bot.next.persona.profile import load_persona
from len_bot.next.plugins.host import PluginHost
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_next_model import recorded_text_response
from test_next_native_models import peer_server
from test_next_persona_permissions import _package
from test_next_plugins import CORE, _root

GROUP = 'onebot:group:80001'
OK = (200, 'application/json', json.dumps(recorded_text_response()).encode())
DOWN = (503, 'text/plain', b'upstream unavailable')


def endpoint(server):
    return f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'


@pytest.mark.asyncio
async def test_plugin_generation_moves_to_the_backup_when_the_primary_is_down(tmp_path, caplog):
    primary_seen, backup_seen = [], []
    primary = await peer_server([DOWN], primary_seen)
    backup = await peer_server([OK], backup_seen)
    async with primary, backup:
        root = _root(tmp_path, {'sample': {}}, ['sample'])
        _package(root, 'role', tools=[], documents={})
        source = json.loads((root / 'lenbot.config.json').read_text())
        source['models'] = {
            'providers': {'main': {'api': 'openai-chat', 'base_url': endpoint(primary), 'api_key': 'synthetic-a'},
                          'spare': {'api': 'openai-chat', 'base_url': endpoint(backup), 'api_key': 'synthetic-b'}},
            'roles': {'mind': {'provider': 'main', 'model': 'plugin-primary', 'context_window_tokens': 8192,
                               'fallbacks': [{'provider': 'spare', 'model': 'plugin-backup'}]}}}
        (root / 'lenbot.config.json').write_text(json.dumps(source))
        config = load_host_config(root)
        host = PluginHost(config, core_tools=CORE)
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                NetworkRuntime(config, [(config.scene_config(GROUP), load_persona(root / 'role'))], store, mind,
                               plugins=host)
                with caplog.at_level(logging.INFO):
                    text = await host.plugins['sample'].context.generate(GROUP, '写一句问候')
            await host.close()
    assert text == recorded_text_response()['choices'][0]['message']['content']
    assert len(primary_seen) == 1 and backup_seen[0][2]['model'] == 'plugin-backup'
    record = next(item for item in caplog.records if getattr(item, 'event', None) == 'model_call')
    assert record.fields['plugin'] == 'sample' and record.fields['provider'] == 'main'
    assert (record.fields['served_provider'], record.fields['served_model']) == ('spare', 'plugin-backup')
    state = HEALTH.state()['roles']['mind']
    assert state['last_served']['provider'] == 'spare' and state['last_served']['model'] == 'plugin-backup'
