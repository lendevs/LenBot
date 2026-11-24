"""Candidate configuration is published with its source through panel HTTP operations."""

import asyncio
from io import BytesIO
import json
from pathlib import Path
import zipfile

import httpx

from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.memory.service import open_memory
from len_bot.next.panel.app import create_app
from len_bot.next.panel.setup import FirstSetup, initialize
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store


SAMPLE = Path(__file__).parent / 'fixtures/plugins/sample'


def package(version, *, text_value=False):
    manifest = (SAMPLE / 'plugin.toml').read_text().replace('version = "1.0.0"', f'version = "{version}"')
    if text_value:
        manifest = manifest.replace('type = "boolean"', 'type = "string"').replace('default = true', 'default = "brief"')
    content = BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        archive.writestr('plugin.toml', manifest)
        archive.writestr('__init__.py', (SAMPLE / '__init__.py').read_bytes())
    return content.getvalue()


def test_candidate_cancel_disable_apply_and_rollback_preserve_matching_config(tmp_path):
    binding = {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 16000}
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
        'compaction': {'input_tokens': 2000}, 'mind': binding, 'scene': 'onebot:group:80001',
        'panel_port': 8088, 'username': 'fixture', 'password': 'synthetic-password',
    })))
    # Rules switched off for another plugin survive operations on this one.
    raw = json.loads((tmp_path / 'lenbot.config.json').read_text())
    raw['plugins']['disabled_rules'] = {'other': ['/签到']}
    (tmp_path / 'lenbot.config.json').write_text(json.dumps(raw, ensure_ascii=False))
    config = load_host_config(tmp_path)

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
                scene = config.scene_config('onebot:group:80001')
                runtime = NetworkRuntime(config, [(scene, load_persona(scene.persona))], store, mind, memory=memory)
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    assert (await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'synthetic-password'})).status_code == 200
                    endpoint = '/api/host/plugins/sample'

                    async def upload(version, *, text_value=False):
                        result = await client.post('/api/host/plugins/zip', files={'file': ('sample.zip', package(version, text_value=text_value))})
                        assert result.status_code == 200, result.text

                    async def configure(values, enabled=True):
                        result = await client.put(endpoint, json={'enabled': enabled, 'config': values})
                        assert result.status_code == 200, result.text

                    async def operate(action):
                        result = await client.post(endpoint + '/' + action)
                        assert result.status_code == 200, result.text
                        return result.json()

                    loose = BytesIO()
                    with zipfile.ZipFile(loose, 'w') as archive:
                        archive.writestr('sample/README.md', '说明')
                    refused = await client.post('/api/host/plugins/zip', files={'file': ('sample.zip', loose.getvalue())})
                    assert refused.status_code >= 400
                    assert '没有 plugin.toml 和 __init__.py' in refused.json()['detail']['message']
                    await upload('1.0.0')
                    # The new plugin waits disabled for apply; the panel does not ask for a restart.
                    assert (await client.get('/api/host/plugins')).json()['restart_required'] is False
                    await configure({'show_details': False})
                    applied = await operate('apply')
                    assert applied['restart_required'] is False
                    assert runtime.config.plugins.disabled_rules == {'other': ['/签到']}
                    await upload('2.0.0', text_value=True)
                    await configure({'show_details': 'expanded'})
                    assert load_host_config(tmp_path).plugins.configured['sample'] == {'show_details': False}
                    await operate('cancel')
                    assert load_host_config(tmp_path).plugins.configured['sample'] == {'show_details': False}
                    await upload('2.0.0', text_value=True)
                    await configure({'show_details': 'expanded'})
                    await configure({}, enabled=False)
                    applied = await operate('apply')
                    assert 'sample' in applied['saved']['disabled']
                    assert load_host_config(tmp_path).plugins.configured['sample'] == {'show_details': 'expanded'}
                    await upload('3.0.0', text_value=True)
                    await operate('apply')
                    await operate('rollback')
                    saved = load_host_config(tmp_path)
                    assert saved.plugins.configured['sample'] == {'show_details': 'expanded'}
                    assert 'sample' in saved.plugins.disabled
                if runtime.plugins is not None:
                    await runtime.plugins.close()

    asyncio.run(run())


