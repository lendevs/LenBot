"""The live event protocol over an authenticated network WebSocket."""

import asyncio
from contextlib import asynccontextmanager, nullcontext
import json
import socket

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.memory.service import open_memory
from len_bot.next.memory.ingest import open_memory_ingestor
from len_bot.next.panel.app import create_app
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from len_bot.next.models.slots import ModelSlots
from len_bot.next.learning.expressions import ExpressionLearner
from len_bot.next.learning.jargon import JargonLearner
from len_bot.next.learning.sticker_collection import StickerCollector
from len_bot.next.learning.reply_effects import ReplyEffectTracker
from test_next_panel_acts_as_owner import SCENE, write_instance


@asynccontextmanager
async def panel(root, configure=None):
    write_instance(root, ['onebot:70001'])
    if configure is not None:
        configure(root)
    config = load_host_config(root)
    with Store(config.database) as store:
        slots = ModelSlots(config.max_model_requests)
        async with (ChatModel(config.model_settings('mind')) as model,
                    (ChatModel(config.model_settings('learner')) if config.models.roles.learner is not None else nullcontext(None)) as learner,
                    (ChatModel(config.model_settings('vision')) if config.models.roles.vision is not None else nullcontext(None)) as vision,
                    open_memory(config, store) as memory,
                    open_memory_ingestor(config, store, memory, list(config.scenes)) as ingestor):
            runtime = NetworkRuntime(config, [(config.scene_config(scene), load_persona(settings.persona))
                                              for scene, settings in config.scenes.items()],
                                     store, model, memory=memory, ingestor=ingestor, slots=slots, vision=vision,
                                     learning=None if learner is None else ExpressionLearner(config, store, learner, slots=slots),
                                     jargon=None if learner is None else JargonLearner(config, store, learner, slots=slots),
                                     reply_effects=None if learner is None else ReplyEffectTracker(config, store, learner, slots=slots),
                                     sticker_collection=None if vision is None else StickerCollector(config, store, vision, slots=slots,
                                         recording=lambda scene: runtime.chats[scene].toolset.replay_images))
            app = create_app(config, runtime, root=root)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(app, log_level='critical', access_log=False))
                running = asyncio.create_task(server.serve(sockets=[listener]))
                try:
                    async with asyncio.timeout(3):
                        while not server.started:
                            await asyncio.sleep(.01)
                    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}') as client:
                        yield runtime, client, f'ws://127.0.0.1:{port}/api/host/stream'
                finally:
                    server.should_exit = True
                    await running


async def login(client):
    response = await client.post('/api/auth/login', json={
        'username': 'host-operator', 'password': 'synthetic-password'})
    assert response.status_code == 200
    return {'Cookie': '; '.join(f'{k}={v}' for k, v in client.cookies.items())}


async def receive(websocket):
    return json.loads(await asyncio.wait_for(websocket.recv(), 2))


@pytest.mark.asyncio
async def test_stream_auth_origin_and_logout(tmp_path):
    async with panel(tmp_path) as (runtime, client, url):
        with pytest.raises(InvalidStatus) as denied:
            async with connect(url, proxy=None):
                pass
        assert denied.value.response.status_code == 403
        headers = await login(client)
        with pytest.raises(InvalidStatus):
            async with connect(url, additional_headers=headers, origin='http://elsewhere.test', proxy=None):
                pass
        async with connect(url, additional_headers=headers, origin=str(client.base_url).rstrip('/'), proxy=None) as ws:
            assert (await receive(ws))['type'] == 'hello'
            await client.post('/api/auth/logout')
            with pytest.raises(ConnectionClosed) as closed:
                await receive(ws)
            assert closed.value.rcvd.code == 1008


@pytest.mark.asyncio
async def test_stream_thread_publish_preserves_order_and_scene(tmp_path):
    async with panel(tmp_path) as (runtime, client, url):
        headers = await login(client)
        async with connect(url, additional_headers=headers, proxy=None) as ws:
            hello = await receive(ws)
            assert hello == {'type': 'hello', 'seq': 0}

            def publish():
                for number in range(20):
                    runtime.events.publish('message.received', scene=SCENE, message_seq=number)

            await asyncio.to_thread(publish)
            events = [await receive(ws) for _ in range(20)]
            assert [item['seq'] for item in events] == list(range(1, 21))
            assert [item['message_seq'] for item in events] == list(range(20))
            assert all(item['scene'] == SCENE and item['at'] > 0 for item in events)


@pytest.mark.asyncio
async def test_stream_overflow_resync_then_continues(tmp_path):
    async with panel(tmp_path) as (runtime, client, url):
        async with connect(url, additional_headers=await login(client), proxy=None) as ws:
            await receive(ws)
            for number in range(2001):
                runtime.events.publish('message.received', scene=SCENE, message_seq=number)
            event = await receive(ws)
            assert event['type'] == 'resync' and event['seq'] == 2001
            runtime.events.publish('message.received', scene=SCENE, message_seq=2001)
            event = await receive(ws)
            assert event['type'] == 'message.received' and event['seq'] == 2002


@pytest.mark.asyncio
async def test_stream_coalesces_changes_and_reports_controls(tmp_path):
    async with panel(tmp_path) as (runtime, client, url):
        async with connect(url, additional_headers=await login(client), proxy=None) as ws:
            await receive(ws)
            runtime.notify()
            assert (await receive(ws))['type'] == 'host.changed'
            for _ in range(100):
                runtime.notify()
            assert (await receive(ws))['type'] == 'host.changed'
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(ws.recv(), .3)
            response = await client.put(f'/api/host/scenes/{SCENE}/control/chat', json={'enabled': False})
            assert response.status_code == 200, response.text
            while (event := await receive(ws))['type'] != 'host.state':
                pass
            assert event['scene'] == SCENE
            assert runtime.runners[SCENE].state.paused
