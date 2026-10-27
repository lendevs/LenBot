"""A persona package's own versions of the framework expression rules."""
import asyncio
import json

import httpx

from len_bot.next.chat.context import build_system
from len_bot.next.config import load_host_config
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel
from len_bot.next.panel.app import create_app
from len_bot.next.panel.setup import FirstSetup, initialize
from len_bot.next.persona.packages import export_package, import_package
from len_bot.next.persona.profile import load_persona
from len_bot.next.prompt_files import bundled
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_next_persona_permissions import _config, _package

SCENE = 'onebot:group:80001'


def test_framework_rules_apply_until_the_package_brings_its_own(tmp_path):
    package = _package(tmp_path, 'plain', tools=['say'], documents={})
    config = _config(tmp_path / 'instance', package)
    framework = build_system(config, load_persona(package), [], platform=False)
    assert bundled('next_chat_examples.md') in framework
    assert '长短看这次需要' in framework

    (package / 'expression_principles.md').write_text('$name 说话只用短句，价格写成 $5 这样。\n', encoding='utf-8')
    (package / 'chat_examples.md').write_text('<chat_examples>\n- 有人问价格：先说数字。\n</chat_examples>\n',
                                              encoding='utf-8')
    (package / 'response_choice.md').write_text('   \n', encoding='utf-8')
    persona = load_persona(package)
    assert set(persona.expression) == {'expression_principles.md', 'chat_examples.md'}
    own = build_system(config, persona, [], platform=False)
    assert '合成角色plain 说话只用短句，价格写成 $5 这样。' in own
    assert '有人问价格：先说数字。' in own
    assert '长短看这次需要' not in own and bundled('next_chat_examples.md') not in own
    # The blank file falls back to the framework's version.
    assert '开口之前，先站在你自己的位置想' in own


def test_expression_files_travel_with_the_package(tmp_path):
    package = _package(tmp_path / 'source', 'travel', tools='all', documents={})
    (package / 'response_choice.md').write_text('先判断是不是在问我。\n', encoding='utf-8')
    data = export_package(package)
    (tmp_path / 'instance').mkdir()
    result = import_package(tmp_path / 'instance', 'arrived', data)
    assert load_persona(tmp_path / 'instance/personas/arrived').expression == {'response_choice.md': '先判断是不是在问我。\n'}
    assert result['persona']['id'] == 'travel'


def test_files_page_edits_and_clears_expression_files(tmp_path):
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC', 'delivery': 'simulated',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
        'compaction': {'input_tokens': 6000}, 'mind': {'provider': 'primary', 'model': 'fixture',
                                                       'context_window_tokens': 16000},
        'scene': SCENE, 'persona_id': 'fixture', 'persona_name': '合成角色', 'brief': '合成资料',
        'voice_text': '简短', 'boundaries': '', 'panel_port': 8088, 'username': 'fixture',
        'password': 'synthetic-password',
    })))
    config = load_host_config(tmp_path)
    package = tmp_path / 'personas/fixture'
    (package / 'examples.yaml').write_text('- {context: 群友问在吗, line: 在的}\n- {context: 群友道晚安, line: 晚安}\n',
                                           encoding='utf-8')
    metadata = (package / 'persona.yaml').read_text(encoding='utf-8').replace(
        'styles: []', 'styles:\n- {name: 慢慢说, weight: 1.0, note: 句子短一点}')
    (package / 'persona.yaml').write_text(metadata, encoding='utf-8')

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(package))], store, mind,
                                         memory=memory)
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='http://testserver') as client:
                    url = '/api/host/personas/fixture/files/chat_examples.md'
                    assert (await client.put(url, json={'directory': str(package), 'content': 'x'})).status_code == 401
                    assert (await client.post('/api/auth/login', json={'username': 'fixture',
                                                                       'password': 'synthetic-password'})).status_code == 200
                    files = (await client.get('/api/host/personas/fixture/files')).json()
                    assert files['saved']['chat_examples.md'] == ''
                    assert files['defaults']['chat_examples.md'] == bundled('next_chat_examples.md')

                    saved = await client.put(url, json={'directory': str(package),
                                                        'content': '<chat_examples>\n- 合成情境。\n</chat_examples>\n'})
                    assert saved.status_code == 200, saved.text
                    assert saved.json()['saved']['chat_examples.md'].startswith('<chat_examples>')
                    assert '合成情境' in runtime.chats[SCENE].persona.expression['chat_examples.md']

                    preview = await client.get('/api/host/personas/fixture/preview', params={'scene': SCENE})
                    assert preview.status_code == 200, preview.text
                    body = preview.json()
                    assert [item['name'] for item in body['sections']] == [
                        'character', 'response_choice.md', 'expression_principles.md', 'chat_examples.md']
                    assert [item['own'] for item in body['sections']][1:] == [False, False, True]
                    assert '合成资料' in body['sections'][0]['text'] and '合成情境' in body['sections'][3]['text']
                    assert body['examples'] == 2 and body['styles'][0]['name'] == '慢慢说'
                    assert '名称：慢慢说' in body['style']
                    assert (await client.get('/api/host/personas/fixture/preview',
                                             params={'scene': 'onebot:group:1'})).status_code == 422
                    bare = (await client.get('/api/host/personas/fixture/preview')).json()
                    assert bare['scene'] is None and '<本场景角色补充>' not in bare['sections'][0]['text']

                    cleared = await client.put(url, json={'directory': str(package), 'content': '  \n'})
                    assert cleared.status_code == 200, cleared.text
                    assert not (package / 'chat_examples.md').exists()
                    assert cleared.json()['saved']['chat_examples.md'] == ''
                    assert runtime.chats[SCENE].persona.expression == {}
    asyncio.run(run())
