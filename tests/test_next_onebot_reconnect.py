"""OneBot connections that drop while the host keeps running."""

import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from len_bot.next.config import load_host_config
from len_bot.next.configuration.onebot import OneBotForward
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform import onebot as onebot_module
from len_bot.next.platform.onebot import OneBot
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store

SCENE = 'onebot:group:80001'
LOGIN = {'status': 'ok', 'retcode': 0, 'data': {'user_id': 90001, 'nickname': '脱敏 Bot'}}


async def _until(condition, seconds: float = 3) -> None:
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(.01)


@pytest.mark.asyncio
async def test_forward_transport_dials_again_and_verifies_the_new_connection(monkeypatch):
    monkeypatch.setattr(onebot_module, 'RECONNECT_INITIAL_SECONDS', .05)
    connections, requests, errors = [], [], []

    async def peer(websocket):
        connections.append(websocket)
        if len(connections) == 1:
            await websocket.close(code=1012, reason='synthetic restart')
            return
        async for frame in websocket:
            request = json.loads(frame)
            requests.append(request['action'])
            data = LOGIN['data'] if request['action'] == 'get_login_info' else {'message_id': 1}
            await websocket.send(json.dumps({**LOGIN, 'data': data, 'echo': request['echo']}))

    async with serve(peer, '127.0.0.1', 0) as server:
        settings = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                                 request_timeout_seconds=1)
        async with OneBot(settings, bot_id='onebot:90001', on_event=lambda event: None,
                          on_error=errors.append) as bot:
            await _until(lambda: len(connections) == 2 and bot.connected)
            assert await bot.identify() == 'onebot:90001'
            assert (await bot.call('get_status', {}))['status'] == 'ok'
    assert any('synthetic restart' in error for error in errors)
    assert requests == ['get_login_info', 'get_status']


@pytest.mark.asyncio
async def test_forward_close_does_not_wait_out_the_reconnect_backoff(monkeypatch):
    monkeypatch.setattr(onebot_module, 'RECONNECT_INITIAL_SECONDS', 60)
    async def peer(websocket):
        await websocket.close()

    server = await serve(peer, '127.0.0.1', 0)
    settings = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                             request_timeout_seconds=1)
    bot = OneBot(settings, bot_id=None, on_event=lambda event: None, on_error=lambda error: None)
    try:
        await bot.start()
        await _until(lambda: not bot.connected)
    finally:
        server.close()
        await server.wait_closed()
    async with asyncio.timeout(2):
        await bot.close()
    assert not bot.connected


def _runtime_config(tmp_path: Path, onebot: dict) -> None:
    role = tmp_path / 'persona'
    role.mkdir()
    (role / 'persona.yaml').write_text(
        'id: reconnect-fixture\nname: 协议角色\nbrief: 重连协议核对\nbehavior: 旁听\n'
        'self_reference: [我]\naliases: []\ntools: []\nskills: []\nstyles: []\n')
    (role / 'voice.md').write_text('协议核对')
    (role / 'boundaries.md').write_text('协议核对')
    (role / 'examples.yaml').write_text('[]\n')
    source = {
        'mode': 'isolated-multi', 'bot_id': 'onebot:90001', 'timezone': 'UTC',
        'database': 'chat.sqlite3', 'delivery': 'simulated', 'onebot': {**onebot, 'request_timeout_seconds': 1},
        'models': {'providers': {'fixture': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1',
                                           'api_key': 'synthetic-unused'}},
                   'roles': {'mind': {'provider': 'fixture', 'model': 'synthetic-unused',
                                      'context_window_tokens': 8192}}},
        'compaction': {'input_tokens': 2000},
        'scenes': {SCENE: {'persona': 'persona', 'attention': {'only_direct': True}}},
    }
    (tmp_path / 'lenbot.config.json').write_text(json.dumps(source, ensure_ascii=False))


