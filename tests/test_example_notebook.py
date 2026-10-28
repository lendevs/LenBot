"""The example memory plugin in examples/plugins/notebook: notes from the chat, recall by shared wording,
the memory tool, and upkeep that starts when the plugin first serves a group and reports its progress."""

import json
from pathlib import Path

import pytest

from len_bot.plugin_testing import PluginTest
from len_bot.next.plugins.store import PluginStore

NOTEBOOK = Path(__file__).parents[1] / 'examples/plugins/notebook'
SCENE = 'onebot:group:80001'


async def call(bot, arguments, **options):
    return json.loads(await bot.memory(arguments, **options))


class Clock:
    def __init__(self):
        self.value = 1_000_000.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_the_memory_tool_keeps_notes_per_group():
    async with PluginTest(NOTEBOOK, scenes=[SCENE, 'onebot:group:80002'], memory=True) as bot:
        assert await call(bot, {'action': 'write', 'text': '小林周六下午三点在东门集合'}) == {'id': 1}
        await call(bot, {'action': 'write', 'text': '阿青不吃香菜'})
        assert await call(bot, {'action': 'search', 'query': '东门'}) == [{'id': 1, 'text': '小林周六下午三点在东门集合'}]
        assert await call(bot, {'action': 'list'}, scene='onebot:group:80002') == []
        assert await call(bot, {'action': 'delete', 'id': 1}) == {'deleted': 1}
        with pytest.raises(ValueError, match='没有笔记'):
            await bot.memory({'action': 'delete', 'id': 1})


@pytest.mark.asyncio
async def test_recall_returns_notes_sharing_wording_with_the_chat():
    async with PluginTest(NOTEBOOK, config={'recall_limit': 2}, memory=True) as bot:
        for text in ('小林周六下午三点在东门集合', '阿青不吃香菜', '读书会改到周日'):
            await bot.memory({'action': 'write', 'text': text})
        bot.add_message('周六几点在东门集合来着')
        items = await bot.recall()
        assert [(item['path'], item['content']) for item in items] == [('笔记 #1', '小林周六下午三点在东门集合')]


@pytest.mark.asyncio
async def test_upkeep_starts_when_first_serving_and_reports_what_it_read():
    clock = Clock()
    async with PluginTest(NOTEBOOK, config={'min_messages': 2}, memory=True, now=clock) as bot:
        bot.add_message('之前的消息不整理', timestamp=clock.value - 10)
        plugin = bot.host.plugins['notebook']
        prompts = []

        async def generate(name, scene, prompt, role, system):
            prompts.append((prompt, role))
            return '```json\n["小林周六下午三点在东门集合"]\n```'

        bot.host.generate = generate
        await bot.recall()
        clock.value += 60
        bot.add_message('周六下午三点东门集合', timestamp=clock.value - 30)
        last = bot.add_message('好的', timestamp=clock.value - 20)
        await plugin.instance.upkeep(plugin.context)
        [(prompt, role)] = prompts
        assert role == 'learner' and '周六下午三点东门集合' in prompt and '之前的消息' not in prompt
        assert await call(bot, {'action': 'list'}) == [{'id': 1, 'text': '小林周六下午三点在东门集合'}]
        store = bot.host.runtime.store
        assert PluginStore(store).memory_progress(SCENE, 'notebook') == store.db.execute(
            "SELECT seq FROM messages WHERE json_extract(body,'$.id')=?", (last.id,)).fetchone()[0]
        # Nothing new: no model call.
        clock.value += 60
        await plugin.instance.upkeep(plugin.context)
        assert len(prompts) == 1
