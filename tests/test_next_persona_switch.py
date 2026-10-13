"""Switching a scene's role while the host runs: library, scene settings, memory, handover and the owner command."""
import asyncio
import json
import time

import httpx
import pytest

from len_bot.next.config import load_host_config
from len_bot.next.configuration.editing import restart_summary
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel, ModelReply
from len_bot.next.panel.app import create_app
from len_bot.next.panel.setup import FirstSetup, initialize
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.onebot_messages import parse_event
from len_bot.next.runtime import personas as persona_service
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store

SCENE = 'onebot:group:80001'


def instance(tmp_path):
    binding = {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 16000}
    initialize(tmp_path, FirstSetup.model_validate_json(json.dumps({
        'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'UTC', 'delivery': 'simulated',
        'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
        'compaction': {'input_tokens': 12000}, 'mind': binding, 'scene': SCENE, 'persona_id': 'fixture',
        'persona_name': '合成角色', 'brief': '合成资料', 'voice_text': '简短', 'boundaries': '',
        'panel_port': 8088, 'username': 'fixture', 'password': 'synthetic-password',
    })))
    path = tmp_path / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['scenes'][SCENE]['persona_aliases'] = ['老称呼']
    path.write_text(json.dumps(source))
    return load_host_config(tmp_path)


def run_host(tmp_path, exercise):
    config = instance(tmp_path)

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store, active_personas={SCENE: 'fixture'}) as memory:
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona))],
                                         store, mind, memory=memory)
                app = create_app(config, runtime, root=tmp_path)
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                        assert (await client.post('/api/auth/login', json={
                            'username': 'fixture', 'password': 'synthetic-password'})).status_code == 200
                        await exercise(client, runtime, store)
                finally:
                    await app.state.trials.close()

    asyncio.run(run())


def reply(text):
    return ModelReply({'role': 'assistant', 'content': text}, text, [], 'stop', None, None)


def group_message(user, ident, text):
    return {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
            'user_id': user, 'message_id': ident, 'time': int(time.time()),
            'sender': {'nickname': '匿名成员', 'role': 'member'}, 'message': [{'type': 'text', 'data': {'text': text}}]}


def test_library_switch_parks_and_restores_scene_settings(tmp_path):
    async def exercise(client, runtime, store):
        library = (await client.get('/api/host/personas')).json()['roles']
        assert [(role['key'], role['scenes']) for role in library] == [('fixture', [SCENE])]
        created = await client.post('/api/host/personas', json={'folder': 'second', 'name': '第二角色'})
        assert created.status_code == 200, created.text
        assert created.json()['id'] == 'second' and created.json()['scenes'] == []
        assert (await client.post('/api/host/personas', json={'folder': 'second', 'name': '重复'})).status_code == 409
        assert (await client.post('/api/host/personas', json={'folder': 'Bad_Name', 'name': '坏名'})).status_code == 422
        copied = await client.post('/api/host/personas/fixture/copy', json={'folder': 'third', 'name': '第三角色'})
        assert copied.status_code == 200 and copied.json()['id'] == 'third'
        assert load_persona(tmp_path / 'personas/third').voice == load_persona(tmp_path / 'personas/fixture').voice

        switched = (await client.post('/api/host/personas/second/scenes', json={'scenes': [SCENE]})).json()['results'][0]
        assert switched['status'] == 'switched' and switched['handover'] == 'skipped'
        chat, runner = runtime.chats[SCENE], runtime.runners[SCENE]
        assert chat.persona.id == chat.expression.persona.id == chat.toolset.persona.id == 'second'
        assert '第二角色' in chat.context.system and '合成角色' not in chat.context.system
        assert '第二角色' in runner.keywords and '老称呼' not in runner.keywords
        assert runtime.memory.active_personas[SCENE] == 'second'
        assert {'fixture', 'second'} <= runtime.memory.known_persona_ids(SCENE)
        saved = json.loads((tmp_path / 'lenbot.config.json').read_text())['scenes'][SCENE]
        assert saved['persona'] == 'personas/second' and 'persona_aliases' not in saved
        assert saved['inactive_personas'] == {'fixture': {'persona_aliases': ['老称呼'], 'relationships': {},
                                                          'behavior_addendum': None}}
        pending = restart_summary(tmp_path, runtime.config, {SCENE: chat.persona})
        assert pending['scenes'] == [] and pending['personas'] == []
        assert (await client.delete('/api/host/personas/second')).status_code == 422

        back = (await client.post('/api/host/personas/fixture/scenes', json={'scenes': [SCENE]})).json()['results'][0]
        assert back['status'] == 'switched'
        assert runtime.config.scenes[SCENE].persona_aliases == chat.config.persona_aliases == ['老称呼']
        assert '老称呼' in runner.keywords
        saved = json.loads((tmp_path / 'lenbot.config.json').read_text())['scenes'][SCENE]
        assert saved['persona_aliases'] == ['老称呼'] and 'inactive_personas' not in saved
        again = (await client.post('/api/host/personas/fixture/scenes', json={'scenes': [SCENE]})).json()['results'][0]
        assert again['status'] == 'unchanged'

        removed = await client.delete('/api/host/personas/third')
        assert removed.status_code == 200 and not (tmp_path / 'personas/third').exists()
        assert '.runtime/deleted-personas/third-' in removed.json()['moved_to']
        assert (await client.get('/api/host/personas/third/profile')).status_code == 404

    run_host(tmp_path, exercise)