def test_a_plugin_saving_its_own_settings_writes_the_root_file_without_a_restart(tmp_path):
    binding = {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 16000}
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
        'compaction': {'input_tokens': 2000}, 'mind': binding, 'scene': 'onebot:group:80001',
        'panel_port': 8088, 'username': 'fixture', 'password': 'synthetic-password',
    })))
    config = load_host_config(tmp_path)
    manifest = (SAMPLE / 'plugin.toml').read_text().replace(
        'interface = 1\n', 'interface = 1\npermissions = ["configure"]\n', 1)
    content = BytesIO()
    plugin_source = '''from len_bot.plugin import Plugin, tool

class Sample(Plugin):
    @tool('sample_lookup', '查询示例', summary='查询示例')
    async def lookup(self, ctx):
        return {'enabled': True}

    def unavailable_tools(self, scene):
        return {'sample_lookup': '等待开启'} if self.ctx.config['show_details'] else {}
'''
    with zipfile.ZipFile(content, 'w') as archive:
        archive.writestr('plugin.toml', manifest)
        archive.writestr('__init__.py', plugin_source)

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
                scene = config.scene_config('onebot:group:80001')
                runtime = NetworkRuntime(config, [(scene, load_persona(scene.persona))], store, mind, memory=memory)
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    assert (await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'synthetic-password'})).status_code == 200
                    assert (await client.post('/api/host/plugins/zip', files={'file': ('sample.zip', content.getvalue())})).status_code == 200
                    assert (await client.put('/api/host/plugins/sample', json={'enabled': True, 'config': {}})).status_code == 200
                    assert (await client.post('/api/host/plugins/sample/apply')).status_code == 200
                    await runtime.plugins.start()
                    assert (await client.put('/api/host/scenes/onebot:group:80001/plugins',
                                             json={'plugins': ['sample'], 'memory_plugin': None,
                                                   'recap_plugin': None})).status_code == 200
                    assert 'sample_lookup' not in runtime.chats[scene.scene].toolset.external
                    values = await runtime.plugins.update_config('sample', {'show_details': False})
                    assert 'sample_lookup' in runtime.chats[scene.scene].toolset.external
                    assert values == {'show_details': False}
                    assert runtime.plugins.plugins['sample'].context.config == {'show_details': False}
                    assert load_host_config(tmp_path).plugins.configured['sample'] == {'show_details': False}
                    snapshot = (await client.get('/api/host/plugins')).json()
                    assert snapshot['restart_required'] is False
                    await runtime.plugins.update_config('sample', {'show_details': True})
                    assert 'sample_lookup' not in runtime.chats[scene.scene].toolset.external
                if runtime.plugins is not None:
                    await runtime.plugins.close()

    asyncio.run(run())


