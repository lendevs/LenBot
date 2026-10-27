"""While a plugin is a scene's memory, the native memory neither extracts that scene nor holds its originals.

Switching back to native starts extraction from that moment without the messages in between; retention
follows only the position the scene's current memory reports.
"""

import json
import time
from types import SimpleNamespace

import pytest

from len_bot.next.chat.upkeep import SessionUpkeep
from len_bot.next.config import load_host_config
from len_bot.next.memory.jobs import MemoryJobs
from len_bot.next.memory.service import open_memory
from len_bot.next.platform.messages import ChatMessage, Segment, Sender
from len_bot.next.plugins.store import PluginStore
from len_bot.next.runtime.retention import Retention
from len_bot.next.storage.store import Store
from test_next_plugins import _root
from test_plugin_recall import notes_package

GROUP, PRIVATE = 'onebot:group:80001', 'onebot:private:80002'


def configure(tmp_path):
    base = tmp_path / 'personal'
    base.mkdir()
    notes_package(base)
    root = _root(tmp_path, {'paths': [str(base)], 'notes': {}}, ['notes'])
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['memory'] = {'backend': 'local', 'local': {'directory': 'memory'}, 'ingest': {}}
    source['retention'] = {'message_days': {GROUP: 1, PRIVATE: 1}}
    source['scenes'][GROUP]['memory_plugin'] = 'notes'
    path.write_text(json.dumps(source))
    return load_host_config(root)


def receive(store: Store, scene: str, number: int, at: float) -> ChatMessage:
    message = ChatMessage(id=f'{scene}-{number}', platform='onebot', bot_id='onebot:90001', scene=scene,
                          platform_message_id=f'{scene}-{number}', sender=Sender('onebot:70001', '群友', None, None),
                          time=at, segments=[Segment('text', {'text': f'第 {number} 条'})], reply_to=None,
                          mentions_bot=False, is_self=False, send_status='received')
    store.enqueue(message, {}, at)
    return message


@pytest.mark.asyncio
async def test_native_extraction_skips_a_plugin_scene_and_restarts_from_the_switch_back(tmp_path):
    config = configure(tmp_path)
    with Store(config.database) as store:
        for number in range(3):
            receive(store, GROUP, number, time.time())
            receive(store, PRIVATE, number, time.time())
        async with open_memory(config, store) as memory:
            # A cursor left from before the group moved to the plugin.
            memory.jobs.initialize(GROUP, 0)
            upkeep = SessionUpkeep(config, store, None, memory=memory)
            assert upkeep.parts['memory'] == {PRIVATE}
            assert [row[0] for row in memory.jobs.db.execute('SELECT scene FROM memory_cursors')] == [PRIVATE]
            for number in range(3, 5):
                receive(store, GROUP, number, time.time())
            config.scenes[GROUP].memory_plugin = None
            upkeep = SessionUpkeep(config, store, None, memory=memory)
            assert upkeep.parts['memory'] == {GROUP, PRIVATE}
            assert memory.jobs.after(GROUP) == store.max_message_seq(GROUP)


def test_retention_follows_the_scene_memory_in_use(tmp_path):
    config = configure(tmp_path)
    old = time.time() - 3 * 86400
    with Store(config.database) as store, MemoryJobs(config.database.with_name(config.database.name + '.memory.sqlite3')) as jobs:
        group = [receive(store, GROUP, number, old) for number in range(5)]
        for number in range(5):
            receive(store, PRIVATE, number, old)
        for scene in (GROUP, PRIVATE):
            store.db.execute('INSERT INTO mind_sessions(scene,last_message_seq) VALUES (?,?)',
                             (scene, store.max_message_seq(scene)))
            # Both native cursors stand before every message.
            jobs.initialize(scene, 0)
        store.db.commit()
        retention = Retention(SimpleNamespace(config=config, store=store))

        def removable() -> int:
            return retention._batch(store, jobs, preview=True)['messages']

        # The plugin has not reported: only the native private scene holds its originals back.
        assert removable() == 4
        PluginStore(store).report_memory_progress(GROUP, 'notes', group[1].id)
        assert removable() == 2
        config.scenes[GROUP].memory_plugin = None
        assert removable() == 0


@pytest.mark.asyncio
async def test_only_the_scene_memory_plugin_reports_progress_and_it_never_moves_back(tmp_path):
    from len_bot.plugin_testing import PluginTest
    notes_package(tmp_path)
    async with PluginTest(tmp_path / 'notes', scenes=[GROUP, PRIVATE]) as bot:
        first, second = bot.add_message('甲'), bot.add_message('乙')
        bot.host.config.scenes[GROUP].memory_plugin = 'notes'
        ctx = bot.host.plugins['notes'].context
        store = PluginStore(bot.host.runtime.store)
        await ctx.report_memory_progress(GROUP, second.id)
        await ctx.report_memory_progress(GROUP, first.id)
        assert store.memory_progress(GROUP, 'notes') == bot.host.runtime.store.max_message_seq(GROUP)
        with pytest.raises(ValueError, match='没有消息'):
            await ctx.report_memory_progress(GROUP, 'missing')
        with pytest.raises(PermissionError, match='不是场景'):
            await ctx.report_memory_progress(PRIVATE, first.id)
