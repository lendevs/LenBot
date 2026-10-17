"""Host commands over a real OneBot peer: who may use which command, and what reaches the group."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from websockets.asyncio.server import serve

from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
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

    async def say(self, text: str, *, user: int = MEMBER, role: str = 'member', message_id: int = -1) -> None:
        raw = copy.deepcopy(MESSAGE)
        self.sequence += 1
        raw.update(message_id=message_id if message_id != -1 else -20000 - self.sequence, user_id=user,
                   message=[{'type': 'text', 'data': {'text': text}}], raw_message=text)
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
            async with ChatModel(config.model_settings('mind')) as model:
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
        assert '/help' in reply and '/id' in reply
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


def test_unknown_command_name_in_configuration_is_refused(tmp_path):
    write_config(tmp_path, commands={'disabled': ['nope']})
    with pytest.raises(ValueError, match='disabled'):
        load_host_config(tmp_path)
