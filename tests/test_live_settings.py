"""HTTP settings change live OneBot wake decisions and background model calls."""

import asyncio
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from len_bot.next.chat import upkeep as upkeep_module
from len_bot.next.chat.host_manage import HostManageArguments
from len_bot.next.config import load_host_config
from len_bot.next.learning.sticker_collection import StickerCollector
from len_bot.next.models.client import ChatModel
from len_bot.next.panel.app import create_app
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_attention_protocol import message, response
from test_host_stream import login, panel, receive
from test_next_panel_acts_as_owner import SCENE, write_instance


@pytest.mark.asyncio
async def test_settings_apply_to_wake_learning_permissions_and_platform_connection(tmp_path):
    peers, requests = asyncio.Queue(), []

    async def model_peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.lower().split(':', 1) for line in header.split('\r\n')[1:] if ':' in line)
        request = json.loads(await reader.readexactly(int(fields['content-length'])))
        requests.append(request)
        if '<整理>' in str(request['messages'][-1]['content']):
            body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '{"expressions": []}'},
                                           'finish_reason': 'stop'}],
                               'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}).encode()
        else:
            _, _, body = response('say', {'content': '合成回答', 'end_turn': True}, f'call-{len(requests)}')
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def platform_peer(ws):
        await peers.put(ws)
        async for frame in ws:
            request = json.loads(frame)
            data = ({'user_id': 90001, 'nickname': '合成 Bot'} if request['action'] == 'get_login_info'
                    else {'message_id': 1000 + len(requests)})
            await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'echo': request['echo'], 'data': data}))

    model = await asyncio.start_server(model_peer, '127.0.0.1', 0)
    async with model, serve(platform_peer, '127.0.0.1', 0) as platform:
        def configure(root):
            path = root / 'lenbot.config.json'
            source = json.loads(path.read_text())
            source['onebot'] = {'mode': 'forward_ws', 'ws_url': f'ws://127.0.0.1:{platform.sockets[0].getsockname()[1]}'}
            source['delivery'] = 'live'
            source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{model.sockets[0].getsockname()[1]}/v1'
            source['models']['roles']['mind']['context_window_tokens'] = 64000
            source['compaction']['input_tokens'] = 30000
            source['scenes'][SCENE]['attention'] = {'only_direct': True, 'keywords': ['合成角色'],
                                                    'direct_idle_seconds': 0, 'named_idle_seconds': 0}
            path.write_text(json.dumps(source))
            path = root / 'persona/persona.yaml'
            path.write_text(path.read_text().replace('tools: [tool_search, schedule, schedule_list, schedule_cancel]', 'tools: [say]'))

        async with panel(tmp_path, configure) as (runtime, client, url):
            async with connect(url, additional_headers=await login(client), proxy=None) as ws:
                await receive(ws)
                running = asyncio.create_task(runtime.run(manage_signals=False))
                try:
                    wire = await asyncio.wait_for(peers.get(), 3)
                    async with asyncio.timeout(3):
                        while runtime.status != 'running':
                            await asyncio.sleep(.01)

                    async def incoming(ident, *, direct=False):
                        await wire.send(json.dumps(message(70001, ident, '合成角色，如何解释这件事？', direct=direct)))
                        while True:
                            event = await receive(ws)
                            if event['type'] == 'message.received' and event['message_seq'] == runtime.store.max_message_seq(SCENE):
                                return event['verdict']

                    async def ended():
                        while (await receive(ws))['type'] != 'turn.ended':
                            pass

                    assert (await incoming(1))['reason'] == '只回应直接联系'
                    assert requests == []
                    settings_url = f'/api/host/settings/scenes/{SCENE}'
                    saved = runtime.config.scenes[SCENE].model_dump(mode='json')
                    body = {key: saved[key] for key in ('timezone', 'voice_mode', 'attention', 'schedules', 'proactive',
                                                      'transcribe_audio', 'persona_aliases', 'relationships', 'behavior_addendum')}
                    body['schedules'] = {key: body['schedules'][key] for key in ('enabled', 'max_pending', 'autonomous')}
                    body['attention']['only_direct'] = False
                    updated = await client.put(settings_url, json=body)
                    assert updated.status_code == 200, updated.text
                    assert not updated.json()['restart_required']['scenes'][SCENE]
                    assert (await incoming(2))['channel'] == 'named'
                    await ended()
                    assert len(requests) == 1

                    now = datetime.now(timezone.utc)
                    body['attention']['quiet_hours'] = {'start': (now - timedelta(hours=1)).strftime('%H:%M'),
                                                        'end': (now + timedelta(hours=1)).strftime('%H:%M'), 'direct': 'defer'}
                    assert (await client.put(settings_url, json=body)).status_code == 200
                    assert not (await incoming(3, direct=True))['woke']
                    assert len(requests) == 1
                    body['attention']['quiet_hours'] = None
                    body['attention']['only_direct'] = True
                    assert (await client.put(settings_url, json=body)).status_code == 200
                    assert (await incoming(4, direct=True))['channel'] == 'direct'
                    await ended()

                    learning_url = settings_url + '/learning'
                    enabled = await client.put(learning_url, json={'learning': {'extract': True}})
                    assert enabled.status_code == 200, enabled.text
                    assert not enabled.json()['restart_required']
                    assert runtime.learning.state(SCENE)['running']
                    assert (await incoming(5))['reason'] == '只回应直接联系'
                    trigger = await client.post(f'/api/host/scenes/{SCENE}/learning/request')
                    assert trigger.status_code == 200, trigger.text
                    async with asyncio.timeout(3):
                        while (latest := runtime.learning.state(SCENE)['latest']) is None or latest['status'] == 'running':
                            await asyncio.sleep(.01)
                    assert latest['status'] == 'complete'
                    # The upkeep request continues the chat request (without its turn snapshot): same tools, an instruction appended.
                    assert requests[-1]['tools'] == requests[-2]['tools']
                    chat = [item for item in requests[-2]['messages']
                            if not (item['role'] == 'user' and str(item.get('content', '')).startswith('<当前场景状态与参考>'))]
                    assert requests[-1]['messages'][:len(chat)] == chat
                    disabled = await client.put(learning_url, json={'learning': None})
                    assert disabled.status_code == 200 and not disabled.json()['restart_required']
                    assert SCENE not in runtime.learning.scenes

                    permissions_url = f'/api/host/permissions?scene={SCENE}'
                    permission = (await client.get(permissions_url)).json()['saved']
                    permission['global_identities']['admins'] = ['onebot:70002']
                    assert (await client.put(permissions_url, json=permission)).status_code == 200
                    status = HostManageArguments.model_validate({'action': 'status', 'requester': 'onebot:70002'})
                    assert (await runtime.management.execute(SCENE, status))['scenes'][0]['scene'] == SCENE
                    permission['global_identities']['admins'] = []
                    assert (await client.put(permissions_url, json=permission)).status_code == 200
                    with pytest.raises(PermissionError):
                        await runtime.management.execute(SCENE, status)

                    connection = (await client.get('/api/host/settings')).json()['saved']['connection']
                    connection.pop('bot_id')
                    connection['onebot'].pop('access_token_configured')
                    original_url = runtime.config.onebot.ws_url
                    connection['onebot']['ws_url'] = 'ws://127.0.0.1:9'
                    connection['access_token'] = 'synthetic-new-token'
                    connection['max_steps'] = 9
                    moved = await client.put('/api/host/settings/connection', json=connection)
                    assert moved.status_code == 200, moved.text
                    assert not moved.json()['restart_required']['connection']
                    # OneBot reopens at the saved address at once; an unreachable one is reported and can be retried.
                    assert runtime.config.onebot.ws_url == 'ws://127.0.0.1:9' != original_url
                    assert 'onebot' not in runtime.platform.adapters and runtime.last_platform_error
                    assert runtime.missing_platforms == ['onebot'] and runtime.can_connect
                    assert runtime.chats[SCENE].config.max_steps == 9
                    pending = (await client.get('/api/host/pending-restart')).json()
                    assert pending['sections'] == [] and pending['scenes'] == []
                finally:
                    runtime.stop()
                    await asyncio.wait_for(running, 3)