def test_plugin_panel_enhancements_candidate_apply_rules_and_batch_scenes(tmp_path):
    binding = {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 16000}
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
        'compaction': {'input_tokens': 2000}, 'mind': binding, 'scene': 'onebot:group:80001',
        'panel_port': 8088, 'username': 'fixture', 'password': 'synthetic-password',
    })))
    raw = json.loads((tmp_path / 'lenbot.config.json').read_text())
    raw['telegram'] = {'bot_id': 'telegram:7001', 'bot_token': '7001:' + 'T' * 35}
    raw['scenes']['onebot:group:80002'] = {'persona': raw['scenes']['onebot:group:80001']['persona']}
    raw['scenes']['telegram:group:-100123'] = {'persona': raw['scenes']['onebot:group:80001']['persona']}
    (tmp_path / 'lenbot.config.json').write_text(json.dumps(raw, ensure_ascii=False))
    config = load_host_config(tmp_path)

    def build_zip(version: str, *, title: str | None = '示例插件', data_version: int = 1,
                  permissions: str = '["send"]', chat_platforms: str = '["onebot"]',
                  dependencies: str = '[]') -> bytes:
        manifest_lines = [
            'name = "sample"',
            *([] if title is None else [f'title = "{title}"']),
            f'version = "{version}"',
            'interface = 1',
            f'data_version = {data_version}',
            'requires_lenbot = ">=0.2,<1"',
            'requires_python = ">=3.13"',
            'platforms = ["linux", "darwin", "win32"]',
            'reload = "plugin"',
            'authors = ["LEN5010"]',
            'license = "AGPL-3.0-only"',
            'description = "全栈面板测试插件"',
            f'permissions = {permissions}',
            f'chat_platforms = {chat_platforms}',
            f'dependencies = {dependencies}',
            '',
            '[config.show_details]',
            'type = "boolean"',
            'description = "是否显示详细回复"',
            'default = true',
        ]
        source = '''from len_bot.plugin import Plugin, RecallBlock, command, fullmatch, regex, recall, compact, tool

class Sample(Plugin):
    @command("示例", "示例命令")
    async def cmd(self, ctx, args):
        return "ok"

    @fullmatch("今日直播", "日历")
    async def today(self, ctx):
        return "ok"

    @regex(r"查看 (?P<name>.+)", "正则查询", priority=5)
    async def query(self, ctx, match):
        return "ok"

    @tool("sample_tool", "示例工具")
    async def run_tool(self, ctx) -> str:
        return "ok"

    def unavailable_tools(self, scene):
        return {} if self.ctx.config["show_details"] else {"sample_tool": "详细模式未开启"}

    @recall()
    async def remember(self, request):
        return [RecallBlock("记录", "内容")]

    @compact()
    async def summarize(self, request):
        return "摘要"
'''
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr('plugin.toml', '\n'.join(manifest_lines) + '\n')
            archive.writestr('__init__.py', source)
        return buf.getvalue()

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
                scenes = [(config.scene_config(scene), load_persona(config.scenes[scene].persona))
                          for scene in config.scenes]
                runtime = NetworkRuntime(config, scenes, store, mind, memory=memory)
                runtime.accepting = True
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    assert (await client.post('/api/auth/login', json={
                        'username': 'fixture', 'password': 'synthetic-password'})).status_code == 200

                    # 1. Upload first candidate -> installed_manifest is None; batch scenes rejected before apply.
                    uploaded = await client.post('/api/host/plugins/zip',
                                                 files={'file': ('sample.zip', build_zip('1.0.0'))})
                    assert uploaded.status_code == 200, uploaded.text
                    snap = uploaded.json()
                    cand = snap['available']['sample'][0]
                    assert cand['title'] == '示例插件' and cand['data_version'] == 1
                    assert cand['installed_manifest'] is None
                    assert 'group_digest' in snap['catalog_entries']

                    uninstalled = await client.put('/api/host/plugins/sample/scenes',
                                                   json={'scenes': ['onebot:group:80001']})
                    assert uninstalled.status_code == 422 and '尚未应用源码' in uninstalled.text

                    # 2. Candidate parameter reading tolerates missing configured entry (no KeyError / AttributeError).
                    saved_raw = json.loads((tmp_path / 'lenbot.config.json').read_text())
                    saved_raw['plugins'].pop('sample', None)
                    saved_raw['plugins']['disabled'] = []
                    (tmp_path / 'lenbot.config.json').write_text(json.dumps(saved_raw, ensure_ascii=False))

                    # 3. One-step save + apply_candidate=True + disabled_rules.
                    applied = await client.put('/api/host/plugins/sample', json={
                        'enabled': True, 'config': {'show_details': False},
                        'apply_candidate': True, 'disabled_rules': ['/示例', '今日直播'],
                    })
                    assert applied.status_code == 200, applied.text
                    body = applied.json()
                    assert body['operation'] == {'name': 'sample', 'restart_required': False,
                                                 'candidate_config_saved': True}
                    assert body['restart_required'] is False
                    assert body['saved']['disabled_rules'] == {'sample': ['/示例', '今日直播']}
                    running_sample = next(item for item in body['running']['plugins'] if item['name'] == 'sample')
                    assert running_sample['title'] == '示例插件'
                    assert running_sample['disabled_rules'] == ['/示例', '今日直播']
                    assert running_sample['commands'] == [{'name': '示例', 'description': '示例命令', 'disabled': True}]
                    assert running_sample['rules'] == [
                        {'kind': 'fullmatch', 'pattern': '今日直播', 'description': '日历', 'disabled': True},
                        {'kind': 'regex', 'pattern': r'查看 (?P<name>.+)', 'description': '正则查询',
                         'priority': 5, 'disabled': False},
                    ]
                    assert running_sample['unavailable_tools'] == {}

                    # 4. Batch scenes toggle + chat_platforms check + memory_plugin/recap_plugin cleanup.
                    bad_dup = await client.put('/api/host/plugins/sample/scenes',
                                               json={'scenes': ['onebot:group:80001', 'onebot:group:80001']})
                    assert bad_dup.status_code == 422
                    bad_unknown = await client.put('/api/host/plugins/sample/scenes',
                                                   json={'scenes': ['onebot:group:99999']})
                    assert bad_unknown.status_code == 422
                    bad_platform = await client.put('/api/host/plugins/sample/scenes',
                                                    json={'scenes': ['telegram:group:-100123']})
                    assert bad_platform.status_code == 422 and 'onebot' in bad_platform.text

                    enabled_scenes = await client.put('/api/host/plugins/sample/scenes',
                                                      json={'scenes': ['onebot:group:80001', 'onebot:group:80002']})
                    assert enabled_scenes.status_code == 200, enabled_scenes.text
                    snap = enabled_scenes.json()
                    assert snap['restart_required'] is False
                    assert 'sample' in snap['scenes']['onebot:group:80001']['running']
                    assert 'sample' in snap['scenes']['onebot:group:80002']['running']
                    running_sample = next(item for item in snap['running']['plugins'] if item['name'] == 'sample')
                    assert running_sample['unavailable_tools'] == {'sample_tool': '详细模式未开启'}

                    # Bind memory_plugin & recap_plugin on group 80001, then remove 80001 via batch scenes.
                    bound = await client.put('/api/host/scenes/onebot:group:80001/plugins', json={
                        'plugins': ['sample'], 'memory_plugin': 'sample', 'recap_plugin': 'sample',
                    })
                    assert bound.status_code == 200, bound.text
                    removed = await client.put('/api/host/plugins/sample/scenes',
                                               json={'scenes': ['onebot:group:80002']})
                    assert removed.status_code == 200, removed.text
                    snap = removed.json()
                    assert snap['restart_required'] is False
                    assert snap['scenes']['onebot:group:80001']['saved'] == []
                    assert snap['scenes']['onebot:group:80001']['memory_plugin'] == {'saved': None, 'running': None}
                    assert snap['scenes']['onebot:group:80001']['recap_plugin'] == {'saved': None, 'running': None}
                    assert snap['scenes']['onebot:group:80002']['running'] == ['sample']

                    # 5. Non-candidate disabled_rules update preserves config when config is omitted,
                    # and empty list cleans root config key.
                    toggled = await client.put('/api/host/plugins/sample', json={
                        'enabled': True, 'disabled_rules': ['/示例'],
                    })
                    assert toggled.status_code == 200, toggled.text
                    assert load_host_config(tmp_path).plugins.configured['sample'] == {'show_details': False}
                    assert toggled.json()['saved']['disabled_rules'] == {'sample': ['/示例']}

                    cleared = await client.put('/api/host/plugins/sample', json={
                        'enabled': True, 'config': {'show_details': True}, 'disabled_rules': [],
                    })
                    assert cleared.status_code == 200, cleared.text
                    snap = cleared.json()
                    assert snap['restart_required'] is False
                    assert snap['saved']['disabled_rules'] == {}
                    assert 'disabled_rules' not in json.loads((tmp_path / 'lenbot.config.json').read_text())['plugins']
                    running_sample = next(item for item in snap['running']['plugins'] if item['name'] == 'sample')
                    assert running_sample['disabled_rules'] == []
                    assert running_sample['commands'] == [{'name': '示例', 'description': '示例命令', 'disabled': False}]
                    assert running_sample['unavailable_tools'] == {}

                    # 6. Uploading a v2 candidate attaches installed_manifest of v1.
                    v2 = await client.post('/api/host/plugins/zip', files={'file': (
                        'sample.zip', build_zip('2.0.0', data_version=2, permissions='["send", "history"]',
                                                chat_platforms='["onebot", "telegram"]'))})
                    assert v2.status_code == 200, v2.text
                    cand2 = v2.json()['available']['sample'][0]
                    assert cand2['version'] == '2.0.0' and cand2['data_version'] == 2
                    assert cand2['installed_manifest'] == {
                        'version': '1.0.0',
                        'data_version': 1,
                        'permissions': [{'name': 'send', 'title': '在启用的群内发送消息'}],
                        'chat_platforms': ['onebot'],
                        'dependencies': [],
                    }
                if runtime.plugins is not None:
                    await runtime.plugins.close()

    asyncio.run(run())
