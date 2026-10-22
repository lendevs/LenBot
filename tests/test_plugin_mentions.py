"""Opted-in commands retain real mentions; ordinary matching remains text-only."""

import json
from pathlib import Path

import pytest

from len_bot.plugin import Segment
from len_bot.plugin_testing import PluginTest


@pytest.fixture
def package(tmp_path):
    package = tmp_path / 'mentions'
    package.mkdir()
    source = Path(__file__).parent / 'fixtures/plugins/sample/plugin.toml'
    manifest = source.read_text().replace('name = "sample"', 'name = "mentions"')
    (package / 'plugin.toml').write_text(manifest)
    (package / '__init__.py').write_text('''from len_bot.plugin import Plugin, command, fullmatch, regex
class Mentions(Plugin):
    @command('转发', '保留真实提及', allow_mentions=True)
    async def forward(self, ctx, args):
        await ctx.reply(args + '|' + ','.join(part.data['user'] for part in ctx.message.segments if part.type == 'mention'))
    @command('纯文', '默认不接管正文提及')
    async def plain(self, ctx, args):
        await ctx.reply(args)
    @command('角色', '插件显式接管同名命令')
    async def role(self, ctx, args):
        await ctx.reply('插件角色 ' + args)
    @fullmatch('全文 匹配', '不把提及当作不可见文字')
    async def exact(self, ctx):
        await ctx.reply('全文')
    @regex('正则.*', '不接管正文提及')
    async def pattern(self, ctx, match):
        await ctx.reply('正则')
''')
    return package


@pytest.mark.asyncio
@pytest.mark.parametrize('isolation', ['inline', 'process'])
async def test_mentions_are_opt_in_for_commands_and_round_trip_through_process(package, isolation):
    manifest = package / 'plugin.toml'
    manifest.write_text(manifest.read_text().replace('interface = 1', f'interface = 1\nisolation = "{isolation}"'))
    mention = Segment('mention', {'user': 'onebot:70002'})
    async with PluginTest(package) as bot:
        assert await bot.message('/转发 查询 ', parts=[mention, Segment('text', {'text': ' 状态'})])
        assert bot.deliveries[-1].text == '查询   状态|onebot:70002'
        assert await bot.message('/纯文 查询')
        for text in ('/纯文 查询 ', '全文 ', '正则 '):
            assert not await bot.message(text, parts=[mention, Segment('text', {'text': '匹配'})])
        assert not await bot.message('/转发 图片', parts=[Segment('image', {'url': 'https://example.invalid/image.png'})])
        assert not await bot.message('/转发 引用', parts=[Segment('reply', {'id': '42'})])
        assert await bot.message('/角色 示例')
        assert bot.deliveries[-1].text == '插件角色 示例'
        assert json.loads(json.dumps(bot.state()))['plugins'][0]['status'] == 'running'
