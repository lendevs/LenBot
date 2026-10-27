"""A scene whose memory_plugin names a plugin takes its automatic recall from that plugin's @recall entry.

The host builds one request per turn, keeps the returned blocks within the budget, shows them like
native recall and goes on without recall when the plugin fails; process plugins answer the same way.
"""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path

import pytest

from len_bot.next.config import load_host_config
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel
from len_bot.next.panel.routes.timeline import read_turn
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.messages import ChatMessage, Segment, Sender, plain_text
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.plugins import host as plugin_host
from len_bot.next.plugins.host import PluginHost
from len_bot.next.runtime.lifecycle import HostLifecycle
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from len_bot.plugin import RecallRequest
from test_next_host_manage_permissions_config import instance
from test_next_message_reaction import incoming
from test_next_model import recorded_response, recorded_text_response
from test_next_native_models import peer_server
from test_next_plugins import CORE, _copy_sample, _root

SCENE = 'onebot:group:80001'
NOTES = '''
import asyncio
from len_bot.plugin import Plugin, RecallBlock, recall


class Notes(Plugin):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.requests = []
        self.mode = "ok"

    @recall()
    async def remember(self, request):
        self.requests.append(request)
        if self.mode == "fail":
            raise RuntimeError("索引损坏")
        if self.mode == "slow":
            await asyncio.sleep(30)
        if self.mode == "wrong":
            return "不是块"
        said = " / ".join(segment.data["text"] for message in request.messages
                          for segment in message.segments if segment.type == "text")
        return [RecallBlock("约定", "周六下午三点在东门集合"), RecallBlock("空", "  "),
                RecallBlock("原话", said), RecallBlock("长记录", "长" * 5000), RecallBlock("预算外", "不显示")]
'''


def notes_package(base: Path, *, process: bool = False, source: str = NOTES) -> None:
    directory = _copy_sample(base, 'notes')
    manifest = (directory / 'plugin.toml').read_text(encoding='utf-8')
    if process:
        manifest = manifest.replace('description = ', 'isolation = "process"\ndescription = ', 1)
    (directory / 'plugin.toml').write_text(manifest, encoding='utf-8')
    (directory / '__init__.py').write_text(source, encoding='utf-8')


def request(**values) -> RecallRequest:
    message = ChatMessage(id='m1', platform='onebot', bot_id='onebot:90001', scene=SCENE, platform_message_id='1',
                          sender=Sender('onebot:70001', '群友', None, 'member'), time=1.0,
                          segments=[Segment('text', {'text': '秋游几点集合'})], reply_to=None, mentions_bot=False,
                          is_self=False, send_status='received')
    return RecallRequest(**{'scene': SCENE, 'persona': 'role', 'turn_id': 't1', 'observed_at': 2.0,
                            'messages': (message,), 'recap': None, 'tasks': (), 'budget_chars': 300, **values})


@asynccontextmanager
async def running(root: Path, replies: list[dict], received: list, *, plugin: str = NOTES,
                  tools: list[str] | None = None):
    server = await peer_server([(200, 'application/json', json.dumps(body).encode()) for body in replies], received)
    async with server:
        source = instance(root)
        source['compaction']['input_tokens'] = 6000
        source['models']['providers']['fixture']['base_url'] = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        source['plugins'] = {'paths': ['plugins'], 'notes': {}}
        source['scenes'][SCENE].update(plugins=['notes'], memory_plugin='notes')
        notes_package(root / 'plugins', source=plugin)
        if tools is not None:
            persona = root / 'persona/persona.yaml'
            persona.write_text(persona.read_text().replace('tools: [say, tool_search, host_manage]',
                                                           f'tools: [{", ".join(tools)}]'))
        (root / 'lenbot.config.json').write_text(json.dumps(source, ensure_ascii=False))
        config = load_host_config(root)
        plugins = PluginHost(config, core_tools=CORE)
        persona = load_persona(config.scenes[SCENE].persona)
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
                runtime = NetworkRuntime(config, [(config.scene_config(scene), persona) for scene in config.scenes],
                                         store, mind, memory=memory, plugins=plugins, lifecycle=HostLifecycle())
                await plugins.start()
                try:
                    yield runtime
                finally:
                    await plugins.close()


async def turn(runtime) -> dict:
    store, chat = runtime.store, runtime.chats[SCENE]
    raw = incoming()
    seq = store.enqueue(parse_message(raw, own_message_ids=set()), raw, store.now())

    async def append_new(called, turn):
        return False

    async def wait_for_messages(seconds):
        return '没有新消息'

    async def native(*args, **kwargs):
        raise AssertionError('the native memory must not recall for a plugin scene')

    chat.memory.recall = native
    result = await chat.run_turn(batch=(seq, ['接个梗']), append_new=append_new,
                                 wait_for_messages=wait_for_messages, attention_state={})
    assert result['status'] == 'settled', result
    return result


