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
