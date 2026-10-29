"""Persist the decision for each accepted platform message, independently of pending wakes."""

import json
import asyncio

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.disposition import Disposition
from len_bot.next.chat.session import Chat
from len_bot.next.configuration.chat import TurnDisposition
from len_bot.next.models.client import ChatModel
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message
from test_native_tool_calls import _instance
from test_host_stream import login, panel, receive
from test_next_panel_acts_as_owner import SCENE


@pytest.mark.asyncio
@pytest.mark.parametrize('case,reason', [
    ('blacklist', '黑名单'), ('paused', '群聊已暂停'), ('quiet', '安静时段'),
    ('only-direct', '只回应直接联系'), ('other-bot', '来自其他 Bot'),
    ('plugin', '插件接管'), ('command', '宿主命令'), ('score', '参与分未达门槛'),
    ('pending', '本轮已有待处理唤醒'), ('closed', '局部收尾不允许'), ('others', '发给别人的消息'),
])
async def test_unwoken_message_records_its_own_reason(tmp_path, case, reason):
    config, persona = _instance(tmp_path)
    config.attention.activity = 1
    config.attention.ambient_threshold = 10
    config.attention.explore_probability = 0
    config.attention.focus_seconds = 0
    if case == 'only-direct':
        config.attention.only_direct = True
    if case == 'other-bot':
        config.attention.other_bot_ids = ['onebot:70003']
    if case == 'closed':
        config.attention.ambient_threshold = 0
        config.attention.disposition = TurnDisposition(mode='enforce')
    with Store(config.database, now=lambda: START) as store:
        async with ChatModel(config.model_settings('mind')) as model:
            runner = SceneRunner(Chat(config, persona, store, model, now=lambda: START), lambda _: None)
            if case == 'paused':
                runner.set_paused(True)
            if case == 'quiet':
                runner.set_temporary_quiet(600, 'defer', None)
            if case == 'pending':
                runner.receive(message(70001, 100, '在吗', direct=True))
            if case == 'closed':
                runner.state.disposition = Disposition('closed', [], START + 600, 'previous')
            raw = message(70005 if case == 'blacklist' else 70003, 101, '有人知道怎么做吗？', reply=5 if case == 'others' else None)
            claim = ('fixture', '插件处理') if case == 'plugin' else ('/help', '宿主命令') if case == 'command' else None
            receipt = runner.receive_message(parse_message(raw, own_message_ids=set()), raw,
                                             wake=claim is None, plugin_claim=claim)
            verdict = receipt['wake_verdict']
            assert not verdict['woke'] and verdict['channel'] is None
            assert reason in verdict['reason']
            assert set(verdict) == {'woke', 'channel', 'reason', 'score', 'threshold', 'effect_factor'}
            recorded = store.db.execute('SELECT wake_verdict FROM messages WHERE seq=?', (receipt['message_seq'],)).fetchone()[0]
            assert json.loads(recorded) == verdict
            if case == 'score':
                assert verdict['score'] < verdict['threshold'] == 10
                assert verdict['effect_factor'] == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize('channel', ['direct', 'named', 'focus', 'ambient', 'explore'])
async def test_woken_message_records_the_selected_channel(tmp_path, channel):
    config, persona = _instance(tmp_path)
    config.attention.activity = 1 if channel == 'ambient' else 0
    config.attention.ambient_threshold = .1
    config.attention.explore_probability = 1 if channel == 'explore' else 0
    config.attention.focus_seconds = 60 if channel == 'focus' else 0
    persona.aliases = ['测试名字']
    with Store(config.database, now=lambda: START) as store:
        async with ChatModel(config.model_settings('mind')) as model:
            runner = SceneRunner(Chat(config, persona, store, model, now=lambda: START), lambda _: None)
            if channel == 'focus':
                runner.state.contact(START - 1, 60)
            verdict = runner.receive(message(70001, 1, '测试名字' if channel == 'named' else '有人知道怎么做吗？',
                                             direct=channel == 'direct'))['wake_verdict']
            assert verdict['woke'] and verdict['channel'] == channel


@pytest.mark.asyncio
async def test_onebot_receipt_stream_carries_persisted_verdict_once(tmp_path):
    peers = asyncio.Queue()

    async def peer(ws):
        await peers.put(ws)
        async for frame in ws:
            request = json.loads(frame)
            await ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'echo': request['echo'],
                                      'data': {'user_id': 90001, 'nickname': '合成角色'}}))

    async with serve(peer, '127.0.0.1', 0) as server:
        def configure(root):
            path = root / 'lenbot.config.json'
            source = json.loads(path.read_text())
            source['onebot'] = {'mode': 'forward_ws', 'ws_url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'}
            source['scenes'][SCENE]['attention'] = {'activity': 0}
            path.write_text(json.dumps(source))

        async with panel(tmp_path, configure) as (runtime, client, url):
            async with connect(url, additional_headers=await login(client), proxy=None) as ws:
                await receive(ws)
                running = asyncio.create_task(runtime.run(manage_signals=False))
                try:
                    wire = await asyncio.wait_for(peers.get(), 3)
                    async with asyncio.timeout(3):
                        while runtime.status != 'running':
                            await asyncio.sleep(.01)
                    for raw in [message(70001, 1, '路过'), message(70001, 1, '路过'), message(70001, 2, '/help')]:
                        await wire.send(json.dumps(raw))
                    items = []
                    while len(items) < 2:
                        event = await receive(ws)
                        if event['type'] == 'message.received':
                            items.append(event)
                    assert [e['verdict']['reason'] for e in items] == ['未开启群聊参与', '宿主命令']
                    for event in items:
                        stored = runtime.store.db.execute('SELECT wake_verdict FROM messages WHERE seq=?',
                                                          (event['message_seq'],)).fetchone()[0]
                        assert json.loads(stored) == event['verdict']
                finally:
                    runtime.stop()
                    await asyncio.wait_for(running, 3)
