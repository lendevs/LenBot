"""Panel diagnostics: event loop stall metrics behind the panel login."""
import asyncio
import time

import httpx

from len_bot.next.runtime.loop_monitor import MONITOR
from test_next_panel_acts_as_owner import exercise, write_instance


def test_event_loop_metrics_require_login_and_report_stalls(tmp_path):
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client: httpx.AsyncClient):
        probe = asyncio.create_task(MONITOR.run())
        await asyncio.sleep(0.05)
        before = (await client.get('/api/host/event-loop')).json()
        assert before['running'] is True
        time.sleep(MONITOR.interval + MONITOR.threshold + 0.4)  # hold the loop past the threshold
        await asyncio.sleep(MONITOR.interval + 0.1)
        state = (await client.get('/api/host/event-loop')).json()
        probe.cancel()
        await asyncio.gather(probe, return_exceptions=True)
        assert state['stalls'] == before['stalls'] + 1
        assert state['recent'][0]['lag_ms'] >= MONITOR.threshold * 1000
        assert 'check' in state['recent'][0]['stack']
        assert set(state) == {'running', 'started_at', 'interval_ms', 'threshold_ms', 'probes', 'stalls',
                              'stalled_ms_total', 'max_lag_ms', 'recent'}
        await client.post('/api/auth/logout')
        assert (await client.get('/api/host/event-loop')).status_code == 401

    exercise(tmp_path, check)


def test_provider_health_lists_roles_with_fallbacks(tmp_path):
    from len_bot.next.models.failover import HEALTH, FailoverModel
    from len_bot.next.models.client import ModelSettings
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client: httpx.AsyncClient):
        candidates = [(name, ModelSettings(api='openai-chat', base_url=f'https://{name}.example/v1',
                                           api_key='synthetic-key', model=f'{name}-model'))
                      for name in ('primary', 'spare')]
        async with FailoverModel('learner', candidates, HEALTH):
            HEALTH.failed('learner', 'primary', 'primary-model', TimeoutError('slow'))
            state = (await client.get('/api/host/model-providers/health')).json()
        role = state['roles']['learner']
        assert [(row['priority'], row['provider'], row['model']) for row in role['candidates']] == [
            (0, 'primary', 'primary-model'), (1, 'spare', 'spare-model')]
        assert role['candidates'][0]['consecutive_failures'] == 1
        assert role['candidates'][0]['last_error'] == 'TimeoutError: slow'
        assert {'failure_threshold', 'cooldown_seconds', 'roles'} <= set(state)
        await client.post('/api/auth/logout')
        assert (await client.get('/api/host/model-providers/health')).status_code == 401

    exercise(tmp_path, check)
