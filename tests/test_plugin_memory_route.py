"""In a scene whose memory is a plugin, chat, plugins and task workers reach the same memory tool: the plugin's.

The native memory files stay readable through ``ctx.native_memory`` and are never written from there.
"""

from copy import deepcopy
import json
import time

import pytest
from pydantic import ValidationError

from len_bot.next.chat.tools import task_data_tools
from test_plugin_memory_boundary import receive
from test_plugin_recall import SCENE, running

NOTEBOOK = '''
from len_bot.plugin import Invocation, Plugin, RecallBlock, memory_tool, recall


class Notes(Plugin):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.saved = []

    @recall()
    async def remember(self, request):
        return [RecallBlock("笔记", text) for text in self.saved]

    @memory_tool("读写本群笔记；note 写入一条，query 按文字检索。")
    async def notes(self, ctx: Invocation, query: str = "", note: str = "") -> str:
        if note:
            self.saved.append(note)
            return f"已记下 {ctx.scene}"
        return "笔记：" + " / ".join(item for item in self.saved if query in item)
'''
RECALL_ONLY = '''
from len_bot.plugin import Plugin, RecallBlock, recall


class Notes(Plugin):
    @recall()
    async def remember(self, request):
        return [RecallBlock("笔记", "无")]
'''


def definition(chat, name='memory'):
    return next((tool['function'] for tool in chat.toolset.tools if tool['function']['name'] == name), None)


@pytest.mark.asyncio
async def test_chat_plugins_and_tasks_reach_the_plugin_memory_tool(tmp_path):
    async with running(tmp_path, [], [], plugin=NOTEBOOK, tools=['say', 'memory']) as runtime:
        chat = runtime.chats[SCENE]
        tool = definition(chat)
        assert tool['description'] == '[插件 notes] 读写本群笔记；note 写入一条，query 按文字检索。'
        assert set(tool['parameters']['properties']) == {'query', 'note'}
        system = chat.context.system
        assert '本群的长期记忆由插件 notes 提供' in system and '后端是' not in system
        assert await chat.toolset.run_memory({'note': '周六东门集合'}) == f'已记下 {SCENE}'
        ctx = runtime.plugins.plugins['notes'].context
        assert await ctx.memory(SCENE, {'query': '东门'}) == '笔记：周六东门集合'
        with pytest.raises(ValidationError, match='query'):
            await ctx.memory(SCENE, {'query': 1})
        data = task_data_tools(chat.config, chat.persona, platform=False, memory=runtime.memory,
                               plugins=runtime.plugins)
        assert [item['description'] for item in data if item['name'] == 'memory'] == [tool['description']]
        # Another scene keeps the native memory tool.
        native = definition(runtime.chats['onebot:group:80002'])
        assert 'action' in native['parameters']['properties']


@pytest.mark.asyncio
async def test_native_files_stay_readable_and_are_never_written_through_the_plugin(tmp_path):
    async with running(tmp_path, [], [], plugin=NOTEBOOK, tools=['say', 'memory']) as runtime:
        ctx = runtime.plugins.plugins['notes'].context
        found = json.loads(await ctx.native_memory(SCENE, {'action': 'search', 'query': '集合'}))
        assert found is not None
        with pytest.raises(PermissionError, match='原生记忆只读'):
            await ctx.native_memory(SCENE, {'action': 'write', 'path': 'a.md', 'content': '新内容', 'reason': '测试'})


@pytest.mark.asyncio
async def test_without_a_plugin_memory_tool_the_scene_has_no_memory_tool(tmp_path):
    async with running(tmp_path, [], [], plugin=RECALL_ONLY, tools=['say', 'memory']) as runtime:
        chat = runtime.chats[SCENE]
        assert definition(chat) is None and 'memory' not in chat.toolset.allowed_tool_names
        with pytest.raises(PermissionError, match='未允许 memory'):
            await runtime.plugins.plugins['notes'].context.memory(SCENE, {'query': 'x'})


@pytest.mark.asyncio
async def test_the_local_harness_calls_the_memory_tool(tmp_path):
    from len_bot.plugin_testing import PluginTest
    from test_plugin_recall import notes_package
    notes_package(tmp_path, source=NOTEBOOK)
    async with PluginTest(tmp_path / 'notes') as bot:
        assert await bot.memory({'note': '甲'}) == f'已记下 {SCENE}'
        assert await bot.memory({'query': '甲'}) == '笔记：甲'


