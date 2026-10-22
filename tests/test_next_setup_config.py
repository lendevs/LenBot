"""First-run configuration validation, no production connections."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from len_bot.next.config import load_host_config
from len_bot.next.persona.profile import load_persona
from len_bot.next.panel.setup import create_setup_app
from len_bot.web.auth import verify_password


@pytest.mark.parametrize('voice_mode', ['direct'])
@pytest.mark.parametrize('default_persona', [False, True])
@pytest.mark.parametrize('embedding_mode', ['skip', 'primary', 'separate'])
def test_first_setup_validates_and_never_overwrites(tmp_path: Path, voice_mode: str, default_persona: bool, embedding_mode: str):
    body = {
        'bot_id':'onebot:90001','owners':['onebot:70001'],'timezone':'Asia/Shanghai','delivery':'simulated',
        'onebot':{'mode':'forward_ws','ws_url':'ws://127.0.0.1:9','access_token':'synthetic-token'},
        'provider':{'api':'openai-chat','base_url':'http://127.0.0.1:9/v1','api_key':'synthetic-secret'},
        'mind':{'provider':'primary','model':'fixture','context_window_tokens':8192},

        'voice_mode': voice_mode, 'compaction': {'input_tokens': 6000},
        'scene':'onebot:group:80001','persona_id':'fixture','persona_name':'合成角色','brief':'测试设定',
        'voice_text':'简短','boundaries':'合成场景','panel_port':8088,'username':'fixture',
        'password':'synthetic-password',
    }
    if embedding_mode != 'skip':
        body['embedding'] = {'model': 'synthetic-vector', 'dimensions': 4,
            'provider': None if embedding_mode == 'primary' else {
                'api': 'openai-embeddings', 'base_url': 'http://127.0.0.1:10/v1', 'api_key': 'synthetic-vector-key'}}
    else:
        body['embedding'] = None
    if default_persona:
        for name in ('persona_id', 'persona_name', 'brief', 'voice_text', 'boundaries'):
            del body[name]
    async def exercise():
        complete = asyncio.Event()
        app = create_setup_app(tmp_path, 'fixture-token', complete)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
            assert (await client.post('/api/setup', json=body)).status_code == 401
            client.headers['X-Setup-Token'] = 'fixture-token'
            invalid = await client.post('/api/setup', json={**body, 'scene':'invalid'})
            assert invalid.status_code == 422 and not (tmp_path/'lenbot.config.json').exists()
            invalid = await client.post('/api/setup', json={**body, 'password':42})
            assert invalid.status_code == 422 and 'synthetic-secret' not in invalid.text
            invalid = await client.post('/api/setup', json={**body, 'voice_mode':'unknown'})
            assert invalid.status_code == 422 and not (tmp_path/'lenbot.config.json').exists()
            response = await client.post('/api/setup', json=body)
            assert response.status_code == 200, response.text
            assert complete.is_set() and 'synthetic-secret' not in response.text
            cfg = load_host_config(tmp_path)
            assert cfg.delivery == 'simulated' and cfg.models.roles.mind.model == 'fixture'
            assert cfg.memory is not None
            if embedding_mode == 'skip':
                assert cfg.memory.local.embedding is None and set(cfg.models.providers) == {'primary'}
            else:
                binding = cfg.memory.local.embedding
                assert binding.model == 'synthetic-vector' and binding.dimensions == 4
                assert binding.provider == ('primary' if embedding_mode == 'primary' else 'vectors')
            assert cfg.scenes['onebot:group:80001'].voice_mode == voice_mode
            assert response.json()['voice_mode'] == voice_mode
            persona = load_persona(cfg.scenes['onebot:group:80001'].persona)
            if default_persona:
                assert persona.id == 'companion' and persona.name == '小然'
                assert persona.voice and persona.knowledge and persona.stickers
                assert persona.examples == []
                assert persona.skills == 'all' and '小然' in persona.aliases
            else:
                assert persona.name == '合成角色'
            assert verify_password(body['password'], cfg.panel.password_hash)
            before = (tmp_path/'lenbot.config.json').read_bytes()
            assert body['password'] not in before.decode()
            assert (await client.post('/api/setup', json=body)).status_code == 409
            assert (tmp_path/'lenbot.config.json').read_bytes() == before
    asyncio.run(exercise())


@pytest.mark.asyncio
async def test_setup_vector_probe_auth_and_embedding_protocol(tmp_path):
    from test_next_native_models import peer_server
    received = []
    response = b'{"data":[{"index":0,"embedding":[1,0,0,1]}]}'
    server = await peer_server([(200, 'application/json', response)], received)
    async with server:
        app = create_setup_app(tmp_path, 'fixture-token', asyncio.Event())
        body = {
            'provider': {'api': 'openai-embeddings', 'base_url': f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
                         'api_key': 'synthetic-vector-key'},
            'binding': {'provider': 'vectors', 'model': 'synthetic-vector', 'dimensions': 4},
        }
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
            assert (await client.post('/api/setup/embedding', json=body)).status_code == 401
            client.headers['X-Setup-Token'] = 'fixture-token'
            result = await client.post('/api/setup/embedding', json=body)
            assert result.status_code == 200, result.text
            assert result.json()['dimensions'] == 4
            assert not (tmp_path / 'lenbot.config.json').exists()
    assert len(received) == 1 and received[0][2]['model'] == 'synthetic-vector'


@pytest.mark.asyncio
async def test_setup_reads_account_from_onebot_before_configuration(tmp_path):
    from websockets.asyncio.server import serve

    requests = []

    async def peer(websocket):
        packet = json.loads(await websocket.recv())
        requests.append(packet)
        await websocket.send(json.dumps({'status': 'ok', 'retcode': 0,
                                         'data': {'user_id': 90001, 'nickname': '脱敏 Bot'},
                                         'echo': packet['echo']}))
        await websocket.wait_closed()

    async with serve(peer, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        app = create_setup_app(tmp_path, 'fixture-token', asyncio.Event())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
            body = {'onebot': {'mode': 'forward_ws', 'ws_url': f'ws://127.0.0.1:{port}'}}
            assert (await client.post('/api/setup/platform', json=body)).status_code == 401
            client.headers['X-Setup-Token'] = 'fixture-token'
            result = await client.post('/api/setup/platform', json=body)
            assert result.status_code == 200, result.text
            assert result.json() == {'bot_id': 'onebot:90001'}
    assert len(requests) == 1 and requests[0]['action'] == 'get_login_info'
    assert not (tmp_path / 'lenbot.config.json').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 429])
async def test_setup_model_probe_makes_one_request_and_returns_original_error(tmp_path, status):
    response = (Path(__file__).parent / 'fixtures/next/model/response-text.json').read_bytes()
    requests = []

    async def peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)
        requests.append(json.loads(await reader.readexactly(int(fields['Content-Length']))))
        body = response if status == 200 else b'{"error":{"message":"fixture provider rejected probe"}}'
        writer.write(f'HTTP/1.1 {status} Probe\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(peer, '127.0.0.1', 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        app = create_setup_app(tmp_path, 'fixture-token', asyncio.Event())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1',
                                     headers={'X-Setup-Token': 'fixture-token'}) as client:
            result = await client.post('/api/setup/model', json={
                'provider': {'api': 'openai-chat', 'base_url': f'http://127.0.0.1:{port}/v1', 'api_key': 'probe-fixture-key'},
                'mind': {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 8192},
            })
            if status == 200:
                assert result.status_code == 200, result.text
                assert result.json()['text'] == json.loads(response)['choices'][0]['message']['content']
            else:
                assert result.status_code == 422 and 'fixture provider rejected probe' in result.text
    assert len(requests) == 1 and requests[0]['model'] == 'fixture'
    assert not (tmp_path / 'lenbot.config.json').exists()


def test_first_setup_rejects_bad_account_before_creating_files(tmp_path):
    from pydantic import ValidationError
    from len_bot.next.panel.setup import FirstSetup, initialize
    source = json.loads((Path(__file__).parents[1] / 'deploy/current/first-setup.example.json').read_text())
    source.update(password='fixture-password', password_confirmation='fixture-password')
    for fields in ({'username': ' '}, {'username': ' leading'}, {'password': '        ', 'password_confirmation': '        '},
                   {'password_confirmation': 'different'}, {'password': 'short', 'password_confirmation': 'short'}):
        with pytest.raises(ValidationError):
            initialize(tmp_path, FirstSetup.model_validate({**source, **fields}))
        assert not (tmp_path/'lenbot.config.json').exists()
        assert not (tmp_path/'personas').exists()


@pytest.mark.asyncio
async def test_setup_official_plugins_are_optional_and_selected_sources_stay_disabled(tmp_path):
    from io import BytesIO
    import zipfile
    from len_bot.next.panel.setup import FirstSetup, initialize
    from len_bot.next.plugins.install import PluginInstaller
    body = json.loads((Path(__file__).parents[1] / 'deploy/current/first-setup.example.json').read_text())
    body['password'] = 'fixture-password'
    app = create_setup_app(tmp_path, 'fixture-token', asyncio.Event())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
        assert (await client.get('/api/setup/plugins')).status_code == 401
        client.headers['X-Setup-Token'] = 'fixture-token'
        choices = (await client.get('/api/setup/plugins')).json()['plugins']
        assert {p['name'] for p in choices} == {'group_digest', 'gscore_adapter', 'asoul', 'bilibili'}
        assert all(not p['installed'] and p['repository'].startswith('https://github.com/lendevs/') for p in choices)
        invalid = await client.post('/api/setup', json={**body, 'install_plugins': ['unknown']})
        assert invalid.status_code == 422 and not (tmp_path/'lenbot.config.json').exists()
        invalid = await client.post('/api/setup', json={**body, 'install_plugins': ['group_digest', 'group_digest']})
        assert invalid.status_code == 422
        with pytest.raises(ValueError, match='尚未安装'):
            initialize(tmp_path, FirstSetup.model_validate({**body, 'install_plugins': ['group_digest']}))
        assert not (tmp_path/'personas').exists()
        # A prepared local source exercises the same managed-installation boundary without network downloads.
        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('plugin.toml', '''name = "group_digest"
version = "1.3.0"
interface = 1
requires_lenbot = ">=0.2,<1"
requires_python = ">=3.13"
platforms = ["linux", "darwin", "win32"]
reload = "plugin"
authors = ["LEN5010"]
license = "AGPL-3.0-only"
description = "本机安装边界样本"
''')
            package.writestr('__init__.py', '')
        installer = PluginInstaller(tmp_path)
        await installer.prepare_zip(archive.getvalue(), 'fixture.zip', [])
        installer.apply_files('group_digest')
        result = await client.post('/api/setup', json={**body, 'install_plugins': ['group_digest']})
        assert result.status_code == 200, result.text
        assert result.json()['plugins'] == [{'name': 'group_digest', 'installed': True, 'version': '1.3.0'}]
        cfg = load_host_config(tmp_path)
        assert cfg.plugins.disabled == ['group_digest'] and cfg.plugins.configured == {'group_digest': {}}
        assert cfg.scenes[body['scene']].plugins == []
        before = (tmp_path/'lenbot.config.json').read_bytes()
        assert (await client.get('/api/setup/plugins')).status_code == 409
        assert (await client.post('/api/setup', json=body)).status_code == 409
        assert (tmp_path/'lenbot.config.json').read_bytes() == before


def test_container_setup_always_uses_the_published_panel_port(tmp_path: Path):
    """Compose publishes only 11307; the wizard's default 8088 must not reach the saved config (audit B-1)."""
    from len_bot.next.panel.setup import CONTAINER_PANEL_PORT
    compose = (Path(__file__).parents[1] / 'deploy' / 'current' / 'host.compose.yaml').read_text(encoding='utf-8')
    assert f'{CONTAINER_PANEL_PORT}:{CONTAINER_PANEL_PORT}' in compose
    body = {
        'bot_id':'onebot:90001','owners':['onebot:70001'],'timezone':'Asia/Shanghai','delivery':'simulated',
        'onebot':{'mode':'forward_ws','ws_url':'ws://127.0.0.1:9','access_token':'synthetic-token'},
        'provider':{'api':'openai-chat','base_url':'http://127.0.0.1:9/v1','api_key':'synthetic-secret'},
        'mind':{'provider':'primary','model':'fixture','context_window_tokens':8192},
        'voice_mode':'direct','compaction':{'input_tokens':6000},'embedding':None,
        'scene':'onebot:group:80001','panel_port':8088,'username':'fixture','password':'synthetic-password',
    }

    async def exercise():
        app = create_setup_app(tmp_path, 'fixture-token', asyncio.Event(), container=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://lenbot.example',
                                     headers={'X-Setup-Token': 'fixture-token'}) as client:
            page = (await client.get('/api/setup/protocols')).json()
            assert page['container'] is True and page['panel_port'] == CONTAINER_PANEL_PORT
            response = await client.post('/api/setup', json=body)
            assert response.status_code == 200, response.text
            assert response.json()['panel_url'] == '/' and response.json()['panel_port'] == CONTAINER_PANEL_PORT
        cfg = load_host_config(tmp_path)
        assert (cfg.panel.host, cfg.panel.port) == ('0.0.0.0', CONTAINER_PANEL_PORT)
    asyncio.run(exercise())


