"""Host commands over a real OneBot peer: who may use which command, and what reaches the group."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from websockets.asyncio.server import serve

from len_bot.next.config import load_host_config
from len_bot.next.models.failover import open_model
from len_bot.next.models.limits import record_speech
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store

SCENE = 'onebot:group:80001'
OWNER, MEMBER, MANAGER = 70009, 70001, 70002
MESSAGE = json.loads((Path(__file__).parent / 'fixtures/next/shutdown/message.json').read_text())


async def until(condition, seconds: float = 3) -> None:
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(.01)


class Peer:
    """A OneBot implementation that confirms the bot and records each group send."""

    def __init__(self):
        self.sends, self.socket, self.sequence = [], None, 0

    async def serve(self, websocket):
        self.socket = websocket
        async for frame in websocket:
            request = json.loads(frame)
            if request['action'] == 'send_group_msg':
                self.sends.append(request['params'])
            self.sequence += 1
            data = ({'user_id': 90001, 'nickname': '脱敏 Bot'} if request['action'] == 'get_login_info'
                    else {'message_id': 900000 + self.sequence})
            await websocket.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': data, 'echo': request['echo']}))

    async def say(self, text: str, *, user: int = MEMBER, role: str = 'member', before: list | None = None) -> None:
        raw = copy.deepcopy(MESSAGE)
        self.sequence += 1
        raw.update(message_id=-20000 - self.sequence, user_id=user,
                   message=[*(before or []), {'type': 'text', 'data': {'text': text}}], raw_message=text)
        raw['sender'].update(user_id=user, role=role)
        await self.socket.send(json.dumps(raw))

    def texts(self) -> list[str]:
        return [''.join(part['data'].get('text', '') for part in send['message']) for send in self.sends]


def write_config(root: Path, **changes) -> None:
    role = root / 'persona'
    role.mkdir()
    (role / 'persona.yaml').write_text(
        'id: command-fixture\nname: 命令角色\nbrief: 命令协议核对\nbehavior: 旁听\n'
        'self_reference: [我]\naliases: []\ntools: []\nskills: []\nstyles: []\n')
    for name in ('voice.md', 'boundaries.md'):
        (role / name).write_text('协议核对')
    (role / 'examples.yaml').write_text('[]\n')
    source = {
        'mode': 'isolated-multi', 'bot_id': 'onebot:90001', 'timezone': 'UTC', 'owners': [f'onebot:{OWNER}'],
        'database': 'chat.sqlite3', 'delivery': 'onebot',
        'models': {'providers': {'fixture': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1',
                                             'api_key': 'synthetic-unused'}},
                   'roles': {'mind': {'provider': 'fixture', 'model': 'synthetic-unused', 'context_window_tokens': 8192}}},
        'compaction': {'input_tokens': 2000},
        'scenes': {SCENE: {'persona': 'persona', 'attention': {'only_direct': True}}},
        **changes,
    }
    (root / 'lenbot.config.json').write_text(json.dumps(source, ensure_ascii=False))


@asynccontextmanager
async def host(tmp_path: Path, **changes):
    peer = Peer()
    async with serve(peer.serve, '127.0.0.1', 0) as server:
        write_config(tmp_path, onebot={'mode': 'forward_ws', 'request_timeout_seconds': 1,
                                       'ws_url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'}, **changes)
        config = load_host_config(tmp_path)
        with Store(config.database) as store:
            async with open_model(config.models, 'mind') as model:
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(tmp_path / 'persona'))],
                                         store, model)
                running = asyncio.create_task(runtime.run(manage_signals=False))
                await until(lambda: runtime.status == 'running')
                try:
                    yield runtime, peer, store
                finally:
                    runtime.stop()
                    await asyncio.wait_for(running, 3)


def claims(store) -> list[tuple[str, str]]:
    return [tuple(row) for row in store.db.execute('SELECT plugin, kind FROM plugin_events ORDER BY id')]


@pytest.mark.asyncio
async def test_member_help_lists_only_member_commands_without_waking_the_mind(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        await peer.say('/help')
        await until(lambda: peer.sends)
        await until(lambda: len(claims(store)) == 2)
        reply = peer.texts()[0]
        assert '/help' in reply and '/id' in reply and '/status' not in reply and '/reset' not in reply
        assert peer.sends[0]['group_id'] == 80001
        assert peer.sends[0]['message'][0]['type'] == 'reply'
        assert claims(store) == [('/help', 'reply'), ('/help', 'reply')]
        assert runtime.runners[SCENE].state.pending is None


@pytest.mark.asyncio
async def test_id_names_the_scene_the_sender_and_the_bot(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        await peer.say('/id')
        await until(lambda: peer.sends)
    assert peer.texts()[0] == f'场景：{SCENE}\n你的账号：onebot:{MEMBER}\n机器人账号：onebot:90001'


@pytest.mark.asyncio
async def test_command_may_follow_a_reply_and_a_mention_of_the_bot(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        await peer.say(' /id', before=[{'type': 'reply', 'data': {'id': '-10001'}},
                                       {'type': 'at', 'data': {'qq': '90001'}}])
        await until(lambda: peer.sends)
        await peer.say('/id', before=[{'type': 'at', 'data': {'qq': '70003'}}])
        await until(lambda: store.pending_messages(SCENE))
        await asyncio.sleep(.1)
        assert len(peer.sends) == 1 and peer.texts()[0].startswith(f'场景：{SCENE}')


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['/unknown', '/ help', 'help', '/help!'])
async def test_text_that_is_not_a_known_command_is_an_ordinary_message(tmp_path, text):
    async with host(tmp_path) as (runtime, peer, store):
        await peer.say(text)
        await until(lambda: store.pending_messages(SCENE))
        await asyncio.sleep(.1)
        assert peer.sends == [] and claims(store) == []


@pytest.mark.asyncio
async def test_commands_switched_off_reach_the_conversation(tmp_path):
    async with host(tmp_path, commands={'enabled': True, 'disabled': ['id']}) as (runtime, peer, store):
        await peer.say('/id')
        await until(lambda: store.pending_messages(SCENE))
        await peer.say('/help')
        await until(lambda: peer.sends)
        await asyncio.sleep(.1)
        assert len(peer.sends) == 1 and '/id' not in peer.texts()[0]


@pytest.mark.asyncio
async def test_blacklisted_sender_gets_no_command(tmp_path):
    async with host(tmp_path, permissions={'blacklist': [f'onebot:{MEMBER}']}) as (runtime, peer, store):
        await peer.say('/help')
        await until(lambda: store.pending_messages(SCENE) or store.db.execute('SELECT 1 FROM messages').fetchone())
        await asyncio.sleep(.1)
        assert peer.sends == [] and claims(store) == []


async def ask(peer: Peer, text: str, *, user: int = MANAGER, role: str = 'admin') -> str:
    count = len(peer.sends)
    await peer.say(text, user=user, role=role)
    await until(lambda: len(peer.sends) > count)
    return peer.texts()[count]


@pytest.mark.asyncio
async def test_group_manager_sees_and_uses_scene_commands(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        listed = await ask(peer, '/help')
        assert all(f'/{name}' in listed for name in ('status', 'chat', 'quiet', 'resume', 'reset'))
        status = await ask(peer, '/status')
    assert status.splitlines() == [f'场景：{SCENE}', '聊天：开启',
                                   '发言：最近一小时 0/60 条（全局设置），被叫到时另有余量 5/5 条',
                                   '主脑模型：fixture / synthetic-unused']


@pytest.mark.asyncio
async def test_member_cannot_change_the_scene_and_is_not_answered(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        await peer.say('/chat off')
        await until(lambda: store.pending_messages(SCENE))
        await asyncio.sleep(.1)
        assert peer.sends == [] and runtime.runners[SCENE].state.paused is False


@pytest.mark.asyncio
async def test_chat_off_keeps_recording_and_chat_on_still_works(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        assert '已关闭本群聊天' in await ask(peer, '/chat off', user=OWNER, role='member')
        runner = runtime.runners[SCENE]
        assert runner.state.paused is True
        assert '聊天：已关闭' in await ask(peer, '/status')
        assert await ask(peer, '/chat off') == '本群聊天本来就是关闭的'
        assert '已打开本群聊天' in await ask(peer, '/chat on')
        assert runner.state.paused is False
        assert await ask(peer, '/chat maybe') == '用法：/chat on 或 /chat off'


@pytest.mark.asyncio
async def test_quiet_and_resume(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        runner = runtime.runners[SCENE]
        reply = await ask(peer, '/quiet 30')
        quiet = runner.state.temporary_quiet
        assert quiet.direct == 'allow' and quiet.requester == f'onebot:{MANAGER}'
        assert quiet.until - quiet.started == 1800 and reply.endswith('被@或回复时仍会回应，/resume 提前恢复')
        assert '被叫到时仍回应' in await ask(peer, '/status')
        await ask(peer, '/quiet 5 defer')
        assert runner.state.temporary_quiet.direct == 'defer'
        assert runner.quiet_direct(store.now()) == 'defer'
        assert await ask(peer, '/resume') == '已结束临时安静'
        assert runner.quiet_period(store.now()) is None
        assert await ask(peer, '/resume') == '本群没有临时安静'
        for wrong in ('/quiet', '/quiet ten', '/quiet 5 later', '/quiet 0', '/quiet 10081'):
            assert (await ask(peer, wrong)).startswith(('用法：/quiet', '安静时长为 1 到 10080 分钟'))
        assert runner.state.temporary_quiet is None


@pytest.mark.asyncio
async def test_reset_moves_the_context_boundary_but_keeps_history(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        store.append(SCENE, {'role': 'user', 'content': '旧话'})
        reply = await ask(peer, '/reset')
        assert reply == '已开始新的对话上下文；聊天记录、记忆和未读消息都保留'
        assert store.entries(SCENE) == []
        assert store.db.execute('SELECT COUNT(*) FROM mind_entries WHERE scene=?', (SCENE,)).fetchone()[0] == 1
        assert await ask(peer, '/reset now') == '用法：/reset'


@pytest.mark.asyncio
async def test_reset_refuses_while_a_turn_is_unfinished(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        store.append(SCENE, {'role': 'user', 'content': '旧话'})
        store.start_turn(SCENE)
        assert await ask(peer, '/reset') == '本群还有没结束或等待恢复的一轮，没有重置'
        assert store.entries(SCENE) == [{'role': 'user', 'content': '旧话'}]


CHAIN = {'providers': {'fixture': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-unused'},
                       'backup': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v2', 'api_key': 'synthetic-unused'}},
         'roles': {'mind': {'provider': 'fixture', 'model': 'synthetic-command-primary', 'context_window_tokens': 8192,
                            'fallbacks': [{'provider': 'backup', 'model': 'synthetic-command-backup'}]}},
         'failover': {'failure_threshold': 1, 'cooldown_seconds': 600}}


@pytest.mark.asyncio
async def test_owner_sees_the_mind_fallbacks_and_their_circuits(tmp_path):
    async with host(tmp_path, models=CHAIN) as (runtime, peer, store):
        owner = {'user': OWNER, 'role': 'member'}
        assert (await ask(peer, '/model', **owner)).splitlines() == [
            '主脑服务（按顺序尝试）：', '1. fixture / synthetic-command-primary，正常',
            '2. backup / synthetic-command-backup，正常']
        # Both services are unreachable: the real failover path opens each circuit at the first failure.
        async with open_model(runtime.config.models, 'mind') as mind:
            with pytest.raises(httpx.TransportError):
                await mind.complete([{'role': 'user', 'content': '你好'}], [])
        lines = (await ask(peer, '/model', **owner)).splitlines()
        assert lines[1].startswith('1. fixture / synthetic-command-primary，熔断冷却中，')
        assert lines[2].startswith('2. backup / synthetic-command-backup，熔断冷却中，') and lines[2].endswith('秒后再试')
        assert '主脑模型：fixture / synthetic-command-primary（另有 1 个备用）' in await ask(peer, '/status', **owner)
        assert await ask(peer, '/model use 2', **owner) == '用法：/model。调整顺序或备用服务请在面板的模型页修改'


@pytest.mark.asyncio
async def test_model_without_fallbacks_says_it_does_not_switch(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        assert (await ask(peer, '/model', user=OWNER, role='member')).splitlines() == [
            '主脑服务：', '1. fixture / synthetic-unused', '没有配置备用服务；出错时不会切换']


@pytest.mark.asyncio
async def test_group_manager_is_not_a_bot_manager(tmp_path):
    async with host(tmp_path) as (runtime, peer, store):
        assert '/model' not in await ask(peer, '/help')
        await peer.say('/limit 3', user=MANAGER, role='admin')
        await until(lambda: len(store.pending_messages(SCENE)) == 1)
        await asyncio.sleep(.1)
        assert len(peer.sends) == 1 and 'scene_messages_per_hour' not in (tmp_path / 'lenbot.config.json').read_text()


@pytest.mark.asyncio
async def test_owner_saves_the_scene_speech_limit(tmp_path):
    def saved():
        return json.loads((tmp_path / 'lenbot.config.json').read_text()).get('limits', {}).get('scene_messages_per_hour')

    async with host(tmp_path) as (runtime, peer, store):
        owner = {'user': OWNER, 'role': 'member'}
        assert await ask(peer, '/limit', **owner) == '发言：最近一小时 0/60 条（全局设置），被叫到时另有余量 5/5 条'
        assert (await ask(peer, '/limit 12', **owner)).endswith('0/12 条（本群单独设置），被叫到时另有余量 5/5 条')
        assert saved() == {SCENE: 12} and runtime.config.limits.scene_messages_per_hour == {SCENE: 12}
        assert (await ask(peer, '/limit off', **owner)).endswith('发言上限：不限（最近一小时 0 条）')
        assert saved() == {SCENE: None}
        await ask(peer, '/limit global', **owner)
        assert saved() == {} and runtime.config.limits.scene_messages_per_hour == {}
        record_speech(store, SCENE)
        assert '最近一小时 1/60 条' in await ask(peer, '/limit', **owner)
        assert await ask(peer, '/limit reset', **owner) == '已清空本群最近一小时的发言计数'
        assert '最近一小时 0/60 条' in await ask(peer, '/limit', **owner)
        assert await ask(peer, '/limit 0', **owner) == '每小时条数为 1 到 1000'
        assert saved() == {}


def test_unknown_command_name_in_configuration_is_refused(tmp_path):
    write_config(tmp_path, commands={'disabled': ['nope']})
    with pytest.raises(ValueError, match='disabled'):
        load_host_config(tmp_path)