@pytest.mark.asyncio
async def test_forward_host_keeps_running_across_a_peer_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(onebot_module, 'RECONNECT_INITIAL_SECONDS', .05)
    connections = asyncio.Queue()

    async def peer(websocket):
        await connections.put(websocket)
        await websocket.wait_closed()

    raw = json.loads((Path(__file__).parent / 'fixtures/next/shutdown/message.json').read_text())
    async with AsyncExitStack() as resources:
        server = await resources.enter_async_context(serve(peer, '127.0.0.1', 0))
        _runtime_config(tmp_path, {'mode': 'forward_ws',
                                   'ws_url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'})
        cfg = load_host_config(tmp_path)
        with Store(cfg.database) as store:
            async with ChatModel(cfg.model_settings('mind')) as model:
                runtime = NetworkRuntime(cfg, [(cfg.scene_config(SCENE), load_persona(tmp_path / 'persona'))], store, model)
                running = asyncio.create_task(runtime.run(manage_signals=False))
                first = await asyncio.wait_for(connections.get(), 3)
                await _until(lambda: runtime.status == 'running')
                await first.close()
                await _until(lambda: not runtime.accepting)
                assert runtime.last_platform_error is not None
                # A runner woken while the peer is away waits for the connection instead of ending.
                runtime.runners[SCENE].changed.set()
                second = await asyncio.wait_for(connections.get(), 3)
                await _until(lambda: runtime.accepting)
                assert runtime.last_platform_error is None
                assert runtime.status == 'running' and not running.done()
                await second.send(json.dumps(raw))
                await _until(lambda: store.pending_messages(SCENE))
                runtime.stop()
                await asyncio.wait_for(running, 3)
        assert runtime.status == 'stopped'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['forward_ws', 'reverse_ws'])
async def test_panel_disconnect_while_the_peer_is_away_keeps_the_host_running(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(onebot_module, 'RECONNECT_INITIAL_SECONDS', 60)
    connections = asyncio.Queue()

    async def peer(websocket):
        await connections.put(websocket)
        await websocket.wait_closed()

    async with AsyncExitStack() as resources:
        if mode == 'forward_ws':
            server = await resources.enter_async_context(serve(peer, '127.0.0.1', 0))
            onebot = {'mode': mode, 'ws_url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'}
        else:
            onebot = {'mode': mode, 'listen_host': '127.0.0.1', 'listen_port': 0}
        _runtime_config(tmp_path, onebot)
        cfg = load_host_config(tmp_path)
        with Store(cfg.database) as store:
            async with ChatModel(cfg.model_settings('mind')) as model:
                runtime = NetworkRuntime(cfg, [(cfg.scene_config(SCENE), load_persona(tmp_path / 'persona'))], store, model)
                running = asyncio.create_task(runtime.run(manage_signals=False))
                if mode == 'forward_ws':
                    websocket = await asyncio.wait_for(connections.get(), 3)
                else:
                    await _until(lambda: runtime.platform.addresses)
                    websocket = await connect(f'ws://127.0.0.1:{runtime.platform.addresses[0][1]}', proxy=None,
                                              additional_headers={'X-Client-Role': 'Universal', 'X-Self-ID': '90001'})
                await _until(lambda: runtime.status == 'running')
                await websocket.close()
                await _until(lambda: not runtime.platform.connected)
                runtime.runners[SCENE].changed.set()
                await asyncio.sleep(.05)
                await runtime.disconnect()
                # The host keeps running without the platform until the panel connects again.
                await asyncio.sleep(.05)
                assert not running.done() and runtime.status == 'running'
                assert runtime.missing_platforms == ['onebot'] and runtime.can_connect
                runtime.stop()
                await asyncio.wait_for(running, 3)
        assert runtime.status == 'stopped'


@pytest.mark.asyncio
async def test_forward_half_open_socket_recovers_after_ping_and_close_timeout(monkeypatch):
    """A TCP proxy drops frames after setup while leaving both sockets open."""
    monkeypatch.setattr(onebot_module, 'RECONNECT_INITIAL_SECONDS', .02)
    errors, connections = [], []
    stalled = asyncio.Event()
    handlers = set()

    async def peer(websocket):
        connections.append(websocket)
        async for frame in websocket:
            request = json.loads(frame)
            await websocket.send(json.dumps({**LOGIN, 'echo': request['echo']}))

    async with serve(peer, '127.0.0.1', 0, ping_interval=None) as server:
        upstream_port = server.sockets[0].getsockname()[1]
        attempts = 0

        async def proxy(reader, writer):
            nonlocal attempts
            task = asyncio.current_task()
            handlers.add(task)
            attempts += 1
            first = attempts == 1
            upstream, remote = await asyncio.open_connection('127.0.0.1', upstream_port)
            async def pipe(source, target):
                while data := await source.read(65536):
                    if not (first and stalled.is_set()):
                        target.write(data)
                        await target.drain()
            pipes = [asyncio.create_task(pipe(reader, remote)), asyncio.create_task(pipe(upstream, writer))]
            try:
                await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for item in pipes:
                    item.cancel()
                await asyncio.gather(*pipes, return_exceptions=True)
                remote.close()
                writer.close()
                await asyncio.gather(remote.wait_closed(), writer.wait_closed(), return_exceptions=True)
                handlers.remove(task)

        async with await asyncio.start_server(proxy, '127.0.0.1', 0) as gateway:
            settings = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{gateway.sockets[0].getsockname()[1]}',
                                     request_timeout_seconds=.1, ping_interval_seconds=.05, ping_timeout_seconds=.05)
            async with OneBot(settings, bot_id='onebot:90001', on_event=lambda event: None,
                              on_error=errors.append) as bot:
                assert await bot.identify() == 'onebot:90001'
                started = asyncio.get_running_loop().time()
                stalled.set()
                await _until(lambda: len(connections) == 2 and bot.connected)
                assert await bot.identify() == 'onebot:90001'
                assert asyncio.get_running_loop().time() - started < 1
            if handlers:
                await asyncio.gather(*list(handlers))
    assert any('keepalive ping timeout' in error for error in errors)


