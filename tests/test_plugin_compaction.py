"""A scene whose recap_plugin names a plugin gets its compaction recap from that plugin's @compact entry.

Native and plugin recaps go through the same commit; a failing or oversized plugin recap is recorded
on the plugin and the native recap takes that compaction; a role handover always uses the native one.
"""

from contextlib import asynccontextmanager
import json

import httpx
import pytest

from len_bot.next.chat.session import Chat
from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.plugins.host import PluginHost
from len_bot.next.storage.store import Store
from len_bot.plugin import CompactRequest
from test_model_failure_protocol import FIXTURE, instance
from test_next_panel_acts_as_owner import SCENE
from test_next_plugins import CORE, _copy_sample

NOTES = '''
from len_bot.plugin import Plugin, compact


class Notes(Plugin):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.requests = []
        self.reply = "插件回想：大家约好明天讨论连接恢复的报告。"

    @compact()
    async def fold(self, request):
        self.requests.append(request)
        if self.reply == "fail":
            raise RuntimeError("摘要服务不可用")
        return self.reply
'''
NATIVE = '原生回想：明天讨论报告。'


def notes_package(root, *, process=False):
    directory = _copy_sample(root / 'plugins', 'notes')
    if process:
        manifest = directory / 'plugin.toml'
        manifest.write_text(manifest.read_text().replace('description = ', 'isolation = "process"\ndescription = ', 1))
    (directory / '__init__.py').write_text(NOTES, encoding='utf-8')


def configure(root, *, process=False):
    instance(root)
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['plugins'] = {'paths': ['plugins'], 'notes': {}}
    source['scenes'][SCENE].update(plugins=['notes'], recap_plugin='notes')
    path.write_text(json.dumps(source))
    notes_package(root, process=process)
    return load_host_config(root)


@asynccontextmanager
async def chat_with_notes(root):
    config = configure(root)
    captured = []
    body = json.loads(FIXTURE.read_text())
    body['choices'][0]['message']['content'] = NATIVE

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    host = PluginHost(config, core_tools=CORE)
    await host.start()
    try:
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                await model._client.aclose()
                model._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='https://fixture.invalid/')
                chat = Chat(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona), store, model,
                            plugins=host)
                for content in ['明天讨论报告。' * 100, '报告主题是连接恢复。' * 100, '好的。']:
                    store.append(SCENE, {'role': 'user', 'content': content})
                store.save_discovered_tools(SCENE, ['schedule'])
                yield chat, host.plugins['notes'], store, captured
    finally:
        await host.close()


def session(store):
    return store.db.execute('SELECT compact_through,recap,discovered_tools FROM mind_sessions WHERE scene=?',
                            (SCENE,)).fetchone()


@pytest.mark.asyncio
async def test_the_scene_plugin_writes_the_recap_through_the_shared_commit(tmp_path):
    async with chat_with_notes(tmp_path) as (chat, notes, store, captured):
        result = await chat.compact_now()
        [asked] = notes.instance.requests
        assert (asked.scene, asked.persona, asked.turn_id, asked.budget_tokens) == (
            SCENE, 'synthetic-owner', result['turn_id'], 4096)
        assert '明天讨论报告' in asked.source and '报告主题是连接恢复' in asked.source
        assert result['recap'] == notes.instance.reply and not captured
        assert tuple(session(store)) == (result['compact_through'], notes.instance.reply, '[]')
        assert store.active_history(SCENE)[0] == notes.instance.reply


@pytest.mark.asyncio
@pytest.mark.parametrize('reply,error', [('fail', 'RuntimeError: 摘要服务不可用'),
                                         ('长' * 20000, 'ValueError: 回想估算 20000 token，超过预算 4096'),
                                         ('   ', 'TypeError: @compact 必须返回非空文字')])
async def test_a_failed_plugin_recap_is_recorded_and_the_native_recap_takes_over(tmp_path, reply, error):
    async with chat_with_notes(tmp_path) as (chat, notes, store, captured):
        notes.instance.reply = reply
        result = await chat.compact_now()
        assert result['recap'] == NATIVE and len(captured) == 1
        assert session(store)['recap'] == NATIVE
        assert [(item['where'], item['error']) for item in notes.errors] == [('压缩', error)]
        assert notes.status == 'running'


@pytest.mark.asyncio
async def test_a_role_handover_is_written_by_the_native_recap(tmp_path):
    async with chat_with_notes(tmp_path) as (chat, notes, store, captured):
        assert await chat.hand_over('合成角色', '新角色') == 'done'
        assert not notes.instance.requests and len(captured) == 1
        assert session(store)['recap'] == NATIVE


@pytest.mark.asyncio
async def test_a_process_plugin_answers_compaction(tmp_path):
    config = configure(tmp_path, process=True)
    host = PluginHost(config, core_tools=CORE)
    await host.start()
    try:
        recap = await host.compact('notes', CompactRequest(SCENE, 'role', 't1', '[{"role":"user"}]', 200))
    finally:
        await host.close()
    assert recap == '插件回想：大家约好明天讨论连接恢复的报告。'


@pytest.mark.asyncio
async def test_the_local_harness_runs_compaction_with_the_host_checks(tmp_path):
    from len_bot.plugin_testing import PluginTest
    notes_package(tmp_path)
    async with PluginTest(tmp_path / 'plugins/notes') as bot:
        assert await bot.compact('旧对话') == '插件回想：大家约好明天讨论连接恢复的报告。'
        with pytest.raises(RuntimeError, match='超过预算 5'):
            await bot.compact('旧对话', budget_tokens=5)