def test_local_setup_keeps_the_chosen_port_and_serves_the_panel_frontend(tmp_path: Path):
    built = tmp_path / 'dist'
    (built / 'assets').mkdir(parents=True)
    (built / 'index.html').write_text('<div id="app"></div>', encoding='utf-8')
    (built / 'assets' / 'entry.js').write_text('export {}', encoding='utf-8')
    instance = tmp_path / 'instance'
    instance.mkdir()

    async def exercise():
        app = create_setup_app(instance, 'fixture-token', asyncio.Event(), assets_dir=built)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1',
                                     headers={'X-Setup-Token': 'fixture-token'}) as client:
            page = (await client.get('/api/setup/protocols')).json()
            assert page['container'] is False and page['panel_port'] is None
            # The page itself needs no token: the token is read from the link by the frontend.
            del client.headers['X-Setup-Token']
            assert (await client.get('/api/panel-context')).json() == {'mode': 'setup', 'home': '/setup'}
            index = await client.get('/')
            assert index.status_code == 200 and index.text == '<div id="app"></div>'
            assert (await client.get('/assets/entry.js')).status_code == 200
            assert (await client.get('/api/setup/protocols')).status_code == 401
            assert (await client.get('/api/setup/missing')).status_code == 404

        missing = create_setup_app(instance, 'fixture-token', asyncio.Event(), assets_dir=tmp_path / 'absent')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(missing), base_url='http://127.0.0.1') as client:
            response = await client.get('/')
            assert response.status_code == 503
            message = response.json()['detail']['message']
            assert str(tmp_path / 'absent' / 'index.html') in message and 'npm run build' in message
    asyncio.run(exercise())


