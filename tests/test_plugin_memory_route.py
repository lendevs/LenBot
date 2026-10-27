"""In a scene whose memory is a plugin, chat, plugins and task workers reach the same memory tool: the plugin's.

The native memory files stay readable through ``ctx.native_memory`` and are never written from there.
"""

import json

import pytest
from pydantic import ValidationError

from len_bot.next.chat.tools import task_data_tools
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