@pytest.mark.asyncio
async def test_the_panel_switches_the_group_memory_between_turns(tmp_path):
    import httpx
    from len_bot.next.panel.app import create_app
    async with running(tmp_path, [], [], plugin=NOTEBOOK, tools=['say', 'memory']) as runtime:
        runtime.accepting = True
        chat = runtime.chats[SCENE]
        app = create_app(runtime.config, runtime, root=tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            assert (await client.post('/api/auth/login', json={'username': 'operator',
                                                               'password': 'fixture-password'})).status_code == 200
            path = f'/api/host/scenes/{SCENE}/plugins'
            snapshot = (await client.get('/api/host/plugins')).json()
            assert snapshot['scenes'][SCENE]['memory_plugin'] == {'saved': 'notes', 'running': 'notes'}
            notes = next(item for item in snapshot['running']['plugins'] if item['name'] == 'notes')
            assert notes['memory_entries'] == ['recall', 'memory_tool']
            # Leaving the memory fields out would reset them, so they are required.
            assert (await client.put(path, json={'plugins': ['notes']})).status_code == 422
            refused = await client.put(path, json={'plugins': [], 'memory_plugin': 'notes', 'recap_plugin': None})
            assert refused.status_code == 422 and 'memory_plugin' in refused.text
            saved = await client.put(path, json={'plugins': ['notes'], 'memory_plugin': None, 'recap_plugin': 'notes'})
            assert saved.status_code == 200, saved.text
            body = saved.json()
            assert body['scenes'][SCENE]['memory_plugin'] == {'saved': None, 'running': None}
            assert body['scenes'][SCENE]['recap_plugin'] == {'saved': 'notes', 'running': 'notes'}
            assert body['restart_required'] is False
            assert 'action' in definition(chat)['parameters']['properties']
            assert '本群的长期记忆由插件 notes 提供' not in chat.context.system
            assert chat.config.recap_plugin == 'notes'
            # A plugin that is not running in the scene keeps the choice for the restart.
            runtime.plugins.plugins['notes'].status = 'failed'
            pending = (await client.put(path, json={'plugins': ['notes'], 'memory_plugin': 'notes',
                                                    'recap_plugin': 'notes'})).json()
            assert pending['scenes'][SCENE]['memory_plugin'] == {'saved': 'notes', 'running': None}
            assert pending['restart_required'] is True
            runtime.plugins.plugins['notes'].status = 'running'
            back = (await client.put(path, json={'plugins': ['notes'], 'memory_plugin': 'notes',
                                                 'recap_plugin': None})).json()
            assert back['scenes'][SCENE]['memory_plugin'] == {'saved': 'notes', 'running': 'notes'}
            assert back['restart_required'] is False
            assert set(definition(chat)['parameters']['properties']) == {'query', 'note'}
            assert '本群的长期记忆由插件 notes 提供' in chat.context.system and chat.config.recap_plugin is None
        scene = json.loads((tmp_path / 'lenbot.config.json').read_text())['scenes'][SCENE]
        assert scene['memory_plugin'] == 'notes' and 'recap_plugin' not in scene


@pytest.mark.asyncio
async def test_a_trial_of_a_plugin_memory_group_runs_on_native_memory_and_names_the_plugin(tmp_path):
    import httpx
    from len_bot.next.panel.app import create_app
    async with running(tmp_path, [], [], plugin=NOTEBOOK, tools=['say', 'memory']) as runtime:
        runtime.accepting = True
        app = create_app(runtime.config, runtime, root=tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            assert (await client.post('/api/auth/login', json={'username': 'operator',
                                                               'password': 'fixture-password'})).status_code == 200
            started = await client.post('/api/host/trials', json={'scene': SCENE})
            assert started.status_code == 200, started.text
            info = started.json()
            assert info['memory_plugin'] == 'notes' and info['memory'] == '独立空白本地记忆'
            trial = app.state.trials.records[info['id']]
            assert trial.config.memory_plugin is None and trial.config.plugins == []
            assert 'action' in definition(trial.session.chat)['parameters']['properties']
            listed, = (await client.get('/api/host/trials')).json()['items']
            assert listed['memory_plugin'] == 'notes'
            assert (await client.post(f"/api/host/trials/{info['id']}/stop")).status_code == 200
            # The marker follows the group's running setting after a live switch.
            saved = await client.put(f'/api/host/scenes/{SCENE}/plugins',
                                     json={'plugins': ['notes'], 'memory_plugin': None, 'recap_plugin': None})
            assert saved.status_code == 200, saved.text
            native = await client.post('/api/host/trials', json={'scene': SCENE})
            assert native.status_code == 200, native.text
            assert native.json()['memory_plugin'] is None
            assert (await client.post(f"/api/host/trials/{native.json()['id']}/stop")).status_code == 200


@pytest.mark.asyncio
async def test_a_live_switch_moves_native_extraction_as_a_restart_does(tmp_path):
    async with running(tmp_path, [], [], plugin=NOTEBOOK, tools=['say', 'memory'], upkeep=True) as runtime:
        store, ingestor = runtime.store, runtime.ingestor
        assert SCENE not in ingestor.scenes
        for number in range(3):
            receive(store, SCENE, number, time.time())
        saved = deepcopy(runtime.config)
        saved.scenes[SCENE].memory_plugin = None
        await runtime.scene_service.apply_memory(saved)
        # Native extraction starts from the switch; the messages before it are not extracted.
        assert SCENE in ingestor.scenes and ingestor.jobs.after(SCENE) == store.max_message_seq(SCENE)
        receive(store, SCENE, 3, time.time())
        saved.scenes[SCENE].memory_plugin = 'notes'
        await runtime.scene_service.apply_memory(saved)
        assert SCENE not in ingestor.scenes
        assert ingestor.jobs.db.execute('SELECT 1 FROM memory_cursors WHERE scene=?', (SCENE,)).fetchone() is None


@pytest.mark.asyncio
async def test_uninstalling_the_memory_plugin_returns_its_groups_to_native_memory(tmp_path):
    from io import BytesIO
    import zipfile

    import httpx
    from len_bot.next.config import load_host_config
    from len_bot.next.memory.service import open_memory
    from len_bot.next.models.client import ChatModel
    from len_bot.next.panel.app import create_app
    from len_bot.next.panel.setup import FirstSetup, initialize
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.runtime.network import NetworkRuntime
    from len_bot.next.storage.store import Store
    from test_next_host_plugin_candidates import SAMPLE

    binding = {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 16000}
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC', 'delivery': 'simulated',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
        'compaction': {'input_tokens': 2000}, 'mind': binding, 'scene': SCENE,
        'panel_port': 8088, 'username': 'fixture', 'password': 'synthetic-password',
    })))
    archive = BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('plugin.toml', (SAMPLE / 'plugin.toml').read_text().replace('name = "sample"', 'name = "notes"'))
        zipped.writestr('__init__.py', NOTEBOOK)
    config = load_host_config(tmp_path)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
            scene = config.scene_config(SCENE)
            runtime = NetworkRuntime(config, [(scene, load_persona(scene.persona))], store, mind, memory=memory)
            app = create_app(config, runtime, root=tmp_path)
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    assert (await client.post('/api/auth/login', json={'username': 'fixture',
                                                                       'password': 'synthetic-password'})).status_code == 200
                    for step in (client.post('/api/host/plugins/zip', files={'file': ('notes.zip', archive.getvalue())}),
                                 client.put('/api/host/plugins/notes', json={'enabled': True, 'config': {}}),
                                 client.post('/api/host/plugins/notes/apply'),
                                 client.put(f'/api/host/scenes/{SCENE}/plugins',
                                            json={'plugins': ['notes'], 'memory_plugin': 'notes', 'recap_plugin': 'notes'})):
                        result = await step
                        assert result.status_code == 200, result.text
                    assert runtime.config.scenes[SCENE].memory_plugin == 'notes'
                    removed = await client.delete('/api/host/plugins/notes')
                    assert removed.status_code == 200, removed.text
                    assert removed.json()['restart_required'] is False
                saved = load_host_config(tmp_path).scenes[SCENE]
                assert (saved.plugins, saved.memory_plugin, saved.recap_plugin) == ([], None, None)
                running_scene = runtime.config.scenes[SCENE]
                assert (running_scene.memory_plugin, running_scene.recap_plugin) == (None, None)
                assert runtime.chats[SCENE].config.memory_plugin is None
            finally:
                if runtime.plugins is not None:
                    await runtime.plugins.close()
