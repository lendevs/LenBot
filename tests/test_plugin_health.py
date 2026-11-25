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


@pytest.mark.asyncio
async def test_typed_and_legacy_disabled_rules_distinguish_fullmatch_and_regex(tmp_path):
    source = '''from len_bot.plugin import Plugin, fullmatch, regex, tool


class DualPlugin(Plugin):
    @fullmatch("签到", "精确签到")
    async def exact_checkin(self, ctx):
        await ctx.reply("exact")

    @regex("签到", "正则签到")
    async def pattern_checkin(self, ctx, match):
        await ctx.reply("regex")
'''
    for sub, disabled, expected_full, expected_regex in (
        ('typed_full', ['fullmatch:签到'], True, False),
        ('typed_regex', ['regex:签到'], False, True),
        ('legacy_bare', ['签到'], True, True),
    ):
        case_dir = tmp_path / sub
        case_dir.mkdir()
        root = _root(case_dir, {'sample': {}, 'disabled_rules': {'sample': disabled}}, ['sample'])
        (root / 'plugins' / 'sample' / '__init__.py').write_text(source, encoding='utf-8')
        host = PluginHost(load_host_config(root), core_tools=CORE)
        await host.start()
        try:
            rules = {(item['kind'], item['pattern']): item['disabled']
                     for item in host.state()['plugins'][0]['rules']}
            assert rules[('fullmatch', '签到')] is expected_full
            assert rules[('regex', '签到')] is expected_regex
        finally:
            await host.close()


@pytest.mark.asyncio
async def test_state_and_tool_previews_do_not_emit_updates_when_unavailable_tools_raises(tmp_path):
    source = '''from len_bot.plugin import Plugin, tool


class BrokenCheckPlugin(Plugin):
    def unavailable_tools(self, scene: str) -> dict[str, str]:
        raise RuntimeError("配置连接断开")

    @tool("ping_ext", "测试工具")
    async def ping_ext(self, ctx) -> str:
        return "pong"
'''
    root = _root(tmp_path, {'sample': {}}, ['sample'])
    (root / 'plugins' / 'sample' / '__init__.py').write_text(source, encoding='utf-8')
    host = PluginHost(load_host_config(root), core_tools=CORE)
    await host.start()
    notifications = 0
    host.on_update = lambda: None

    def bump():
        nonlocal notifications
        notifications += 1

    host.on_update = bump
    try:
        scene = next(iter(host.config.scenes))
        snapshot = host.state()['plugins'][0]
        assert 'RuntimeError: 配置连接断开' in snapshot['unavailable_tools']['ping_ext']
        assert snapshot['errors'] == []
        assert notifications == 0

        previews = host.tool_previews(scene)
        assert any('RuntimeError: 配置连接断开' in r for r in previews[0]['reasons'])
        assert host.plugins['sample'].errors == deque_empty(host.plugins['sample'].errors)
        assert notifications == 0

        # Actual runtime tool resolution still records the error and notifies.
        assert host.tools_for(scene) == []
        assert len(host.plugins['sample'].errors) == 1
        assert notifications == 1
    finally:
        await host.close()


def deque_empty(items):
    return type(items)()
