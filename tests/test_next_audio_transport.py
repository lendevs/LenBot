"""OneBot WAV/base64 boundary using a synthetic 20-second voice message."""
import asyncio
import base64
from io import BytesIO
import json
import wave

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from len_bot.next.config import HostConfig
from len_bot.next.platform.onebot_audio import parse_record
from len_bot.next.platform.onebot import OneBot


def host_source(onebot):
    binding = {'provider': 'fixture', 'model': 'synthetic', 'context_window_tokens': 4096}
    return {"compaction": {"input_tokens": 2000},
        'mode': 'isolated-multi', 'bot_id': 'onebot:90001', 'timezone': 'UTC', 'database': 'unused.db',
        'delivery': 'live', 'onebot': onebot,
        'models': {
            'providers': {'fixture': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1',
                                      'api_key': 'synthetic-unused'}},
            'roles': {'mind': binding,
                      'asr': {'provider': 'fixture', 'model': 'synthetic-audio'}},
        },
        'scenes': {'onebot:group:80001': {'persona': 'unused-role'}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['forward_ws', 'reverse_ws'])
async def test_configured_asr_accepts_wav_above_chat_message_limit(mode):
    output = BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * (20 * 24000))
    wav = output.getvalue()
    response = {'status': 'ok', 'retcode': 0, 'data': {
        'file': '/fixture/voice.wav', 'base64': base64.b64encode(wav).decode(),
    }}
    assert len(json.dumps(response)) > 1048576

    async def peer(websocket):
        request = json.loads(await websocket.recv())
        assert request['action'] == 'get_record'
        await websocket.send(json.dumps({**response, 'echo': request['echo']}))
        await websocket.wait_closed()

    async def request(bot, config):
        await bot.wait_connected(1)
        result = await bot.call('get_record', {'file': 'synthetic.wav', 'out_format': 'wav'})
        assert parse_record(result, config.audio) == (wav, 20.0)
        assert bot.connected

    if mode == 'forward_ws':
        async with serve(peer, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            config = HostConfig.model_validate_json(json.dumps(host_source({
                'mode': mode, 'ws_url': f'ws://127.0.0.1:{port}',
            })))
            async with OneBot(config.onebot, bot_id=config.bot_id,
                              on_event=lambda event: None, on_error=lambda error: None) as bot:
                await request(bot, config)
    else:
        config = HostConfig.model_validate_json(json.dumps(host_source({
            'mode': mode, 'listen_host': '127.0.0.1', 'listen_port': 0,
        })))
        async with OneBot(config.onebot, bot_id=config.bot_id,
                          on_event=lambda event: None, on_error=lambda error: None) as bot:
            port = bot.addresses[0][1]
            async with connect(f'ws://127.0.0.1:{port}', proxy=None, additional_headers={
                'X-Self-ID': config.bot_id.split(':', 1)[1], 'X-Client-Role': 'Universal',
            }) as websocket:
                async with asyncio.TaskGroup() as group:
                    group.create_task(peer(websocket))
                    try:
                        await request(bot, config)
                    finally:
                        await websocket.close()


@pytest.mark.parametrize('audio_bytes', [1024, 16 * 1024 * 1024, 25 * 1024 * 1024])
def test_asr_capacity_default_is_finite_and_tracks_allowed_audio(audio_bytes):
    source = host_source({'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'})
    source['audio'] = {'max_bytes': audio_bytes}
    config = HostConfig.model_validate_json(json.dumps(source))
    required = 4 * ((audio_bytes + 2) // 3) + 65536
    assert config.onebot.max_frame_bytes == max(1048576, required)
    assert 'max_frame_bytes' not in source['onebot']


@pytest.mark.parametrize('onebot', [
    {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
    {'mode': 'reverse_ws', 'listen_host': '127.0.0.1', 'listen_port': 0},
])
def test_asr_explicit_capacity_is_not_silently_changed(onebot):
    from pydantic import ValidationError
    source = host_source({**onebot, 'max_frame_bytes': 1048576})
    with pytest.raises(ValidationError, match='onebot.max_frame_bytes >= 22435160'):
        HostConfig.model_validate_json(json.dumps(source))
    source['onebot']['max_frame_bytes'] = 24 * 1024 * 1024
    config = HostConfig.model_validate_json(json.dumps(source))
    assert config.onebot.max_frame_bytes == 24 * 1024 * 1024
    source['onebot']['max_frame_bytes'] = 1048576
    source['audio'] = {'max_bytes': 512 * 1024}
    config = HostConfig.model_validate_json(json.dumps(source))
    assert config.onebot.max_frame_bytes == 1048576


@pytest.mark.parametrize('mode', ['forward_ws', 'reverse_ws'])
@pytest.mark.parametrize('without_ws_audio', ['no_asr', 'simulated', 'http'])
def test_other_transports_and_disabled_audio_keep_the_message_limit(mode, without_ws_audio):
    onebot = ({'mode': mode, 'ws_url': 'ws://127.0.0.1:9'} if mode == 'forward_ws'
              else {'mode': mode, 'listen_host': '127.0.0.1', 'listen_port': 0})
    source = host_source(onebot)
    if without_ws_audio == 'no_asr':
        del source['models']['roles']['asr']
    elif without_ws_audio == 'simulated':
        source['delivery'] = 'simulated'
    else:
        source['onebot'].update(action_transport='http', http_url='http://127.0.0.1:9')
    assert HostConfig.model_validate_json(json.dumps(source)).onebot.max_frame_bytes == 1048576
    source['onebot']['max_frame_bytes'] = 2048
    assert HostConfig.model_validate_json(json.dumps(source)).onebot.max_frame_bytes == 2048


def test_saved_capacity_remains_explicit_when_audio_limit_changes():
    from pydantic import ValidationError
    source = host_source({'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'})
    config = HostConfig.model_validate_json(json.dumps(source))
    saved = json.loads(config.model_dump_json())
    restored = HostConfig.model_validate_json(json.dumps(saved))
    assert restored.onebot.max_frame_bytes == config.onebot.max_frame_bytes
    saved['audio']['max_bytes'] = 25 * 1024 * 1024
    with pytest.raises(ValidationError, match='onebot.max_frame_bytes'):
        HostConfig.model_validate_json(json.dumps(saved))


@pytest.mark.asyncio
async def test_fetch_record_reads_segment_url_when_file_missing_or_unreachable(monkeypatch):
    from types import SimpleNamespace
    from len_bot.next.models.asr import AudioSettings
    from len_bot.next.platform import onebot_audio, platform_tools
    from len_bot.next.platform.adapter import _open_onebot
    from len_bot.next.platform.onebot_audio import fetch_record

    output = BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 16000)
    wav = output.getvalue()

    fetched = []

    async def fake_fetch_public(url, timeout_seconds, byte_limit, *, fake_ip_networks, public_dns_url=None):
        fetched.append((url, byte_limit('audio/wav', b''), fake_ip_networks, public_dns_url))
        if url.endswith('.wav'):
            return url, 'audio/wav', wav
        if url.endswith('.ogg'):
            return url, 'audio/ogg', b'OggS-audio-bytes'
        return url, 'application/octet-stream', b'\x02#!SILK_V3-raw'

    monkeypatch.setattr(onebot_audio, 'fetch_public', fake_fetch_public)
    settings = AudioSettings(max_bytes=64 * 1024, max_seconds=30, timeout_seconds=5)

    async def unused_call(action, params):
        raise AssertionError(f'unexpected call {action} {params}')

    # No file locator: segment carries http(s) WAV/OGG url directly.
    audio, duration = await fetch_record(unused_call, {'url': 'https://cdn.example/a.wav'}, settings)
    assert audio == wav and duration == 1.0
    audio, duration = await fetch_record(unused_call, {'url': 'https://cdn.example/b.ogg', 'duration': 3.5}, settings)
    assert audio == b'OggS-audio-bytes' and duration == 3.5

    # Raw SILK/AMR URL is rejected rather than poisoning audio_cache.wav.
    with pytest.raises(ValueError, match='neither WAV nor OGG'):
        await fetch_record(unused_call, {'url': 'https://cdn.example/raw.silk'}, settings)

    # Remote NapCat file path MUST still call get_record(out_format="wav") instead of short-circuiting to raw SILK url.
    async def host_path_call(action, params):
        assert action == 'get_record' and params['out_format'] == 'wav'
        return {'status': 'ok', 'retcode': 0, 'data': {
            'file': '/napcat-host/nonexistent/out.wav', 'url': 'https://cdn.example/c.wav',
        }}

    audio, duration = await fetch_record(
        host_path_call,
        {'file': '/napcat-host/nonexistent/voice.amr', 'url': 'https://cdn.example/raw.silk'},
        settings,
    )
    assert audio == wav and duration == 1.0
    assert [item[0] for item in fetched] == [
        'https://cdn.example/a.wav', 'https://cdn.example/b.ogg',
        'https://cdn.example/raw.silk', 'https://cdn.example/c.wav',
    ]
    assert all(limit == settings.max_bytes for _, limit, _, _ in fetched)

    # Verify fake_ip_networks and public_dns_url propagate into OneBot and group_file_fetch.
    source = host_source({'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'})
    source['network'] = {'fake_ip_networks': ['198.18.0.0/15'], 'public_dns_url': 'https://dns.example/dns-query'}
    cfg = HostConfig.model_validate_json(json.dumps(source))
    bot = _open_onebot(cfg, on_event=lambda _: None, on_error=lambda _: None)
    assert bot._fake_ip_networks == cfg.network.networks()
    assert bot._public_dns_url == 'https://dns.example/dns-query'

    forwarded = {}

    async def fake_download_group_file(call, group_id, file_id, busid, max_bytes, *, fake_ip_networks=(), public_dns_url=None):
        forwarded.update(group_id=group_id, file_id=file_id, busid=busid, max_bytes=max_bytes,
                         fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url)
        return b'payload'

    monkeypatch.setattr(platform_tools, 'download_group_file', fake_download_group_file)
    fetcher = platform_tools.group_file_fetch(
        unused_call, '80001', fake_ip_networks=cfg.network.networks(), public_dns_url=cfg.network.public_dns_url,
    )
    assert await fetcher(SimpleNamespace(file_id='f1', busid=102), 4096) == b'payload'
    assert forwarded['fake_ip_networks'] == cfg.network.networks()
    assert forwarded['public_dns_url'] == 'https://dns.example/dns-query'