@pytest.mark.asyncio
async def test_memory_ingest_and_summarizer_model_apply_live_without_restart(tmp_path):
    def configure(root):
        path = root / 'lenbot.config.json'
        source = json.loads(path.read_text())
        source['memory'] = {'backend': 'local', 'local': {'directory': 'memory'}, 'summaries': True, 'ingest': None}
        path.write_text(json.dumps(source))

    async with panel(tmp_path, configure) as (runtime, client, _):
        await login(client)
        assert runtime.ingestor is None
        assert SCENE not in runtime.upkeep.parts['memory']
        assert runtime.memory is not None and runtime.memory.summarizer is not None

        current_memory = (await client.get('/api/host/settings')).json()['saved']['memory']
        current_memory['ingest'] = {
            'idle_seconds': 60, 'min_messages': 10, 'max_age_seconds': 3600,
            'batch_size': 50, 'max_steps': 5, 'timeout_seconds': 120,
        }
        enabled = await client.put('/api/host/settings/memory', json={'memory': current_memory})
        assert enabled.status_code == 200, enabled.text
        assert not enabled.json()['restart_required']['memory']
        assert runtime.ingestor is not None
        assert SCENE in runtime.upkeep.parts['memory']
        assert (await client.get('/api/host/memory/ingest')).json()['enabled'] is True

        current_memory['ingest'] = None
        disabled = await client.put('/api/host/settings/memory', json={'memory': current_memory})
        assert disabled.status_code == 200, disabled.text
        assert not disabled.json()['restart_required']['memory']
        assert runtime.ingestor is None
        assert SCENE not in runtime.upkeep.parts['memory']
        assert (await client.get('/api/host/memory/ingest')).json()['enabled'] is False

        models = (await client.get('/api/host/settings')).json()['saved']['models']
        providers = {
            alias: {key: value for key, value in item.items() if key != 'api_key_configured'}
            for alias, item in models['providers'].items()
        }
        roles = models['roles']
        roles['memory'] = {**roles['mind'], 'model': 'summary-v2'}
        rebound = await client.put('/api/host/settings/models', json={'providers': providers, 'roles': roles})
        assert rebound.status_code == 200, rebound.text
        assert not rebound.json()['restart_required']['models']
        assert runtime.memory.summarizer.model.settings.model == 'summary-v2'