@pytest.mark.asyncio
async def test_ws_call_splits_submitted_state_and_handles_late_echo(monkeypatch, caplog):
    import logging
    from len_bot.next.platform.messages import ChatMessage, Segment, Sender
    from len_bot.next.platform.onebot import OneBotCallError

    errors = []
    release_reply = asyncio.Event()
    received_echoes = []

    async def peer(websocket):
        async for frame in websocket:
            request = json.loads(frame)
            if request['action'] == 'get_login_info':
                await websocket.send(json.dumps({**LOGIN, 'echo': request['echo']}))
                continue
            received_echoes.append(request['echo'])
            await release_reply.wait()
            await websocket.send(json.dumps({
                'status': 'ok', 'retcode': 0, 'data': {'message_id': 777}, 'echo': request['echo'],
            }))

    async with serve(peer, '127.0.0.1', 0) as server:
        settings = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                                 request_timeout_seconds=.08)
        async with OneBot(settings, bot_id='onebot:90001', on_event=lambda event: None,
                          on_error=errors.append) as bot:
            assert await bot.identify() == 'onebot:90001'

            # 1. Timeout after websocket.send succeeds -> submitted=True and recorded in _late_echoes.
            with caplog.at_level(logging.WARNING, logger='len_bot.next.platform.onebot'):
                with pytest.raises(OneBotCallError) as failure:
                    await bot.call('send_group_msg', {'group_id': 80001, 'message': [{'type': 'text', 'data': {'text': 'hi'}}]})
                assert failure.value.submitted is True
                assert received_echoes
                release_reply.set()
                await _until(lambda: not bot._late_echoes)
            assert errors == []
            assert any(getattr(record, 'event', None) == 'onebot_late_echo' and record.levelno == logging.WARNING
                       for record in caplog.records)

            # 2. Failure inside websocket.send -> submitted=False (send_message returns failed, not unconfirmed).
            async def broken_send(_payload):
                raise RuntimeError('socket write failed')

            monkeypatch.setattr(bot._ws, 'send', broken_send)
            msg = ChatMessage(
                id='m1', platform='onebot', bot_id='onebot:90001', scene=SCENE,
                platform_message_id=None, sender=Sender('onebot:90001', None, None, None),
                time=1_700_000_000.0, segments=[Segment('text', {'text': 'hi'})],
                reply_to=None, mentions_bot=False, is_self=True, send_status='sent',
            )
            result = await bot.send_message(msg)
            assert result.status == 'failed' and 'socket write failed' in result.error


