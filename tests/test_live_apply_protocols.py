"""Live changes across model, platform, MCP, configuration and panel session boundaries."""
import asyncio
import json
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from websockets.asyncio.server import serve

from len_bot.next.config import load_host_config
from len_bot.next.configuration.chat import WAKE_LEVELS
from len_bot.next.configuration.mcp import MCPService
from len_bot.next.configuration.migrations import migrate_source
from len_bot.next.models.client import ChatModel, ModelSettings
from len_bot.next.tools.mcp_host import MCPHost
from len_bot.web import auth
from test_scene_commands_protocol import SCENE, Peer, host, until
from test_platform_connection_panel import panel


def test_format_four_keeps_scene_data_and_removes_sending_switches():
    source = {'config_version': 3, 'delivery': 'simulated', 'onebot': {'mode': 'reverse_ws'},
              'scenes': {SCENE: {'persona': 'role', 'simulated_delivery': True},
                         'telegram:group:123': {'persona': 'other'}}}
    saved = migrate_source(source, 4)
    assert saved['config_version'] == 4 and saved['delivery'] == 'live'
    assert saved['scenes'] == {SCENE: {'persona': 'role'}, 'telegram:group:123': {'persona': 'other'}}
    assert source['delivery'] == 'simulated' and source['scenes'][SCENE]['simulated_delivery']
    assert migrate_source({'config_version': 3, 'delivery': 'simulated'}, 4)['delivery'] == 'simulated'


def test_format_five_moves_wake_levels_and_drops_participation_scores():
    scenes = {'onebot:group:1': {'persona': 'role', 'attention': {'activity': 0.06, 'ambient_min_interval_seconds': 600.0,
                                                                  'ambient_max_interval_seconds': 3600.0,
                                                                  'focus_seconds': 30.0, 'focus_unanswered_limit': 1,
                                                                  'keywords': ['开播']}},
              'onebot:group:2': {'persona': 'role', 'attention': {'only_direct': True}},
              'onebot:group:3': {'persona': 'role', 'attention': {'activity': 0.5, 'ambient_threshold': 0.4,
                                                                  'close_focus_on_silence': True,
                                                                  'focus_seconds': 45.0}},
              'onebot:private:4': {'persona': 'role'}}
    saved = migrate_source({'config_version': 4, 'delivery': 'live', 'scenes': scenes}, 5)
    assert saved['config_version'] == 5
    assert saved['scenes'] == {
        'onebot:group:1': {'persona': 'role', 'attention': {'keywords': ['开播'], **WAKE_LEVELS['quiet']}},
        'onebot:group:2': {'persona': 'role', 'attention': {'only_direct': True}},
        'onebot:group:3': {'persona': 'role', 'attention': {'focus_seconds': 45.0}},
        'onebot:private:4': {'persona': 'role'}}


def test_panel_sessions_survive_restart_and_logout_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, '_ACTIVE_SESSIONS', {})
    monkeypatch.setattr(auth, '_SESSION_FILE', None)
    first = tmp_path / 'one' / 'sessions.json'
    auth.keep_sessions(first)
    token = auth.create_session('operator')
    assert token not in first.read_text()
    auth.keep_sessions(first)
    assert auth.session_user(token) == 'operator'
    auth.keep_sessions(tmp_path / 'two' / 'sessions.json')
    with pytest.raises(HTTPException):
        auth.session_user(token)
    auth.keep_sessions(first)
    auth.revoke_session(token)
    auth.keep_sessions(first)
    with pytest.raises(HTTPException):
        auth.session_user(token)


@pytest.mark.asyncio
async def test_wake_presets_apply_live_and_keep_group_keywords(tmp_path):
    async with panel(tmp_path) as (client, runtime):
        keywords = list(runtime.config.scenes[SCENE].attention.keywords)
        for level in ['active', 'moderate', 'quiet']:
            result = await client.put(f'/api/host/settings/scenes/{SCENE}/wake-level', json={'level': level})
            assert result.status_code == 200, result.text
            saved = load_host_config(tmp_path).scenes[SCENE].attention
            running = runtime.chats[SCENE].config.attention
            assert all(getattr(saved, name) == value for name, value in WAKE_LEVELS[level].items())
            assert running == saved and saved.keywords == keywords and not saved.only_direct
            state = (await client.get('/api/host/state')).json()
            assert next(row for row in state['scenes'] if row['scene'] == SCENE)['wake_level'] == level
        before = (tmp_path / 'lenbot.config.json').read_bytes()
        assert (await client.put(f'/api/host/settings/scenes/{SCENE}/wake-level', json={'level': 'missing'})).status_code == 422
        assert (tmp_path / 'lenbot.config.json').read_bytes() == before


