"""Model fallback configuration: same-protocol backups in priority order, panel edits keep them."""
import json

import httpx
import pytest
from pydantic import ValidationError

from len_bot.next.configuration.models import Models
from len_bot.next.models.client import ModelSettings
from test_provider_settings import instance, models_body  # noqa: F401  (fixture)

PROVIDERS = {
    'primary': {'api': 'openai-chat', 'base_url': 'https://primary.example/v1', 'api_key': 'synthetic-a'},
    'backup': {'api': 'openai-chat', 'base_url': 'https://backup.example/v1', 'api_key': 'synthetic-b'},
    'claude': {'api': 'anthropic', 'base_url': 'https://api.anthropic.com/v1', 'api_key': 'synthetic-c'},
}


def models(*fallbacks, **failover) -> Models:
    return Models.model_validate({
        'providers': PROVIDERS,
        'roles': {'mind': {'provider': 'primary', 'model': 'mind-a', 'context_window_tokens': 64000,
                           'temperature': 0.6, 'reasoning_effort': 'low', 'fallbacks': list(fallbacks)}},
        **({'failover': failover} if failover else {}),
    })


def test_without_fallbacks_the_binding_is_its_only_candidate():
    config = models()
    assert [item.model for item in config.roles.mind.candidates()] == ['mind-a']
    assert config.failover.failure_threshold == 3 and config.failover.cooldown_seconds == 60


def test_fallbacks_inherit_unset_fields_and_keep_the_primary_window():
    config = models({'provider': 'backup', 'model': 'mind-b', 'temperature': 1.0},
                    {'provider': 'backup', 'model': 'mind-c', 'thinking_budget_tokens': None,
                     'reasoning_effort': 'high'},
                    failure_threshold=2, cooldown_seconds=30)
    primary, second, third = config.roles.mind.candidates()
    assert (primary.provider, primary.model, primary.fallbacks) == ('primary', 'mind-a', [])
    assert (second.provider, second.model, second.temperature, second.reasoning_effort) == ('backup', 'mind-b', 1.0, 'low')
    assert (third.reasoning_effort, third.temperature) == ('high', 0.6)
    assert {item.context_window_tokens for item in (primary, second, third)} == {64000}
    assert config.failover.failure_threshold == 2
    # Settings for the request never carry the fallback list.
    ModelSettings.from_binding(config.providers['backup'], second)


@pytest.mark.parametrize('fallback,message', [
    ({'provider': 'missing', 'model': 'x'}, 'unknown provider'),
    ({'provider': 'claude', 'model': 'x'}, '同一协议'),
    ({'provider': 'primary', 'model': 'mind-a'}, '重复'),
    ({'provider': 'backup', 'model': ' '}, 'blank'),
    ({'provider': 'backup', 'model': 'x', 'context_window_tokens': 1000}, 'Extra inputs'),
])
def test_invalid_fallbacks_are_rejected(fallback, message):
    with pytest.raises(ValidationError, match=message):
        models(fallback)


def test_invalid_failover_settings_are_rejected():
    with pytest.raises(ValidationError):
        models(failure_threshold=0)
    with pytest.raises(ValidationError):
        models(cooldown_seconds=-1)


@pytest.mark.asyncio
async def test_panel_save_keeps_fallbacks_and_follows_a_provider_rename(instance):  # noqa: F811
    root, app = instance
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['providers']['backup'] = dict(source['models']['providers']['primary'])
    source['models']['roles']['mind']['fallbacks'] = [{'provider': 'backup', 'model': 'synthetic-backup'}]
    source['models']['failover'] = {'failure_threshold': 5, 'cooldown_seconds': 120}
    path.write_text(json.dumps(source))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        body = await models_body(client)
        assert body['roles']['mind']['fallbacks'] == [{
            'provider': 'backup', 'model': 'synthetic-backup', 'temperature': None, 'timeout_seconds': None,
            'reasoning_effort': None, 'thinking_budget_tokens': None, 'output_token_field': None,
            'retry_delays_seconds': None}]
        body['providers']['spare'] = body['providers'].pop('backup')
        response = await client.put('/api/host/settings/models', json=body)
        assert response.status_code == 200, response.text
    saved = json.loads(path.read_text())['models']
    assert saved['roles']['mind']['fallbacks'][0]['provider'] == 'spare'
    assert saved['failover'] == {'failure_threshold': 5, 'cooldown_seconds': 120}
