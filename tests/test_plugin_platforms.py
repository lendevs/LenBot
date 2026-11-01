"""Plugins in Telegram and Feishu scenes: the scene's bot, platform, mentions and media through PluginTest."""

from pathlib import Path

import pytest

from len_bot.plugin import Segment
from len_bot.plugin_testing import PluginTest

TELEGRAM = 'telegram:group:-1001234'
FEISHU = 'feishu:group:oc_room'
SOURCE = '''from len_bot.plugin import Mention, Plugin, Text, command


class Places(Plugin):
    @command('在哪', '平台和 Bot 账号')
    async def where(self, ctx, args):
        await ctx.reply(ctx.platform + ' ' + ctx.bot_id)

    @command('提及', '提及正文里写的账号')
    async def mention(self, ctx, args):
        await ctx.reply_parts([Mention(args), Text(' 你好')])

    @command('全员', '提及全体成员')
    async def everyone(self, ctx, args):
        sent = await ctx.reply_parts([Mention('all'), Text(' 开会了')])
        await ctx.reply(sent.report)

    @command('图片大小', '读取本群最近一张图片')
    async def size(self, ctx, args):
        image = next(part for message in reversed(ctx.recent_messages()) for part in message.segments
                     if part.type == 'image')
        await ctx.reply(str(len(await ctx.fetch_media(image))))
'''


@pytest.fixture
def package(tmp_path):
    package = tmp_path / 'places'
    package.mkdir()
    manifest = (Path(__file__).parent / 'fixtures/plugins/sample/plugin.toml').read_text()
    (package / 'plugin.toml').write_text(manifest.replace('name = "sample"', 'name = "places"'))
    (package / '__init__.py').write_text(SOURCE)
    return package


@pytest.mark.asyncio
@pytest.mark.parametrize('isolation', ['inline', 'process'])
async def test_each_scene_sees_its_own_platform_and_bot(package, isolation):
    manifest = package / 'plugin.toml'
    manifest.write_text(manifest.read_text().replace('interface = 1', f'interface = 1\nisolation = "{isolation}"'))
    scenes = ('onebot:group:80001', TELEGRAM, FEISHU)
    bots = {'telegram': 'telegram:7001', 'feishu': 'feishu:ou_bot'}
    async with PluginTest(package, scenes=scenes, bots=bots) as bot:
        expected = {'onebot:group:80001': 'onebot onebot:90001', TELEGRAM: 'telegram telegram:7001',
                    FEISHU: 'feishu feishu:ou_bot'}
        for scene, text in expected.items():
            assert await bot.message('/在哪', scene=scene)
            assert bot.deliveries[-1].text == text
        # A command after @Bot is taken in the scene's own platform.
        assert await bot.message('', scene=TELEGRAM, sender='telegram:501',
                                 parts=[Segment('mention', {'user': 'telegram:7001'}), Segment('text', {'text': ' /在哪'})])
        assert not await bot.message('', scene=TELEGRAM, sender='telegram:501',
                                     parts=[Segment('mention', {'user': 'onebot:90001'}), Segment('text', {'text': ' /在哪'})])
        bot.add_media('AgACAgQ', b'telegram-photo')
        bot.add_message('', scene=TELEGRAM, sender='telegram:501',
                        parts=[Segment('image', {'file_id': 'AgACAgQ', 'file_unique_id': 'u'})])
        assert await bot.message('/图片大小', scene=TELEGRAM, sender='telegram:501')
        assert bot.deliveries[-1].text == str(len(b'telegram-photo'))


@pytest.mark.asyncio
async def test_mentions_follow_the_scene_platform(package):
    async with PluginTest(package, scenes=(TELEGRAM, FEISHU), bots={'telegram': 'telegram:7001',
                                                                    'feishu': 'feishu:ou_bot'}) as bot:
        with pytest.raises(RuntimeError, match='不属于场景 telegram:group:-1001234 的平台 telegram'):
            await bot.message('/提及 onebot:70001', scene=TELEGRAM, sender='telegram:501')
        assert await bot.message('/提及 telegram:502', scene=TELEGRAM, sender='telegram:501')
        assert await bot.message('/全员', scene=TELEGRAM, sender='telegram:501')
        assert [type(part).__name__ for part in bot.deliveries[-2].parts] == ['Text']
        assert bot.deliveries[-1].text.endswith('telegram 没有全员提醒，已省略提及全体成员')
        assert await bot.message('/全员', scene=FEISHU, sender='feishu:ou_ann')
        assert [type(part).__name__ for part in bot.deliveries[-2].parts] == ['Mention', 'Text']


@pytest.mark.parametrize('value, error', [('["qq"]', 'chat_platforms'), ('["onebot", "onebot"]', 'must not repeat'),
                                          ('[]', 'chat_platforms')])
def test_chat_platforms_names_known_platforms_once(tmp_path, value, error):
    from len_bot.next.plugins.manifest import parse_manifest
    manifest = tmp_path / 'plugin.toml'
    source = (Path(__file__).parent / 'fixtures/plugins/sample/plugin.toml').read_text()
    manifest.write_text(source.replace('interface = 1\n', f'interface = 1\nchat_platforms = {value}\n', 1))
    with pytest.raises(ValueError, match=error):
        parse_manifest(manifest)


@pytest.mark.asyncio
async def test_installing_from_a_catalog_checks_declared_chat_platforms(tmp_path):
    from len_bot.next.plugins.install import PluginInstaller
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    source = (Path(__file__).parent / 'fixtures/plugins/sample/plugin.toml').read_text()
    (checkout / 'plugin.toml').write_text(source.replace('interface = 1\n', 'interface = 1\nchat_platforms = ["onebot"]\n', 1))
    (checkout / '__init__.py').write_text('')
    installer = PluginInstaller(tmp_path / "instance")
    with pytest.raises(ValueError, match='仓库清单声明的聊天平台是'):
        await installer.candidate(checkout, None, [], switch_source=False, expected_chat_platforms=['telegram'])