@pytest.mark.asyncio
async def test_onebot_replacement_and_manual_reconnect_keep_the_scene_running(tmp_path):
    replacement = Peer()
    async with serve(replacement.serve, '127.0.0.1', 0) as server, host(tmp_path) as (runtime, original, store):
        saved = runtime.config.model_copy(deep=True)
        saved.onebot.ws_url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        await runtime.settings.apply(saved)
        await until(lambda: runtime.platform.connected)
        await replacement.say('/id')
        await until(lambda: replacement.sends)
        assert original.sends == [] and runtime.status == 'running'
        await runtime.disconnect()
        waiting = asyncio.create_task(runtime._ready(True, SCENE))
        try:
            assert runtime.can_connect and not await runtime._ready(False, SCENE)
            runtime.request_connection()
            assert await asyncio.wait_for(waiting, 3)
            await replacement.say('/id', user=70002)
            await until(lambda: len(replacement.sends) == 2)
            assert runtime.status == 'running' and not runtime.stopped.is_set()
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_scene_platform_waits_for_its_own_connection(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        assert await runtime._ready(False, SCENE)
        assert not await runtime._ready(False, 'telegram:group:123')
        waiting = asyncio.create_task(runtime._ready(True, 'telegram:group:123'))
        await asyncio.sleep(.03)
        assert not waiting.done()
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)


@pytest.mark.asyncio
async def test_rebinding_model_keeps_inflight_request_and_uses_new_credentials():
    arrived, release = asyncio.Event(), asyncio.Event()
    requests = []
    body = (Path(__file__).parent / 'fixtures/next/model/response-text.json').read_bytes()

    async def peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        headers = dict(line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)
        payload = json.loads(await reader.readexactly(int(headers['Content-Length'])))
        requests.append((headers['Authorization'], payload['model']))
        if payload['model'] == 'old':
            arrived.set()
            await release.wait()
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with await asyncio.start_server(peer, '127.0.0.1', 0) as server:
        settings = ModelSettings(base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
                                 api='openai-chat', api_key='old-key', model='old')
        async with ChatModel(settings) as model:
            old = asyncio.create_task(model.complete([{'role': 'user', 'content': 'hi'}], []))
            try:
                await asyncio.wait_for(arrived.wait(), 3)
                await model.rebind(settings.model_copy(update={'api_key': 'new-key', 'model': 'new'}))
                new = await model.complete([{'role': 'user', 'content': 'hi'}], [])
                release.set()
                assert (await old).text == new.text
            finally:
                release.set()
                await old
    assert requests == [('Bearer old-key', 'old'), ('Bearer new-key', 'new')]


@pytest.mark.asyncio
async def test_mcp_saved_service_replaces_tools_and_removes_connection(tmp_path):
    script = tmp_path / 'mcp_peer.py'
    script.write_text('''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': request['params']['protocolVersion'], 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'protocol-fixture', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': sys.argv[1], 'description': 'fixture', 'inputSchema': {'type': 'object'}}]}
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': sys.argv[1]}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
''')
    def service(name):
        return MCPService.model_validate({'enabled': True, 'scenes': [SCENE], 'timeout_seconds': 3,
            'transport': {'type': 'stdio', 'command': sys.executable, 'args': [str(script), name], 'cwd': tmp_path}})
    mcp = MCPHost({}, reserved_tools=set(), log_directory=tmp_path)
    try:
        await mcp.apply({'fixture': service('before')})
        assert [tool.name for tool in mcp.tools_for(SCENE)] == ['mcp__fixture__before'], mcp.state()
        await mcp.apply({'fixture': service('after')})
        tools = mcp.tools_for(SCENE)
        assert [tool.name for tool in tools] == ['mcp__fixture__after'], mcp.state()
        assert json.loads(await tools[0].call(SCENE, {}))['content'][0]['text'] == 'after'
        await mcp.apply({})
        assert mcp.tools_for(SCENE) == [] and mcp.state() == []
    finally:
        await mcp.close()
