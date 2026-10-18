"""An isolated plugin runs in its own process: it answers over a real OneBot peer, a crash fails
only that plugin, a reload brings it back, and capability checks still apply across the boundary."""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil

import pytest
from websockets.asyncio.server import serve

from len_bot.next.config import load_host_config
from len_bot.next.models.failover import open_model
from len_bot.next.persona.profile import load_persona
from len_bot.next.plugins.host import PluginHost
from test_next_plugins import CORE
from test_scene_commands_protocol import MEMBER, SCENE, Peer, claims, until, write_config

SAMPLE = Path(__file__).parent / 'fixtures/plugins/sample'
BOXED = '''
import asyncio
import os
from len_bot.next.plugins.worker import INVOCATION
from len_bot.plugin import Invocation, Plugin, command, regex


class Boxed(Plugin):
    @command("回声", "原样回复")
    async def echo(self, ctx: Invocation, args: str) -> None:
        count = await ctx.get_kv("count", 0) + 1
        await ctx.set_kv("count", count)
        await ctx.reply(f"{args}（第 {count} 次，进程 {os.getpid()}）")

    @regex(r"掷(\\d+)", "按正则回复")
    async def roll(self, ctx: Invocation, match) -> None:
        await ctx.reply("点数 " + match[1])

    @command("历史", "读取最近消息")
    async def history(self, ctx: Invocation, args: str) -> str:
        return str(len(ctx.recent_messages(5)))

    @command("委派", "以触发人身份委派，并试着冒充主人")
    async def hand(self, ctx: Invocation, args: str) -> None:
        await ctx.delegate("合成目标", "原文")
        await self.ctx.host.delegate("boxed", ctx.scene, "onebot:70009", "冒充主人", "原文", "", [])
        token, refused = INVOCATION.get(), []

        async def later():
            await asyncio.sleep(.3)
            for value in (token, None, "0" * 32):
                INVOCATION.set(value)
                try:
                    await self.ctx.host.delegate("boxed", ctx.scene, "onebot:70009", "后台冒充", "原文", "", [])
                except ValueError as error:
                    refused.append(str(error))
            await self.ctx.host.set_kv("boxed", "refused", refused)

        self.later = asyncio.create_task(later())
        await ctx.reply("已委派")

    @command("崩溃", "让进程直接退出")
    async def crash(self, ctx: Invocation, args: str) -> None:
        print("不会进入协议输出")
        os._exit(3)
'''


def plugin_packages(root: Path) -> None:
    base = root / 'plugins'
    shutil.copytree(SAMPLE, base / 'sample', ignore=shutil.ignore_patterns('__pycache__'))
    boxed = base / 'boxed'
    boxed.mkdir()
    manifest = (SAMPLE / 'plugin.toml').read_text(encoding='utf-8').split('[config')[0]
    (boxed / 'plugin.toml').write_text(manifest.replace('name = "sample"', 'name = "boxed"')
                                       + 'isolation = "process"\npermissions = ["send", "delegate"]\n', encoding='utf-8')
    (boxed / '__init__.py').write_text(BOXED, encoding='utf-8')


@asynccontextmanager
async def running(tmp_path: Path):
    from len_bot.next.runtime.network import NetworkRuntime
    from len_bot.next.storage.store import Store
    peer = Peer()
    plugin_packages(tmp_path)
    async with serve(peer.serve, '127.0.0.1', 0) as server:
        write_config(tmp_path, onebot={'mode': 'forward_ws', 'request_timeout_seconds': 1,
                                       'ws_url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'},
                     plugins={'paths': ['plugins'], 'sample': {}, 'boxed': {}})
        source = json.loads((tmp_path / 'lenbot.config.json').read_text())
        source['scenes'][SCENE]['plugins'] = ['sample', 'boxed']
        (tmp_path / 'lenbot.config.json').write_text(json.dumps(source, ensure_ascii=False))
        config = load_host_config(tmp_path)
        plugins = PluginHost(config, core_tools=CORE)
        with Store(config.database) as store:
            async with open_model(config.models, 'mind') as model:
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(tmp_path / 'persona'))],
                                         store, model, plugins=plugins)
                task = asyncio.create_task(runtime.run(manage_signals=False))
                await until(lambda: runtime.status == 'running', 10)
                await until(lambda: plugins.plugins['boxed'].status == 'running', 10)
                try:
                    yield plugins, peer, store
                finally:
                    runtime.stop()
                    await asyncio.wait_for(task, 10)


