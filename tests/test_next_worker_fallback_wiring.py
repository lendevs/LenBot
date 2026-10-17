"""The task runner hands the worker role's saved fallbacks to the model proxy."""
import asyncio
import inspect

import pytest

from len_bot.next.configuration.models import Models
from len_bot.next.configuration.tasks import EgressSettings
from len_bot.next.models.client import ModelSettings
from len_bot.next.models.failover import HEALTH, ProviderHealth, fallback_settings
from len_bot.next.work import execution
from len_bot.next.work.worker_model import Limits
from len_bot.next.work.worker_session import worker_session


def models(**worker):
    return Models.model_validate({
        'providers': {'main': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'main-key'},
                      'spare': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:10/v1', 'api_key': 'spare-key'}},
        'roles': {'mind': {'provider': 'main', 'model': 'mind-model', 'context_window_tokens': 8192},
                  'worker': {'provider': 'main', 'model': 'worker-model', 'context_window_tokens': 8192, **worker}},
        'failover': {'failure_threshold': 2, 'cooldown_seconds': 5},
    })


def test_worker_fallbacks_resolve_to_full_settings_in_priority_order():
    health = ProviderHealth()
    config = models(fallbacks=[{'provider': 'spare', 'model': 'spare-model', 'timeout_seconds': 30}])
    [(provider, settings)] = fallback_settings(config, 'worker', health)
    assert (provider, settings.model, settings.base_url, settings.api_key, settings.timeout_seconds) == (
        'spare', 'spare-model', 'http://127.0.0.1:10/v1', 'spare-key', 30)
    assert health.settings.failure_threshold == 2
    assert fallback_settings(models(), 'worker', ProviderHealth()) == []


def test_task_runner_passes_worker_fallbacks_and_the_shared_circuits():
    source = inspect.getsource(execution)
    assert 'fallbacks=fallback_settings(self.config.models, "worker"), health=HEALTH' in source


def test_worker_session_builds_its_proxy_with_the_fallbacks():
    config = models(fallbacks=[{'provider': 'spare', 'model': 'spare-model'}])
    primary = ModelSettings.from_binding(config.providers['main'], config.roles.worker)
    built = []

    class Stop(Exception):
        pass

    def capture(proxy):
        built.append(proxy)
        raise Stop

    async def run():
        async with worker_session(
            None, scene='onebot:group:80001', task_id='1', settings=primary, provider='main',
            context_window_tokens=8192, limits=Limits(5, 100000, 100000), skills=(), data_tools=[],
            task_timeout_seconds=60, public_browser=False, egress_settings=EgressSettings(), fake_ip_networks=(),
            egress_bytes_per_second=1, before_bytes=lambda *_: None, on_connection=lambda *_: None,
            on_bytes=lambda *_: None, model_reasoning=False, compaction_reserve_tokens=1,
            compaction_keep_recent_tokens=1, start_call=lambda facts: 1, finish_call=lambda *_: None,
            on_proxy=capture, fallbacks=fallback_settings(config, 'worker', HEALTH), health=HEALTH,
        ):
            pytest.fail('session should not start')

    with pytest.raises(Stop):
        asyncio.run(run())
    [proxy] = built
    assert [(provider, settings.model) for provider, settings in proxy.candidates] == [
        ('main', 'worker-model'), ('spare', 'spare-model')]
    assert proxy.health is HEALTH
    assert proxy.recorded('main-key spare-key') == '[credential removed] [credential removed]'
