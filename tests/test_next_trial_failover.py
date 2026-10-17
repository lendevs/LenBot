"""Panel trials open the configured fallbacks like the host does."""
import asyncio
import json
from pathlib import Path

import httpx

from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.models.failover import FailoverModel
from len_bot.next.panel.app import create_app
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_next_panel_acts_as_owner import SCENE, write_instance


def test_trial_mind_uses_the_saved_fallbacks(tmp_path: Path):
    write_instance(tmp_path, ['onebot:70001'])
    path = tmp_path / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['providers']['spare'] = {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v2',
                                              'api_key': 'synthetic-spare'}
    source['models']['roles']['mind']['fallbacks'] = [{'provider': 'spare', 'model': 'synthetic-spare-mind'}]
    path.write_text(json.dumps(source))
    config = load_host_config(tmp_path)
    persona = load_persona(config.scenes[SCENE].persona)

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), persona)], store, mind)
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    assert (await client.post('/api/auth/login', json={
                        'username': 'host-operator', 'password': 'synthetic-password'})).status_code == 200
                    trial = await client.post('/api/host/trials', json={'scene': SCENE, 'acknowledge_model_cost': True})
                    assert trial.status_code == 200, trial.text
                    try:
                        model = app.state.trials.records[trial.json()['id']].session.chat.mind
                        assert isinstance(model, FailoverModel)
                        assert [(provider, settings.model) for provider, settings in model.candidates] == [
                            ('local', 'synthetic-mind'), ('spare', 'synthetic-spare-mind')]
                    finally:
                        await app.state.trials.close()

    asyncio.run(run())
