"""message_text, PluginTest.notice and Invocation.wait_message through the public interface."""

from pathlib import Path

import pytest

from len_bot.next.platform.messages import ChatMessage, Sender
from len_bot.plugin import Segment, message_text
from len_bot.plugin_testing import PluginTest


SOURCE = '''import asyncio
from len_bot.plugin import Plugin, command, on_notice


class Survey(Plugin):
    @command('问卷', '逐题提问')
    async def survey(self, ctx, args):
        await ctx.reply('你喜欢什么颜色？')
        answer = await ctx.wait_message(timeout_seconds=float(args or 30))
        await ctx.reply('超时了' if answer is None else '记下了：' + answer.segments[0].data['text'])

    @command('等任何人', '等这个群的下一条消息')
    async def anyone(self, ctx, args):
        answer = await ctx.wait_message(sender=None)
        await ctx.reply('收到 ' + answer.sender.uid)

    @command('重复等待', '同一个发送者等两次')
    async def twice(self, ctx, args):
        first = asyncio.ensure_future(ctx.wait_message())
        await asyncio.sleep(0)
        try:
            await ctx.wait_message()
        finally:
            first.cancel()

    @on_notice('group_increase')
    async def welcome(self, ctx, notice):
        await ctx.reply('欢迎 ' + notice.user_id)

    @on_notice('notify.poke')
    async def poked(self, ctx, notice):
        await ctx.reply('被 ' + notice.user_id + ' 戳了')

    @on_notice('group_decrease')
    async def broken(self, ctx, notice):
        raise ValueError('处理退群失败')
'''


def make_package(root: Path, *, isolation: str = 'inline', permissions: str | None = None) -> Path:
    package = root / 'survey'
    package.mkdir()
    manifest = (Path(__file__).parent / 'fixtures/plugins/sample/plugin.toml').read_text()
    manifest = manifest.replace('name = "sample"', 'name = "survey"')
    extra = f'isolation = "{isolation}"\n' + ('' if permissions is None else f'permissions = {permissions}\n')
    (package / 'plugin.toml').write_text(manifest.replace('interface = 1\n', 'interface = 1\n' + extra, 1))
    (package / '__init__.py').write_text(SOURCE)
    return package


def test_message_text_uses_chat_placeholders_and_optional_names():
    message = ChatMessage(
        id='1', platform='onebot', bot_id='onebot:90001', scene='onebot:group:80001', platform_message_id='1',
        sender=Sender('onebot:70001', 'Ann', None, None), time=0.0, reply_to='9', mentions_bot=False,
        is_self=False, send_status='received',
        segments=[Segment('reply', {'id': '9'}), Segment('text', {'text': '看 '}),
                  Segment('mention', {'user': 'onebot:70002'}), Segment('image', {'url': 'https://example.invalid/a'}),
                  Segment('audio', {'file': 'a.amr'}), Segment('mention', {'user': 'all'}),
                  Segment('face', {'id': '14'})])
    assert message_text(message) == '看 [提及 onebot:70002][图片1][语音1][提及全体成员][face：id=14]'
    assert message_text(message, names={'onebot:70002': 'Bea'}) == '看 [提及 Bea][图片1][语音1][提及全体成员][face：id=14]'


@pytest.mark.asyncio
@pytest.mark.parametrize('isolation', ['inline', 'process'])
async def test_notices_reach_handlers_by_type_and_sub_type(tmp_path, isolation):
    async with PluginTest(make_package(tmp_path, isolation=isolation)) as bot:
        assert await bot.notice('group_increase', sub_type='approve', user='onebot:70003') == 1
        assert bot.deliveries[-1].text == '欢迎 onebot:70003'
        assert await bot.notice('notify', sub_type='poke', user='onebot:70004') == 1
        assert bot.deliveries[-1].text == '被 onebot:70004 戳了'
        assert await bot.notice('group_ban', sub_type='ban', user='onebot:70004', duration=60) == 0
        with pytest.raises(RuntimeError, match='处理退群失败'):
            await bot.notice('group_decrease', sub_type='leave', user='onebot:70003')


@pytest.mark.asyncio
@pytest.mark.parametrize('isolation', ['inline', 'process'])
async def test_a_plugin_waits_for_the_same_senders_next_message(tmp_path, isolation):
    async with PluginTest(make_package(tmp_path, isolation=isolation)) as bot:
        assert await bot.message('/问卷')
        assert bot.deliveries[-1].text == '你喜欢什么颜色？'
        # Another member's message is not the answer and is left to the chat.
        assert not await bot.message('路过', sender='onebot:70009')
        assert await bot.message('蓝色')
        assert bot.deliveries[-1].text == '记下了：蓝色'
        assert any('已交给插件' in event['content'] for event in bot.events())
        # Once answered, the next message from the same member is ordinary chat again.
        assert not await bot.message('还有绿色')


@pytest.mark.asyncio
async def test_a_wait_ends_on_timeout_and_one_sender_has_one_wait(tmp_path):
    async with PluginTest(make_package(tmp_path)) as bot:
        assert await bot.message('/问卷 0.05')
        await bot.wait_tasks('命令 /问卷')
        assert bot.deliveries[-1].text == '超时了'
        assert not await bot.message('蓝色')
        assert await bot.message('/等任何人')
        assert await bot.message('我来', sender='onebot:70009')
        assert bot.deliveries[-1].text == '收到 onebot:70009'
        with pytest.raises(RuntimeError, match='已在等场景 onebot:group:80001 中 onebot:70001 的下一条消息'):
            await bot.message('/重复等待')


@pytest.mark.asyncio
async def test_waiting_needs_the_history_permission(tmp_path):
    async with PluginTest(make_package(tmp_path, permissions='["send"]')) as bot:
        with pytest.raises(RuntimeError, match='history'):
            await bot.message('/问卷')