def test_docker_smoke_goes_through_the_wizard_port_and_docs_name_the_container_port():
    """B-1 follow-up: the smoke test must not hardcode the port, docs must not promise 8088 for Docker."""
    repo = Path(__file__).parents[1]
    smoke = (repo / 'scripts' / 'smoke_docker_update.py').read_text(encoding='utf-8')
    assert "'panel_port': 11307" not in smoke and "'panel_port': submitted" in smoke
    # N5: the smoke submits 8088 on purpose and checks the stored port is still the container port.
    assert 'submitted = 8088' in smoke and "saved['panel']['port'] == published" in smoke
    # Review 2 A6: the static HTML always says 8088, so the smoke reads the port from the setup API only.
    assert 'id="port"' not in smoke and "wizard_port = json.loads(text)['panel_port']" in smoke
    readme = (repo / 'deploy' / 'current' / 'README.md').read_text(encoding='utf-8')
    assert 'Docker 部署固定为 `http://127.0.0.1:11307`' in readme
    for path in [*(repo / 'deploy').rglob('*docker*.md'), repo / 'website' / 'guide' / 'install-docker.md']:
        if path.exists():
            assert '8088' not in path.read_text(encoding='utf-8'), path


@pytest.mark.parametrize('mode', ['shared', 'separate', 'yahoo', 'off'])
def test_setup_search_connection_and_minimal_custom_persona(tmp_path, mode):
    from len_bot.next.panel.setup import FirstSetup, initialize
    source = json.loads((Path(__file__).parents[1] / 'deploy/current/first-setup.example.json').read_text())
    source.update(password='fixture-password', persona_id='new-role', persona_name='新角色', brief='喜欢聊天。',
                  max_steps=16, web_read=True)
    source.pop('voice_text', None)
    if mode in {'shared', 'separate'}:
        source['web_search'] = {'provider': 'deepseek', 'connection': 'primary' if mode == 'shared' else 'search'}
        if mode == 'separate':
            source['search_provider'] = {'api': 'deepseek-search', 'base_url': 'https://api.deepseek.com/v1',
                                         'api_key': 'synthetic-search-key'}
    else:
        source['web_search'] = {'provider': 'yahoo'} if mode == 'yahoo' else None
    initialize(tmp_path, FirstSetup.model_validate(source))
    config = load_host_config(tmp_path)
    assert config.max_steps == 16 and config.web_read is not None
    assert load_persona(config.scenes[source['scene']].persona).voice == ''
    if mode in {'shared', 'separate'}:
        alias = config.web_search.connection
        assert alias == ('primary' if mode == 'shared' else 'search')
        assert config.models.providers[alias].api_key == (source['provider']['api_key'] if mode == 'shared' else 'synthetic-search-key')
    elif mode == 'off':
        assert config.web_search is None
    else:
        assert config.web_search.provider == 'yahoo' and config.web_search.connection is None
