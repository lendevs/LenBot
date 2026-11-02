"""A plugin changing its own settings with update_config, in process and isolated, and through the panel's writer."""

from pathlib import Path

import pytest

from len_bot.plugin_testing import PluginTest


SOURCE = '''from len_bot.plugin import Plugin, command


class Rooms(Plugin):
    @command('订阅', '订阅一个房间')
    async def follow(self, ctx, args):
        rooms = [*ctx.config['rooms'], args]
        saved = await ctx.update_config({'rooms': rooms})
        await ctx.reply(f"{saved['rooms']} {self.ctx.config['rooms']} {self.ctx.config['show_details']}")

    @command('改错', '写入不合法的值')
    async def wrong(self, ctx, args):
        try:
            await ctx.update_config({args: 'x'} if args else {'rooms': 'x'})
        except ValueError as error:
            await ctx.reply(str(error).splitlines()[0])
'''

MANIFEST = '''
[config.rooms]
type = "string_list"
description = "房间"
default = []
'''


def make_package(root: Path, *, isolation: str = 'inline', permissions: str = '["send", "configure"]') -> Path:
    package = root / 'rooms'
    package.mkdir()
    manifest = (Path(__file__).parent / 'fixtures/plugins/sample/plugin.toml').read_text()
    manifest = manifest.replace('name = "sample"', 'name = "rooms"').replace(
        'interface = 1\n', f'interface = 1\nisolation = "{isolation}"\npermissions = {permissions}\n', 1)
    (package / 'plugin.toml').write_text(manifest + MANIFEST)
    (package / '__init__.py').write_text(SOURCE)
    return package


@pytest.mark.asyncio
@pytest.mark.parametrize('isolation', ['inline', 'process'])
async def test_a_plugin_saves_its_own_settings_and_uses_them_at_once(tmp_path, isolation):
    async with PluginTest(make_package(tmp_path, isolation=isolation), config={'rooms': ['1']}) as bot:
        assert await bot.message('/订阅 2')
        assert bot.deliveries[-1].text == "['1', '2'] ['1', '2'] True"
        assert bot.saved_config == {'show_details': True, 'rooms': ['1', '2']}
        assert await bot.message('/订阅 3')
        assert bot.saved_config['rooms'] == ['1', '2', '3']


@pytest.mark.asyncio
async def test_unknown_fields_and_invalid_values_are_refused_and_nothing_is_saved(tmp_path):
    async with PluginTest(make_package(tmp_path)) as bot:
        assert await bot.message('/改错 colour')
        assert bot.deliveries[-1].text == '插件 rooms 的配置没有这些字段：colour'
        assert await bot.message('/改错')
        assert bot.deliveries[-1].text.startswith('plugins.rooms 配置不合法')
        assert bot.saved_config is None


@pytest.mark.asyncio
async def test_saving_settings_needs_the_configure_permission(tmp_path):
    async with PluginTest(make_package(tmp_path, permissions='["send"]')) as bot:
        with pytest.raises(RuntimeError, match='permissions 中声明 configure'):
            await bot.message('/订阅 2')
        assert bot.saved_config is None