def _models_payload(snapshot: dict) -> dict:
    models = snapshot['saved']['models']
    providers = {
        alias: {key: value for key, value in item.items() if key != 'api_key_configured'}
        for alias, item in models['providers'].items()
    }
    return {'providers': providers, 'roles': models['roles']}


@pytest.mark.asyncio
async def test_model_rebind_wakes_stuck_upkeep_without_manual_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(upkeep_module, 'RETRY_DELAY_SECONDS', 0)
    requests = []

    async def model_peer(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.lower().split(':', 1) for line in header.split('\r\n')[1:] if ':' in line)
        request = json.loads(await reader.readexactly(int(fields['content-length'])))
        requests.append(request)
        if request['model'] == 'bad-model':
            status = '429 Too Many Requests'
            body = json.dumps({'error': {'message': 'rate limited'}}).encode()
        else:
            status = '200 OK'
            body = json.dumps({
                'choices': [{'message': {'role': 'assistant', 'content': '{"expressions": []}'},
                             'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 50, 'completion_tokens': 10},
            }).encode()
        writer.write(f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(model_peer, '127.0.0.1', 0)
    async with server:
        def configure(root):
            path = root / 'lenbot.config.json'
            source = json.loads(path.read_text())
            source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
            source['models']['roles']['mind']['model'] = 'bad-model'
            source['models']['roles']['mind']['context_window_tokens'] = 64000
            source['compaction']['input_tokens'] = 30000
            source['scenes'][SCENE]['learning'] = {'extract': True}
            path.write_text(json.dumps(source))

        async with panel(tmp_path, configure) as (runtime, client, _):
            await login(client)
            raw = message(70001, 101, '旧模型报错期间的聊天消息')
            runtime.store.enqueue(parse_message(raw, own_message_ids=set()), raw, 1790000000)
            runtime.upkeep.start()
            runtime.upkeep.request(SCENE, 'expressions')
            async with asyncio.timeout(3):
                while (SCENE not in runtime.upkeep._model_stuck
                       or runtime.learning.state(SCENE)['latest'] is None
                       or runtime.learning.state(SCENE)['latest']['status'] != 'failed'):
                    await asyncio.sleep(.01)
            assert [req['model'] for req in requests] == ['bad-model'] * upkeep_module.AUTO_RETRIES

            payload = _models_payload((await client.get('/api/host/settings')).json())
            payload['roles']['mind']['model'] = 'good-model'
            updated = await client.put('/api/host/settings/models', json=payload)
            assert updated.status_code == 200, updated.text
            assert not updated.json()['restart_required']['models']

            async with asyncio.timeout(3):
                while runtime.learning.state(SCENE)['latest']['status'] != 'complete':
                    await asyncio.sleep(.01)
            assert requests[-1]['model'] == 'good-model'
            assert SCENE not in runtime.upkeep._model_stuck
            assert SCENE not in runtime.upkeep._failures


@pytest.mark.asyncio
async def test_model_and_compaction_updates_clear_compaction_hold_and_recap_cooldown(tmp_path):
    async with panel(tmp_path) as (runtime, client, _):
        await login(client)
        chat = runtime.chats[SCENE]

        chat.compaction_held_at = 1800
        chat._recap_cooldown_until = 9999999999.0
        payload = _models_payload((await client.get('/api/host/settings')).json())
        payload['roles']['mind']['model'] = 'synthetic-mind-v2'
        rebound = await client.put('/api/host/settings/models', json=payload)
        assert rebound.status_code == 200, rebound.text
        assert not rebound.json()['restart_required']['models']
        assert chat.compaction_held_at is None
        assert chat._recap_cooldown_until == 0.0

        chat.compaction_held_at = 2100
        chat._recap_cooldown_until = 9999999999.0
        processing = (await client.get('/api/host/settings')).json()['saved']['processing']
        processing['compaction']['input_tokens'] += 500
        updated = await client.put('/api/host/settings/processing', json=processing)
        assert updated.status_code == 200, updated.text
        assert not updated.json()['restart_required']['processing']
        assert chat.compaction_held_at is None
        assert chat._recap_cooldown_until == 0.0


@pytest.mark.asyncio
async def test_enabling_vision_role_live_when_runtime_started_without_vision(tmp_path):
    write_instance(tmp_path, ['onebot:70001'])
    persona_path = tmp_path / 'persona' / 'persona.yaml'
    persona_path.write_text(
        persona_path.read_text().replace('tools: [tool_search, schedule, schedule_list, schedule_cancel]', 'tools: all'),
        encoding='utf-8',
    )
    config_path = tmp_path / 'lenbot.config.json'
    source = json.loads(config_path.read_text())
    source['models']['roles']['mind']['image_input'] = False
    config_path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')

    config = load_host_config(tmp_path)
    persona = load_persona(config.scenes[SCENE].persona)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind:
            runtime = NetworkRuntime(
                config,
                [(config.scene_config(SCENE), persona)],
                store,
                mind,
                vision=None,
                sticker_collection=StickerCollector(
                    config, store, mind, None,
                    recording=lambda scene: runtime.chats[scene].toolset.replay_images,
                ),
            )
            try:
                chat = runtime.chats[SCENE]
                assert runtime.vision is None
                assert chat.toolset.vision is None
                assert 'look' not in {tool['function']['name'] for tool in chat.toolset.tools}

                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    await login(client)
                    payload = _models_payload((await client.get('/api/host/settings')).json())
                    payload['roles']['mind']['image_input'] = False
                    payload['roles']['vision'] = {
                        **payload['roles']['mind'],
                        'model': 'synthetic-vision',
                        'image_input': True,
                    }
                    updated = await client.put('/api/host/settings/models', json=payload)
                    assert updated.status_code == 200, updated.text
                    assert updated.json()['restart_required']['models'] is False

                assert runtime.vision is not None
                assert runtime._owned_vision is runtime.vision
                assert runtime.vision.settings.model == 'synthetic-vision'
                assert chat.vision is runtime.vision
                assert chat.toolset.vision is runtime.vision
                assert runtime.sticker_collection.vision is runtime.vision
                assert 'look' in {tool['function']['name'] for tool in chat.toolset.tools}
            finally:
                if runtime._owned_vision is not None:
                    await runtime._owned_vision.__aexit__(None, None, None)
                    runtime._owned_vision = None


@pytest.mark.asyncio
async def test_apply_models_syncs_chat_config_before_await_and_clears_compaction_hold_after_scene_update(tmp_path):
    async with panel(tmp_path) as (runtime, client, _):
        await login(client)
        chat = runtime.chats[SCENE]
        observed_during_rebind: list[str] = []
        original_rebind = runtime.mind.rebind

        async def spy_rebind(settings):
            observed_during_rebind.append(chat.config.models.roles.mind.model)
            return await original_rebind(settings)

        runtime.mind.rebind = spy_rebind
        payload = _models_payload((await client.get('/api/host/settings')).json())
        payload['roles']['mind']['model'] = 'sync-before-await-model'
        updated = await client.put('/api/host/settings/models', json=payload)
        assert updated.status_code == 200, updated.text
        assert observed_during_rebind == ['sync-before-await-model']

        # Simulate a turn re-setting compaction hold during an intermediate await inside apply().
        original_set_automatic = runtime.audio.set_automatic

        async def race_during_apply(scene, enabled):
            chat.compaction_held_at = 4321
            chat._recap_cooldown_until = 8888888888.0
            return await original_set_automatic(scene, enabled)

        runtime.audio.set_automatic = race_during_apply
        processing = (await client.get('/api/host/settings')).json()['saved']['processing']
        processing['compaction']['input_tokens'] += 250
        res = await client.put('/api/host/settings/processing', json=processing)
        assert res.status_code == 200, res.text
        assert chat.compaction_held_at is None
        assert chat._recap_cooldown_until == 0.0


@pytest.mark.asyncio
async def test_network_runtime_run_closes_owned_vision_on_stdin_and_early_stop(tmp_path):
    class FakeOwnedVision:
        def __init__(self):
            self.exited = 0

        async def __aexit__(self, exc_type, exc, tb):
            self.exited += 1

    write_instance(tmp_path, ['onebot:70001'])
    config = load_host_config(tmp_path)
    persona = load_persona(config.scenes[SCENE].persona)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind:
            # 1) platform is None (stdin branch) must still release _owned_vision on exit.
            stdin_runtime = NetworkRuntime(config, [(config.scene_config(SCENE), persona)], store, mind, vision=None)
            assert stdin_runtime.platform is None
            fake_stdin_vision = FakeOwnedVision()
            stdin_runtime._owned_vision = fake_stdin_vision
            stdin_runtime.stopped.set()
            await stdin_runtime.run(manage_signals=False)
            assert stdin_runtime._owned_vision is None
            assert fake_stdin_vision.exited == 1

            # 2) stopped already set before platform start (early return branch) must release _owned_vision.
            config_path = tmp_path / 'lenbot.config.json'
            source = json.loads(config_path.read_text(encoding='utf-8'))
            source['onebot'] = {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'}
            config_path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
            platform_config = load_host_config(tmp_path)
            early_runtime = NetworkRuntime(platform_config, [(platform_config.scene_config(SCENE), persona)], store, mind, vision=None)
            assert early_runtime.platform is not None
            fake_early_vision = FakeOwnedVision()
            early_runtime._owned_vision = fake_early_vision
            early_runtime.stopped.set()
            await early_runtime.run(manage_signals=False)
            assert early_runtime._owned_vision is None
            assert fake_early_vision.exited == 1