def replies() -> list[dict]:
    first = recorded_response()
    first['choices'][0]['message']['tool_calls'][0]['function'] = {'name': 'say', 'arguments': json.dumps({'content': '好'})}
    return [first, recorded_text_response()]


@pytest.mark.asyncio
async def test_a_plugin_scene_recalls_from_its_plugin_within_the_budget(tmp_path):
    received = []
    async with running(tmp_path, replies(), received) as runtime:
        notes = runtime.plugins.plugins['notes'].instance
        result = await turn(runtime)
        [asked] = notes.requests
        assert (asked.scene, asked.persona, asked.turn_id, asked.recap, asked.tasks, asked.budget_chars) == (
            SCENE, 'management-fixture', result['turn_id'], None, (), 1500)
        assert [plain_text(message) for message in asked.messages] == [
            plain_text(parse_message(incoming(), own_message_ids=set()))]
        state = received[0][2]['messages'][-1]['content']
        recalled = json.loads(state.split('<相关长期记忆>\n')[1].split('\n</相关长期记忆>')[0])
        assert recalled['backend'] == 'plugin:notes'
        assert [(item['scope'], item['path'], item['truncated']) for item in recalled['items']] == [
            ('plugin:notes', '约定', False), ('plugin:notes', '原话', False), ('plugin:notes', '长记录', True)]
        assert sum(len(item['content']) for item in recalled['items']) == 1500
        # Both model requests of the turn carry the same recall.
        assert received[1][2]['messages'][-1]['content'].count('周六下午三点在东门集合') == 1
        shown = read_turn(runtime.store, SCENE, result['turn_id'])['recall']
        assert [item['path'] for item in shown] == ['约定', '原话', '长记录']


@pytest.mark.asyncio
async def test_a_failing_plugin_recall_is_recorded_and_the_turn_goes_on(tmp_path):
    received = []
    async with running(tmp_path, replies(), received) as runtime:
        runtime.plugins.plugins['notes'].instance.mode = 'fail'
        await turn(runtime)
        assert '<相关长期记忆>' not in received[0][2]['messages'][-1]['content']
        errors = list(runtime.plugins.plugins['notes'].errors)
        assert [(item['where'], item['error']) for item in errors] == [('自动召回', 'RuntimeError: 索引损坏')]
        assert runtime.plugins.plugins['notes'].status == 'running'


@pytest.mark.asyncio
async def test_recall_that_hangs_or_returns_other_values_fails_only_the_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_host, 'RECALL_SECONDS', .1)
    base = tmp_path / 'personal'
    base.mkdir()
    notes_package(base)
    host = PluginHost(load_host_config(_root(tmp_path, {'paths': [str(base)], 'notes': {}}, ['notes'])), core_tools=CORE)
    await host.start()
    try:
        notes = host.plugins['notes'].instance
        notes.mode = 'slow'
        async with asyncio.timeout(3):
            with pytest.raises(RuntimeError, match='自动召回超过 0.1 秒未返回'):
                await host.recall('notes', request())
        notes.mode = 'wrong'
        with pytest.raises(RuntimeError, match='RecallBlock'):
            await host.recall('notes', request())
        with pytest.raises(PermissionError, match='未在场景'):
            await host.recall('notes', request(scene='onebot:private:80002'))
        assert host.plugins['notes'].status == 'running'
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_a_process_plugin_receives_the_request_and_returns_blocks(tmp_path):
    base = tmp_path / 'personal'
    base.mkdir()
    notes_package(base, process=True)
    host = PluginHost(load_host_config(_root(tmp_path, {'paths': [str(base)], 'notes': {}}, ['notes'])), core_tools=CORE)
    await host.start()
    try:
        items = await host.recall('notes', request())
    finally:
        await host.close()
    assert [(item['path'], item['content'][:12]) for item in items] == [
        ('约定', '周六下午三点在东门集合'), ('原话', '秋游几点集合'), ('长记录', '长' * 12)]
    assert sum(len(item['content']) for item in items) == 300


@pytest.mark.parametrize('field', ['memory_plugin', 'recap_plugin'])
def test_memory_plugins_must_be_enabled_in_the_scene(tmp_path, field):
    root = _root(tmp_path, {'sample': {}}, [])
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['scenes'][SCENE][field] = 'sample'
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match=f"{field} must be one of this scene's plugins"):
        load_host_config(root)


@pytest.mark.asyncio
async def test_the_local_harness_runs_recall_on_added_messages(tmp_path):
    from len_bot.plugin_testing import PluginTest
    notes_package(tmp_path)
    async with PluginTest(tmp_path / 'notes') as bot:
        bot.add_message('第一条')
        bot.add_message('第二条')
        items = await bot.recall(budget_chars=40)
    assert [(item['path'], item['content']) for item in items] == [
        ('约定', '周六下午三点在东门集合'), ('原话', '第一条 / 第二条'), ('长记录', '长' * 20)]
