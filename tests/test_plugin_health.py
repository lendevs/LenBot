"""A running plugin reports a health level the panel can show without reading its error list."""


import pytest

from len_bot.next.config import load_host_config
from len_bot.next.plugins.host import PluginHost
from test_next_plugins import CORE, _copy_sample, _root


def health(host, name):
    return next(item for item in host.state()['plugins'] if item['name'] == name)['health']


@pytest.mark.asyncio
async def test_health_follows_status_and_recent_errors(tmp_path):
    clock = [1_000_000.0]
    root = _root(tmp_path, {'sample': {}, 'broken': {}, 'resting': {}, 'disabled': ['resting']}, ['sample'])
    _copy_sample(root / 'plugins', 'broken', interface=99)
    _copy_sample(root / 'plugins', 'resting')
    host = PluginHost(load_host_config(root), core_tools=CORE, now=lambda: clock[0])
    await host.start()
    try:
        assert health(host, 'sample') == {'level': 'ok', 'errors_last_hour': 0, 'failing': [], 'last_error_at': None}
        assert health(host, 'broken')['level'] == 'failed'
        assert health(host, 'resting')['level'] == 'stopped'
        host.report_error('sample', '命令 示例', RuntimeError('上游超时'))
        assert health(host, 'sample') == {'level': 'degraded', 'errors_last_hour': 1, 'failing': [],
                                          'last_error_at': clock[0]}
        clock[0] += 3601
        assert health(host, 'sample') == {'level': 'ok', 'errors_last_hour': 0, 'failing': [],
                                          'last_error_at': clock[0] - 3601}
    finally:
        await host.close()