def test_switch_waits_for_the_current_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(persona_service, 'WAIT_SECONDS', 0.05)

    async def exercise(client, runtime, store):
        await client.post('/api/host/personas', json={'folder': 'second', 'name': '第二角色'})
        runner = runtime.runners[SCENE]
        async with runner.execution:
            waiting = await client.post('/api/host/personas/second/scenes', json={'scenes': [SCENE]})
            assert waiting.json()['results'] == [{'scene': SCENE, 'status': 'pending'}]
            assert runner.chat.persona.id == 'fixture'
        await asyncio.gather(*runtime.personas.background)
        assert runner.chat.persona.id == 'second'

    run_host(tmp_path, exercise)


def test_roles_only_see_their_own_bot_records(tmp_path):
    async def exercise(client, runtime, store):
        await client.post('/api/host/personas', json={'folder': 'second', 'name': '第二角色'})
        memory = runtime.memory
        memory.jobs.remember_personas(SCENE, {'second'})
        await memory.backend.write(SCENE, 'bot/fixture/promise.md', '合成承诺甲：周五唱歌', 'fixture')
        await memory.backend.write(SCENE, 'bot/second/promise.md', '合成承诺乙：周六画画', 'fixture')
        await memory.backend.write(SCENE, 'people/onebot:70001/profile.md', '合成承诺丙：主人爱吃辣', 'fixture')
        await client.post('/api/host/personas/second/scenes', json={'scenes': [SCENE]})

        hits = json.loads(await memory.execute(SCENE, {'action': 'search', 'query': '合成承诺'}))['hits']
        assert sorted(hit['path'] for hit in hits) == ['bot/second/promise.md', 'people/onebot:70001/profile.md']
        listing = json.loads(await memory.execute(SCENE, {'action': 'browse', 'path': 'bot'}))
        assert [node['name'] for node in listing['nodes']] == ['second']
        with pytest.raises(ValueError, match='另一个角色'):
            await memory.execute(SCENE, {'action': 'read', 'path': 'bot/fixture/promise.md'})
        with pytest.raises(ValueError, match='另一个角色'):
            await memory.execute(SCENE, {'action': 'write', 'path': 'bot/fixture/x.md', 'content': '改写', 'reason': '测试'})
        panel = await client.post('/api/host/memory/search', json={'scene': SCENE, 'query': '合成承诺', 'limit': 10})
        assert panel.status_code == 200, panel.text
        assert 'bot/fixture/promise.md' in {hit['path'] for hit in panel.json()['hits']}

    run_host(tmp_path, exercise)


def test_handover_rewrites_the_session_for_the_next_role(tmp_path):
    async def exercise(client, runtime, store):
        await client.post('/api/host/personas', json={'folder': 'second', 'name': '第二角色'})
        chat = runtime.chats[SCENE]
        store.append(SCENE, {'role': 'user', 'content': '[群聊] 匿名成员：周五唱歌吗'})
        store.append(SCENE, {'role': 'assistant', 'content': '我周五唱给你听'})
        requests = []

        async def complete(messages, tools, **_):
            requests.append(messages)
            return reply('## 话题脉络\n合成角色答应周五唱歌。')

        chat.mind.complete = complete
        result = (await client.post('/api/host/personas/second/scenes', json={'scenes': [SCENE]})).json()['results'][0]
        assert result['status'] == 'switched' and result['handover'] == 'done', result
        assert '「合成角色」换成「第二角色」' in requests[0][0]['content']
        assert '我周五唱给你听' in requests[0][1]['content']
        recap, entries = store.active_history(SCENE)
        assert recap == '## 话题脉络\n合成角色答应周五唱歌。' and entries == []
        assert '「合成角色」换成「第二角色」' in chat.context.host_state

        async def broken(messages, tools, **_):
            raise RuntimeError('合成故障')

        chat.mind.complete = broken
        failed = (await client.post('/api/host/personas/fixture/scenes', json={'scenes': [SCENE]})).json()['results'][0]
        assert failed['status'] == 'switched' and failed['handover'] == 'failed' and '合成故障' in failed['error']
        assert chat.persona.id == 'fixture' and '不是你说的' in chat.context.host_state

    run_host(tmp_path, exercise)


def test_owner_command_switches_without_waking_the_mind(tmp_path):
    async def exercise(client, runtime, store):
        await client.post('/api/host/personas', json={'folder': 'second', 'name': '第二角色'})
        runtime.accepting = True
        runner = runtime.runners[SCENE]

        async def send(user, ident, text):
            runtime._receive(group_message(user, ident, text))
            await asyncio.gather(*list(runtime.commands.tasks))
            return [message for message in store.recent(SCENE, 20) if message.is_self]

        replies = await send(70001, 1, '/角色 第二角色')
        assert runner.chat.persona.id == 'second' and runner.state.pending is None
        assert replies[-1].segments[-1].data['text'] == '已换成 第二角色'
        assert replies[-1].reply_to == '1' and replies[-1].send_status == 'simulated'
        assert any(message.platform_message_id == '1' for _, message, _ in store.pending_messages(SCENE))

        await send(70002, 2, '/角色 合成角色')
        assert runner.chat.persona.id == 'second'
        assert (await send(70001, 3, '/角色'))[-1].segments[-1].data['text'] == '现在是 第二角色。可以换：合成角色、第二角色'
        assert (await send(70001, 4, '/角色 second'))[-1].segments[-1].data['text'] == '现在就是 第二角色'
        assert (await send(70001, 5, '/角色 不存在'))[-1].segments[-1].data['text'].startswith('没有叫 不存在 的角色')
        parsed = parse_event(group_message(70001, 6, '/角色 合成角色'))
        call = None if parsed is None else runtime.commands.match(runtime, runner, parsed)
        assert call is not None and call.command.name == '角色' and call.arguments == ['合成角色']
        assert runtime.commands.match(runtime, runner, parse_event(group_message(70002, 7, '/角色 合成角色'))) is None

    run_host(tmp_path, exercise)
