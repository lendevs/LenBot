"""Plugin manifests declare host capabilities; an undeclared one is refused at the call."""

import pytest

from len_bot.next.config import load_host_config
from len_bot.next.plugins.host import PluginHost
from len_bot.next.plugins.manifest import read_manifest
from test_next_plugins import CORE, _root

GROUP = 'onebot:group:80001'


def declare(root, line):
    manifest = root / 'plugins/sample/plugin.toml'
    text = manifest.read_text(encoding='utf-8')
    manifest.write_text(text.replace('description = ', line + '\ndescription = ', 1), encoding='utf-8')


@pytest.mark.asyncio
async def test_declared_permissions_limit_the_context(tmp_path):
    root = _root(tmp_path, {'sample': {}}, ['sample'])
    declare(root, 'permissions = ["send", "history"]')
    host = PluginHost(load_host_config(root), core_tools=CORE)
    ctx = host.plugins['sample'].context
    try:
        # Declared: the call passes the permission check and stops at the missing runtime.
        with pytest.raises(RuntimeError, match='尚未接入'):
            ctx.recent_messages(GROUP)
        for call, permission in ((lambda: ctx.generate(GROUP, '你好'), 'generate'),
                                 (lambda: ctx.memory(GROUP, {'action': 'search', 'query': 'x'}), 'memory'),
                                 (lambda: ctx.fetch_image('https://example.com/a.png'), 'network')):
            with pytest.raises(PermissionError, match=f'未在 plugin.toml 的 permissions 中声明 {permission}'):
                await call()
        with pytest.raises(PermissionError, match='声明 events'):
            await ctx.emit_event(GROUP, '有新动态')
        state = next(item for item in host.state()['plugins'] if item['name'] == 'sample')
        assert state['permissions'] == [{'name': 'send', 'title': '在启用的群内发送消息'},
                                        {'name': 'history', 'title': '读取启用的群的聊天记录'}]
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_manifest_without_permissions_keeps_every_capability(tmp_path):
    root = _root(tmp_path, {'sample': {}}, ['sample'])
    host = PluginHost(load_host_config(root), core_tools=CORE)
    try:
        with pytest.raises(RuntimeError, match='尚未接入'):
            host.plugins['sample'].context.recent_messages(GROUP)
        assert next(item for item in host.state()['plugins'] if item['name'] == 'sample')['permissions'] is None
    finally:
        await host.close()


@pytest.mark.parametrize('line', ['permissions = ["send", "send"]', 'permissions = ["root"]'])
def test_unknown_or_repeated_permissions_are_refused(tmp_path, line):
    root = _root(tmp_path, {'sample': {}}, ['sample'])
    declare(root, line)
    with pytest.raises(ValueError, match='permissions'):
        read_manifest(root / 'plugins/sample')