@pytest.mark.asyncio
async def test_heavy_onebot_media_actions_relax_timeout(monkeypatch):
    from len_bot.next.platform.messages import ChatMessage, Segment, Sender

    monkeypatch.setattr(onebot_module, 'MEDIA_ACTION_TIMEOUT_SECONDS', 0.4)

    async def peer(websocket):
        async for frame in websocket:
            request = json.loads(frame)
            if request['action'] == 'get_login_info':
                await websocket.send(json.dumps({**LOGIN, 'echo': request['echo']}))
            elif request['action'] == 'send_group_msg':
                await asyncio.sleep(0.15)
                await websocket.send(json.dumps({
                    'status': 'ok', 'retcode': 0, 'data': {'message_id': 888}, 'echo': request['echo'],
                }))

    async with serve(peer, '127.0.0.1', 0) as server:
        settings = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                                 request_timeout_seconds=0.05)
        async with OneBot(settings, bot_id='onebot:90001', on_event=lambda event: None,
                          on_error=lambda error: None) as bot:
            assert bot._action_timeout('send_group_msg', {'message': [{'type': 'text', 'data': {'text': 'hi'}}]}) == 0.05
            assert bot._action_timeout('send_group_msg', {'message': [{'type': 'image', 'data': {'file': 'base64://AA=='}}]}) == 0.4
            assert bot._action_timeout('upload_group_file', {'file': '/a', 'name': 'a.txt'}) == 0.4
            msg = ChatMessage(
                id='m-img', platform='onebot', bot_id='onebot:90001', scene=SCENE,
                platform_message_id=None, sender=Sender('onebot:90001', None, None, None),
                time=1_700_000_000.0, segments=[Segment('image', {})],
                reply_to=None, mentions_bot=False, is_self=True, send_status='sent',
            )
            result = await bot.send_message(msg, image_bytes=b'\x89PNG-payload')
            assert result.status == 'sent' and result.platform_message_id == '888'


@pytest.mark.asyncio
async def test_onebot_download_supports_base64_local_file_and_refreshed_url(tmp_path, monkeypatch):
    import base64

    local_img = tmp_path / 'cached.png'
    local_img.write_bytes(b'local-image-bytes')
    responses = {
        'b64.png': {'status': 'ok', 'retcode': 0, 'data': {'base64': base64.b64encode(b'b64-bytes').decode()}},
        'local.png': {'status': 'ok', 'retcode': 0, 'data': {'file': str(local_img)}},
        'remote.png': {'status': 'ok', 'retcode': 0, 'data': {
            'file': '/napcat-host/not-here/remote.png', 'url': 'https://cdn.example/refreshed.png',
        }},
    }

    async def peer(websocket):
        async for frame in websocket:
            request = json.loads(frame)
            assert request['action'] == 'get_image'
            payload = responses[request['params']['file']]
            await websocket.send(json.dumps({**payload, 'echo': request['echo']}))

    fetched_urls = []

    async def fake_fetch_public(url, timeout_seconds, byte_limit, *, fake_ip_networks, public_dns_url=None):
        fetched_urls.append((url, byte_limit('image/png', b'')))
        return url, 'image/png', b'refreshed-http-bytes'

    monkeypatch.setattr(onebot_module, 'fetch_public', fake_fetch_public)
    async with serve(peer, '127.0.0.1', 0) as server:
        settings = OneBotForward(mode='forward_ws', ws_url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                                 request_timeout_seconds=1)
        async with OneBot(settings, bot_id='onebot:90001', on_event=lambda event: None,
                          on_error=lambda error: None) as bot:
            assert await bot.download({'file': 'b64.png'}, 100) == b'b64-bytes'
            with pytest.raises(ValueError, match='exceeds'):
                await bot.download({'file': 'b64.png'}, 4)
            assert await bot.download({'file': 'local.png'}, 100) == b'local-image-bytes'
            assert await bot.download({'file': 'remote.png'}, 256) == b'refreshed-http-bytes'
            assert fetched_urls == [('https://cdn.example/refreshed.png', 256)]


