"""The market endpoints annotate the plugin catalog with what this host has and can load."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading

import httpx

from len_bot.next.config import load_host_config
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel
from len_bot.next.panel.app import create_app
from len_bot.next.panel.setup import FirstSetup, initialize
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_next_host_plugin_candidates import package

SAMPLE = Path(__file__).parent / 'fixtures/plugins/sample'


ENTRIES = [
    {'name': 'sample', 'title': '示例', 'description': '测试用示例插件', 'authors': ['fixture'],
     'license': 'MIT', 'version': '1.2.0', 'interface': 1, 'requires_lenbot': '>=0.1', 'category': '工具',
     'capabilities': ['命令'], 'install': 'git', 'repository': 'https://example.invalid/sample.git'},
    {'name': 'weather', 'title': '天气', 'description': '查询城市天气', 'authors': ['fixture'],
     'license': 'MIT', 'version': '2.0.0', 'interface': 99, 'category': '生活',
     'install': 'git', 'repository': 'https://example.invalid/weather.git'},
    {'name': 'notes', 'title': '群笔记', 'description': '记录群里的约定', 'authors': ['fixture'],
     'license': 'MIT', 'version': '0.3.0', 'interface': 1, 'category': '工具',
     'install': 'git', 'repository': 'https://example.invalid/notes.git'},
]


class Catalog(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'version': 1, 'entries': ENTRIES}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@asynccontextmanager
async def market_client(tmp_path, server):
    binding = {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 16000}
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC', 'delivery': 'simulated',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
        'compaction': {'input_tokens': 2000}, 'mind': binding, 'scene': 'onebot:group:80001',
        'panel_port': 8088, 'username': 'fixture', 'password': 'synthetic-password',
    })))
    config = load_host_config(tmp_path)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
            scene = config.scene_config('onebot:group:80001')
            runtime = NetworkRuntime(config, [(scene, load_persona(scene.persona))], store, mind, memory=memory)
            app = create_app(config, runtime, root=tmp_path)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                assert (await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'synthetic-password'})).status_code == 200
                uploaded = await client.post('/api/host/plugins/zip', files={'file': ('sample.zip', package('1.0.0'))})
                assert uploaded.status_code == 200, uploaded.text
                assert (await client.post('/api/host/plugins/sample/apply')).status_code == 200
                url = f'http://127.0.0.1:{server.server_port}/catalog.json'
                assert (await client.put('/api/host/plugin-catalog', json={'url': url})).status_code == 200
                assert (await client.post('/api/host/plugin-catalog/refresh')).status_code == 200
                yield client


@contextmanager
def catalog_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Catalog)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def test_market_lists_filters_and_guards_installation(tmp_path):
    async def run(server):
        async with market_client(tmp_path, server) as client:
            listed = (await client.get('/api/host/plugin-market')).json()
            assert listed['categories'] == ['工具', '生活'] and listed['total'] == 3
            view = {item['name']: item for item in listed['entries']}
            assert view['sample']['installed'] and view['sample']['installed_version'] == '1.0.0'
            assert view['sample']['update_available'] and view['sample']['compatible']
            assert not view['notes']['installed'] and not view['notes']['update_available']
            assert not view['weather']['compatible'] and '99' in view['weather']['incompatible_reason']

            tools = (await client.get('/api/host/plugin-market', params={'category': '工具', 'query': '约定'})).json()
            assert [item['name'] for item in tools['entries']] == ['notes'] and tools['total'] == 3
            assert (await client.get('/api/host/plugin-market/notes')).json()['version'] == '0.3.0'
            assert (await client.get('/api/host/plugin-market/missing')).status_code == 404

            installed = await client.post('/api/host/plugin-market/sample/install')
            assert installed.status_code == 409 and '更新' in installed.json()['detail']
            incompatible = await client.post('/api/host/plugin-market/weather/install')
            assert incompatible.status_code == 422 and '接口版本' in incompatible.json()['detail']

            status = (await client.get('/api/host/plugins/health')).json()['plugins']
            assert [item['name'] for item in status] == ['sample']
            assert set(status[0]['health']) == {'level', 'errors_last_hour', 'failing', 'last_error_at'}

    with catalog_server() as server:
        asyncio.run(run(server))


def git_repository(path, name):
    """A local repository whose plugin.toml names ``name``; reached through an https URL rewrite."""
    path.mkdir(parents=True)
    manifest = (SAMPLE / 'plugin.toml').read_text(encoding='utf-8').replace('name = "sample"', f'name = "{name}"')
    (path / 'plugin.toml').write_text(manifest, encoding='utf-8')
    (path / '__init__.py').write_bytes((SAMPLE / '__init__.py').read_bytes())
    for command in (['init', '-q', '-b', 'main'], ['add', '.'],
                    ['-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', name]):
        subprocess.run(['git', *command], cwd=path, check=True)


def test_market_install_requires_the_manifest_to_be_the_catalog_entry(tmp_path, monkeypatch):
    repositories = tmp_path / 'repositories'
    git_repository(repositories / 'notes.git', 'sample_other')
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', f'url.{repositories.as_uri()}/.insteadOf')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'https://example.invalid/')
    root = tmp_path / 'instance'
    root.mkdir()

    async def run(server):
        async with market_client(root, server) as client:
            refused = await client.post('/api/host/plugin-market/notes/install')
            assert refused.status_code == 422, refused.text
            assert '仓库清单的插件名是 sample_other，不是 notes' in refused.json()['detail']
            assert not (root / 'plugins/.candidates/sample_other').exists()
            assert not list((root / 'plugins').glob('**/sample_other.json'))
            # The same entry installs once its repository holds the plugin it names.
            fixed = repositories / 'notes.git'
            (fixed / 'plugin.toml').write_text((fixed / 'plugin.toml').read_text(encoding='utf-8')
                                               .replace('sample_other', 'notes'), encoding='utf-8')
            subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '-q', '-am', 'notes'], cwd=fixed, check=True)
            installed = await client.post('/api/host/plugin-market/notes/install')
            assert installed.status_code == 200, installed.text
            assert installed.json()['operation']['name'] == 'notes'

    with catalog_server() as server:
        asyncio.run(run(server))
