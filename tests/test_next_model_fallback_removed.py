"""Backup-model settings were removed; configs that list them fail loudly, others load unchanged."""
import pytest
from pydantic import ValidationError

from len_bot.next.configuration.models import Models

PROVIDERS = {'main': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-key'},
             'spare': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:10/v1', 'api_key': 'synthetic-key'}}


def models(mind=None, **extra):
    return {'providers': PROVIDERS,
            'roles': {'mind': {'provider': 'main', 'model': 'mind-model', 'context_window_tokens': 8192, **(mind or {})}},
            **extra}


def test_a_config_without_backup_settings_loads_unchanged():
    loaded = Models.model_validate(models())
    assert loaded.roles.mind.model == 'mind-model'
    assert 'fallbacks' not in loaded.model_dump()['roles']['mind'] and 'failover' not in loaded.model_dump()


def test_an_empty_fallbacks_list_is_inert_and_dropped():
    loaded = Models.model_validate(models({'fallbacks': []}))
    assert 'fallbacks' not in loaded.model_dump()['roles']['mind']


@pytest.mark.parametrize(('source', 'named'), [
    (models({'fallbacks': [{'provider': 'spare', 'model': 'spare-model'}]}), 'models.roles.mind.fallbacks'),
    (models(failover={'failure_threshold': 3, 'cooldown_seconds': 60}), 'models.failover'),
    (models(failover={}), 'models.failover'),
])
def test_backup_settings_are_rejected_by_name(source, named):
    with pytest.raises(ValidationError) as error:
        Models.model_validate(source)
    assert named in str(error.value) and '已移除，请从配置中删除' in str(error.value)