@pytest.mark.asyncio
async def test_historical_onebot_image_routes_to_fetch_media_before_http(tmp_path, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from len_bot.next.configuration.chat import ImageSettings
    from len_bot.next.media import images as next_images
    from len_bot.next.media.images import LookArguments, load_look_image
    from len_bot.next.platform.onebot_messages import parse_message

    buf = BytesIO()
    Image.new('RGB', (16, 16), 'blue').save(buf, format='PNG')
    png = buf.getvalue()

    now_box = [1_700_002_000.0]
    with Store(tmp_path / 'look.sqlite3', now=lambda: now_box[0]) as store:
        for mid, msg_time, data in (
            ('old-1', 1_700_000_000.0, {'file': 'old.jpg', 'url': 'https://cdn.example/expired.jpg'}),
            ('fresh-1', 1_700_001_500.0, {'file': 'fresh.jpg', 'url': 'https://cdn.example/fresh.jpg'}),
            ('ref-only', 1_700_001_900.0, {'file': 'only-file.jpg'}),
        ):
            raw = {
                'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
                'user_id': 70001, 'message_id': mid, 'time': msg_time,
                'sender': {'nickname': '群友'}, 'message': [{'type': 'image', 'data': data}],
            }
            store.enqueue(parse_message(raw, own_message_ids=set()), raw, received_at=msg_time)

        platform_calls, http_calls = [], []

        async def fetch_media(data: dict, max_bytes: int) -> bytes:
            platform_calls.append(data['file'])
            return png

        async def fake_fetch_public(url, timeout_seconds, byte_limit, *, fake_ip_networks, public_dns_url=None):
            http_calls.append(url)
            return url, 'image/png', png

        monkeypatch.setattr(next_images, 'fetch_public', fake_fetch_public)
        settings = ImageSettings()

        # > 1800s old: deterministically routes to fetch_media without touching HTTP.
        _, reused, source = await load_look_image(
            store, SCENE, LookArguments(message='old-1'), settings,
            fake_ip_networks=(), fetch_media=fetch_media,
        )
        assert not reused and source == 'platform_download'
        assert platform_calls == ['old.jpg'] and http_calls == []

        # <= 1800s fresh with url: goes straight to HTTP.
        _, reused, source = await load_look_image(
            store, SCENE, LookArguments(message='fresh-1'), settings,
            fake_ip_networks=(), fetch_media=fetch_media,
        )
        assert not reused and source == 'http_response'
        assert http_calls == ['https://cdn.example/fresh.jpg'] and platform_calls == ['old.jpg']

        # No url with OneBot file: routes to fetch_media.
        _, reused, source = await load_look_image(
            store, SCENE, LookArguments(message='ref-only'), settings,
            fake_ip_networks=(), fetch_media=fetch_media,
        )
        assert not reused and source == 'platform_download'
        assert platform_calls == ['old.jpg', 'only-file.jpg']


@pytest.mark.asyncio
async def test_onebot_image_load_bidirectional_fallback(tmp_path, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from len_bot.next.configuration.chat import ImageSettings
    from len_bot.next.media import images as next_images
    from len_bot.next.media.images import LookArguments, load_look_image
    from len_bot.next.platform.onebot_messages import parse_message

    buf = BytesIO()
    Image.new('RGB', (16, 16), 'green').save(buf, format='PNG')
    png = buf.getvalue()

    now_box = [1_700_002_000.0]
    with Store(tmp_path / 'fallback.sqlite3', now=lambda: now_box[0]) as store:
        for mid, msg_time, data in (
            ('old-fallback', 1_700_000_000.0, {'file': 'old.jpg', 'url': 'https://cdn.example/still-valid.jpg'}),
            ('fresh-fallback', 1_700_001_500.0, {'file': 'fresh.jpg', 'url': 'https://cdn.example/expired-early.jpg'}),
            ('both-fail', 1_700_001_500.0, {'file': 'gone.jpg', 'url': 'https://cdn.example/403.jpg'}),
            ('url-only-fail', 1_700_001_500.0, {'url': 'https://cdn.example/404-only.jpg'}),
        ):
            raw = {
                'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
                'user_id': 70001, 'message_id': mid, 'time': msg_time,
                'sender': {'nickname': '群友'}, 'message': [{'type': 'image', 'data': data}],
            }
            store.enqueue(parse_message(raw, own_message_ids=set()), raw, received_at=msg_time)

        calls: list[tuple[str, str]] = []
        fail_platform: set[str] = {'old.jpg', 'gone.jpg'}
        fail_http: set[str] = {
            'https://cdn.example/expired-early.jpg',
            'https://cdn.example/403.jpg',
            'https://cdn.example/404-only.jpg',
        }

        async def fetch_media(data: dict, max_bytes: int) -> bytes:
            file_id = str(data['file'])
            calls.append(('platform', file_id))
            if file_id in fail_platform:
                raise RuntimeError(f'get_image unavailable: {file_id}')
            return png

        async def fake_fetch_public(url, timeout_seconds, byte_limit, *, fake_ip_networks, public_dns_url=None):
            calls.append(('http', url))
            if url in fail_http:
                raise ValueError(f'HTTP read status 404: {url}')
            return url, 'image/png', png

        monkeypatch.setattr(next_images, 'fetch_public', fake_fetch_public)
        settings = ImageSettings()

        # > 1800s old image: fetch_media fails, falls back to original HTTP URL.
        _, reused, source = await load_look_image(
            store, SCENE, LookArguments(message='old-fallback'), settings,
            fake_ip_networks=(), fetch_media=fetch_media,
        )
        assert not reused and source == 'http_response'
        assert calls == [('platform', 'old.jpg'), ('http', 'https://cdn.example/still-valid.jpg')]

        # <= 1800s fresh image: HTTP URL fails with 404, falls back to fetch_media.
        calls.clear()
        _, reused, source = await load_look_image(
            store, SCENE, LookArguments(message='fresh-fallback'), settings,
            fake_ip_networks=(), fetch_media=fetch_media,
        )
        assert not reused and source == 'platform_download'
        assert calls == [('http', 'https://cdn.example/expired-early.jpg'), ('platform', 'fresh.jpg')]

        # Both sources fail: raises after trying fallback.
        calls.clear()
        with pytest.raises(RuntimeError, match='get_image unavailable: gone.jpg'):
            await load_look_image(
                store, SCENE, LookArguments(message='both-fail'), settings,
                fake_ip_networks=(), fetch_media=fetch_media,
            )
        assert calls == [('http', 'https://cdn.example/403.jpg'), ('platform', 'gone.jpg')]

        # URL-only image with no platform identifier: does not invoke fetch_media.
        calls.clear()
        with pytest.raises(ValueError, match='HTTP read status 404'):
            await load_look_image(
                store, SCENE, LookArguments(message='url-only-fail'), settings,
                fake_ip_networks=(), fetch_media=fetch_media,
            )
        assert calls == [('http', 'https://cdn.example/404-only.jpg')]


@pytest.mark.asyncio
async def test_animated_keyframes_and_long_screenshot_scaling(tmp_path):
    from io import BytesIO
    from PIL import Image
    from len_bot.media.images import prepare_image, prepare_image_frames
    from len_bot.next.configuration.chat import ImageSettings
    from len_bot.next.media.images import LookArguments, execute_look, load_look_image, shown_image
    from len_bot.next.platform.onebot_messages import parse_message
    from len_bot.next.storage.store import ImageAsset

    # 1. Animated GIF with 8 distinct frames -> extracts 6 keyframes into contact sheet and persists frames=6.
    colors = ['red', 'green', 'blue', 'yellow', 'cyan', 'magenta', 'orange', 'purple']
    gif_frames = [Image.new('RGB', (80, 60), color) for color in colors]
    gif_buf = BytesIO()
    gif_frames[0].save(gif_buf, format='GIF', save_all=True, append_images=gif_frames[1:], duration=100, loop=0)
    gif_bytes = gif_buf.getvalue()

    # Single-frame default compatibility for sticker_collection.
    _, single_anim, sw, sh = prepare_image(gif_bytes, max_bytes=1_000_000, max_pixels=1_000_000, max_dimension=1280)
    assert single_anim is True and (sw, sh) == (80, 60)

    # Multi-frame animated WebP whose flattened RGB pixels are identical deduplicates to 1 frame.
    same_frames = [
        Image.new('RGBA', (64, 64), (255, 255, 255, 0)),
        Image.new('RGBA', (64, 64), (255, 255, 255, 255)),
    ]
    same_buf = BytesIO()
    same_frames[0].save(same_buf, format='WEBP', save_all=True, append_images=same_frames[1:],
                        duration=100, loop=0, lossless=True)
    with Image.open(BytesIO(same_buf.getvalue())) as check_same:
        assert check_same.n_frames == 2
    _, same_anim, _, _, same_count = prepare_image_frames(
        same_buf.getvalue(), max_bytes=1_000_000, max_pixels=1_000_000, max_dimension=1280, max_frames=6,
    )
    assert same_anim is True and same_count == 1

    # Adjacent duplicate flattened frames are filtered while distinct frames are kept.
    dup_frames = [
        Image.new('RGBA', (64, 64), (255, 0, 0, 255)),
        Image.new('RGBA', (64, 64), (255, 255, 255, 0)),
        Image.new('RGBA', (64, 64), (255, 255, 255, 255)),
    ]
    dup_buf = BytesIO()
    dup_frames[0].save(dup_buf, format='WEBP', save_all=True, append_images=dup_frames[1:],
                       duration=100, loop=0, lossless=True)
    with Image.open(BytesIO(dup_buf.getvalue())) as check_dup:
        assert check_dup.n_frames == 3
    _, dup_anim, _, _, dup_count = prepare_image_frames(
        dup_buf.getvalue(), max_bytes=1_000_000, max_pixels=1_000_000, max_dimension=1280, max_frames=6,
    )
    assert dup_anim is True and dup_count == 2

    # 2. Extreme aspect ratio long screenshot keeps readable width and relaxes long edge.
    tall_buf = BytesIO()
    Image.new('RGB', (600, 3000), 'white').save(tall_buf, format='PNG')
    _, tall_anim, tw, th, tframes = prepare_image_frames(
        tall_buf.getvalue(), max_bytes=10_000_000, max_pixels=25_000_000, max_dimension=1280, max_frames=6,
    )
    assert tall_anim is False and tframes == 1 and th == 2560 and tw == 512

    normal_buf = BytesIO()
    Image.new('RGB', (2000, 1000), 'white').save(normal_buf, format='PNG')
    _, _, nw, nh, _ = prepare_image_frames(
        normal_buf.getvalue(), max_bytes=10_000_000, max_pixels=25_000_000, max_dimension=1280, max_frames=6,
    )
    assert (nw, nh) == (1280, 640)

    # 3. Full look pipeline persists frames=6 and distinguishes old frames=1 cache.
    with Store(tmp_path / 'anim.sqlite3', now=lambda: 1_700_000_100.0) as store:
        for mid in ('gif-new', 'gif-old-cache'):
            raw = {
                'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
                'user_id': 70001, 'message_id': mid, 'time': 1_700_000_000.0,
                'sender': {'nickname': '群友'}, 'message': [{'type': 'image', 'data': {'file': f'{mid}.gif'}}],
            }
            store.enqueue(parse_message(raw, own_message_ids=set()), raw, received_at=1_700_000_001.0)

        async def fetch_gif(_data: dict, _max_bytes: int) -> bytes:
            return gif_bytes

        asset, _, _ = await load_look_image(
            store, SCENE, LookArguments(message='gif-new'), ImageSettings(),
            fake_ip_networks=(), fetch_media=fetch_gif,
        )
        assert asset.animated is True and asset.frames == 6
        assert store.image(SCENE, 'gif-new', 1).frames == 6
        shown = shown_image(SCENE, LookArguments(message='gif-new'), asset, pixels_reused=False, pixels_source='platform_download')
        meta = json.loads(shown.split('\n', 1)[0])
        assert meta['animated_frames'] == 6 and meta['animated_first_frame_only'] is False
        assert '动图已提取 6 个关键帧拼图' in shown

        described = await execute_look(
            store, SCENE, LookArguments(message='gif-new'), ImageSettings(),
            model_name='synthetic-vision', describe=lambda _asset: asyncio.sleep(0, result='多帧描述'),
            fake_ip_networks=(), fetch_media=fetch_gif,
        )
        desc_meta = json.loads(described.split('\n', 1)[0])
        assert desc_meta['animated_frames'] == 6 and desc_meta['animated_first_frame_only'] is False
        assert '动图已提取 6 个关键帧拼图' in described

        # Legacy cached animated image with frames=1 still reports first-frame-only truthfully.
        store.save_image(SCENE, 'gif-old-cache', 1, ImageAsset(
            jpeg=asset.jpeg, width=80, height=60, animated=True, fetched_at=1_700_000_050.0, frames=1,
        ))
        old_shown = shown_image(SCENE, LookArguments(message='gif-old-cache'),
                                store.image(SCENE, 'gif-old-cache', 1), pixels_reused=True, pixels_source='cache')
        old_meta = json.loads(old_shown.split('\n', 1)[0])
        assert old_meta['animated_first_frame_only'] is True and 'animated_frames' not in old_meta
        assert '动图只有第一帧' in old_shown


@pytest.mark.asyncio
async def test_parse_forward_content_and_controlled_group_file_download(monkeypatch):
    from len_bot.next.platform import platform_tools
    from len_bot.next.platform.platform_tools import download_group_file, parse_forward

    raw = {'status': 'ok', 'retcode': 0, 'data': {'messages': [{
        'sender': {'user_id': 70001, 'nickname': '甲', 'card': ''},
        'time': 1790000000,
        'content': [{'type': 'text', 'data': {'text': '来自 content 字段'}}],
    }]}}
    nodes = parse_forward(raw)
    assert len(nodes) == 1 and nodes[0].segments[0].data == {'text': '来自 content 字段'}

    seen = []

    async def fake_fetch_public(url, timeout_seconds, byte_limit, *, fake_ip_networks, public_dns_url=None):
        seen.append((url, byte_limit('application/octet-stream', b'')))
        return url, 'application/octet-stream', b'controlled-bytes'

    async def call_ok(_action, _params):
        return {'status': 'ok', 'retcode': 0, 'data': {'url': 'https://files.example/doc.bin'}}

    async def call_bad_url(_action, _params):
        return {'status': 'ok', 'retcode': 0, 'data': {'url': 'https://user:pass@files.example/doc.bin'}}

    monkeypatch.setattr(platform_tools, 'fetch_public', fake_fetch_public)
    assert await download_group_file(call_ok, '80001', '/a1', 102, 512) == b'controlled-bytes'
    assert seen == [('https://files.example/doc.bin', 512)]
    with pytest.raises(ValueError, match='credentials'):
        await download_group_file(call_bad_url, '80001', '/a1', 102, 512)


@pytest.mark.asyncio
async def test_look_falls_back_to_platform_when_fresh_url_returns_unparseable_html(tmp_path, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from len_bot.next.configuration.chat import ImageSettings
    from len_bot.next.media import images as next_images
    from len_bot.next.media.images import LookArguments, load_look_image
    from len_bot.next.platform.onebot_messages import parse_message

    buf = BytesIO()
    Image.new('RGB', (16, 16), 'green').save(buf, format='PNG')
    valid_png = buf.getvalue()

    with Store(tmp_path / 'html_fallback.sqlite3', now=lambda: 1_700_000_100.0) as store:
        raw = {
            'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
            'user_id': 70001, 'message_id': 'html-url-1', 'time': 1_700_000_050.0,
            'sender': {'nickname': '群友'},
            'message': [{'type': 'image', 'data': {'file': 'fallback.png', 'url': 'https://cdn.example/login.html'}}],
        }
        store.enqueue(parse_message(raw, own_message_ids=set()), raw, received_at=1_700_000_050.0)

        async def fake_fetch_public(url, timeout_seconds, byte_limit, *, fake_ip_networks, public_dns_url=None):
            return url, 'text/html', b'<html><body>Expired link</body></html>'

        async def fetch_media(_data: dict, _max_bytes: int) -> bytes:
            return valid_png

        monkeypatch.setattr(next_images, 'fetch_public', fake_fetch_public)
        asset, reused, source = await load_look_image(
            store, SCENE, LookArguments(message='html-url-1'), ImageSettings(),
            fake_ip_networks=(), fetch_media=fetch_media,
        )
        assert not reused and source == 'platform_download'
        assert asset.width == 16 and asset.height == 16