def state(plugins, name):
    return next(item for item in plugins.state()['plugins'] if item['name'] == name)


def reports(store) -> list[str]:
    return [row[0] for row in store.db.execute("SELECT content FROM plugin_events WHERE plugin = 'boxed' ORDER BY id")]


@pytest.mark.asyncio
async def test_isolated_plugin_answers_crashes_alone_and_reloads(tmp_path):
    async with running(tmp_path) as (plugins, peer, store):
        assert state(plugins, 'boxed')['isolation'] == 'process'
        await peer.say('/回声 你好')
        await until(lambda: any(text.startswith('你好（第 1 次') for text in peer.texts()), 10)
        first_pid = peer.texts()[-1].split('进程 ')[1]
        assert first_pid != str(__import__('os').getpid())
        await peer.say('掷6')
        await until(lambda: '点数 6' in peer.texts(), 10)

        await peer.say('/历史')
        await until(lambda: any('PermissionError' in item and 'history' in item for item in reports(store)), 10)

        await peer.say('/崩溃')
        await until(lambda: state(plugins, 'boxed')['status'] == 'failed', 10)
        boxed = state(plugins, 'boxed')
        assert '退出码 3' in boxed['error'] and boxed['health']['level'] == 'failed'
        await peer.say('/示例')
        await until(lambda: '详细' in peer.texts(), 10)
        assert state(plugins, 'sample')['status'] == 'running'

        await plugins.reload('boxed', load_host_config(tmp_path))
        await until(lambda: state(plugins, 'boxed')['status'] == 'running', 10)
        await peer.say('/回声 回来了')
        await until(lambda: any(text.startswith('回来了（第 2 次') for text in peer.texts()), 10)
        assert peer.texts()[-1].split('进程 ')[1] != first_pid
        assert ('boxed', 'reply') in claims(store)


class Tasks:
    """Records what reaches the task service; admission itself is covered by the account tests."""

    def __init__(self):
        self.requests = []

    async def delegate(self, scene, **arguments):
        self.requests.append((scene, arguments['requester'], arguments['goal']))
        return {'id': len(self.requests)}


@pytest.mark.asyncio
async def test_isolated_plugin_cannot_choose_the_delegate_requester(tmp_path):
    async with running(tmp_path) as (plugins, peer, store):
        tasks = plugins.runtime.tasks = Tasks()
        try:
            await delegate_and_replay(plugins, peer, tasks)
        finally:
            plugins.runtime.tasks = None


async def delegate_and_replay(plugins, peer, tasks):
    await peer.say('/委派')
    await until(lambda: '已委派' in peer.texts(), 10)
    member = f'onebot:{MEMBER}'
    assert tasks.requests == [(SCENE, member, '合成目标'), (SCENE, member, '冒充主人')]
    # After the invocation, a kept token, no token and a guessed one are all refused.
    refused = None
    async with asyncio.timeout(10):
        while refused is None:
            refused = await plugins.get_kv('boxed', 'refused', None)
            await asyncio.sleep(.05)
    assert len(refused) == 3 and all('不能伪造请求人' in text for text in refused)
    assert len(tasks.requests) == 2


def test_unsupported_entry_points_refuse_to_load_in_a_process(tmp_path):
    from test_next_plugins import _root
    root = _root(tmp_path, {'sample': {}}, ['sample'])
    manifest = root / 'plugins/sample/plugin.toml'
    manifest.write_text(manifest.read_text().replace('description = ', 'isolation = "process"\ndescription = ', 1))
    (root / 'plugins/sample/__init__.py').write_text(
        'from len_bot.plugin import Plugin, tool\n'
        'class Sample(Plugin):\n    @tool("sample_read", "读取")\n'
        '    async def read(self, ctx) -> str:\n        return "x"\n', encoding='utf-8')
    host = PluginHost(load_host_config(root), core_tools=CORE)
    record = host.plugins['sample']
    assert record.status == 'failed' and '暂不支持 tool' in record.error
