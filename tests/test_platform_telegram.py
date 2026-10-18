"""The Telegram adapter against a local Bot API server: polling, parsing, sending and reconnecting."""

import asyncio
from dataclasses import replace
import json
import threading
import time
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from len_bot.next.config import load_host_config
from len_bot.next.configuration.telegram import TelegramSettings
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.adapter import PlatformCallError
from len_bot.next.platform.messages import ChatMessage, Segment, Sender
from len_bot.next.platform.telegram import Telegram
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_scene_commands_protocol import until, write_config

TOKEN = '123456:synthetic-telegram-token'
BOT = 90001
GROUP = -100500
SCENE = f'telegram:group:{GROUP}'


class BotAPI:
    """A local Telegram Bot API: queued updates for getUpdates, every send recorded."""

    def __init__(self, *, bot: int = BOT):
        self.bot, self.updates, self.sent, self.failures = bot, [], [], 0
        self.lock = threading.Lock()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                token, _, method = self.path.removeprefix('/bot').partition('/')
                status, answer = api.answer(token, method, body, self.headers.get('Content-Type', ''))
                data = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def answer(self, token, method, body, content_type):
        if token != TOKEN:
            return 401, {'ok': False, 'error_code': 401, 'description': 'Unauthorized'}
        if method == 'getMe':
            return 200, {'ok': True, 'result': {'id': self.bot, 'is_bot': True, 'username': 'lenbot_fixture_bot'}}
        if method == 'getUpdates':
            if self.failures:
                self.failures -= 1
                return 502, {'ok': False, 'error_code': 502, 'description': 'Bad Gateway'}
            params = json.loads(body)
            deadline = time.monotonic() + min(params.get('timeout', 0), 0.2)
            while time.monotonic() < deadline:
                with self.lock:
                    if any(item['update_id'] >= params.get('offset', 0) for item in self.updates):
                        break
                time.sleep(0.01)
            with self.lock:
                ready = [item for item in self.updates if item['update_id'] >= params.get('offset', 0)]
            return 200, {'ok': True, 'result': ready}
        if method in {'sendMessage', 'sendPhoto'}:
            params = json.loads(body) if 'json' in content_type else {'multipart': body}
            with self.lock:
                self.sent.append((method, params))
                return 200, {'ok': True, 'result': {'message_id': 7000 + len(self.sent)}}
        if method == 'getChat':
            chat = json.loads(body)['chat_id']
            return 200, {'ok': True, 'result': ({'id': chat, 'type': 'supergroup', 'title': '脱敏群'} if chat < 0 else
                                                {'id': chat, 'type': 'private', 'first_name': '脱敏', 'last_name': '群友'})}
        if method == 'getChatMemberCount':
            return 200, {'ok': True, 'result': 42}
        if method == 'sendChatAction':
            return 400, {'ok': False, 'error_code': 400, 'description': 'Bad Request: chat not found'}
        return 404, {'ok': False, 'error_code': 404, 'description': 'Not Found'}

    def push(self, text, *, user=7001, chat=GROUP, entities=(), reply_to=None):
        with self.lock:
            update_id = 500 + len(self.updates)
            message = {'message_id': 300 + len(self.updates), 'date': int(time.time()),
                       'chat': {'id': chat, 'type': 'supergroup' if chat < 0 else 'private'},
                       'from': {'id': user, 'is_bot': False, 'first_name': '脱敏', 'last_name': '群友'},
                       'text': text, 'entities': list(entities)}
            if reply_to is not None:
                message['reply_to_message'] = reply_to
            self.updates.append({'update_id': update_id, 'message': message})

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


def adapter(api, events=None, errors=None):
    return Telegram(TelegramSettings(bot_token=TOKEN, api_base=api.base, poll_timeout_seconds=1,
                                     request_timeout_seconds=2),
                    bot_id=f'telegram:{BOT}', on_event=([] if events is None else events).append,
                    on_error=([] if errors is None else errors).append)


def test_messages_are_parsed_into_scenes_mentions_and_replies():
    with BotAPI() as api:
        telegram = adapter(api)
        telegram.username = 'lenbot_fixture_bot'
        api.push('嗨 @lenbot_fixture_bot 看看', entities=[{'type': 'mention', 'offset': 2, 'length': 19}],
                 reply_to={'message_id': 12, 'from': {'id': 5}})
        api.push('私聊', chat=7001)
        group, private = (telegram.parse(item) for item in api.updates)
    assert group.scene == SCENE and group.platform_message_id == '300' and group.reply_to == '12'
    assert [(segment.type, segment.data) for segment in group.segments] == [
        ('reply', {'id': '12'}), ('text', {'text': '嗨 '}), ('mention', {'user': f'telegram:{BOT}'}),
        ('text', {'text': ' 看看'})]
    assert group.mentions_bot and not group.is_self and group.sender.uid == 'telegram:7001'
    assert group.sender.nickname == '脱敏 群友'
    assert private.scene == 'telegram:private:7001' and not private.mentions_bot
    assert telegram.parse({'update_id': 1, 'edited_message': {}}) is None


def test_commands_addressed_to_this_bot_drop_the_username_and_mention_it():
    with BotAPI() as api:
        telegram = adapter(api)
        telegram.username = 'lenbot_fixture_bot'
        api.push('/status@LenBot_Fixture_Bot 现在', entities=[{'type': 'bot_command', 'offset': 0, 'length': 26}])
        api.push('/status@other_bot', entities=[{'type': 'bot_command', 'offset': 0, 'length': 17}])
        api.push('/status', entities=[{'type': 'bot_command', 'offset': 0, 'length': 7}])
        ours, other, plain = (telegram.parse(item) for item in api.updates)
    assert [(segment.type, segment.data) for segment in ours.segments] == [('text', {'text': '/status 现在'})]
    assert ours.mentions_bot
    assert [(segment.type, segment.data) for segment in other.segments] == [('text', {'text': '/status@other_bot'})]
    assert not other.mentions_bot
    assert [(segment.type, segment.data) for segment in plain.segments] == [('text', {'text': '/status'})]
    assert not plain.mentions_bot


@pytest.mark.asyncio
async def test_polling_delivers_updates_once_and_reconnects_after_a_gateway_error():
    events, errors = [], []
    with BotAPI() as api:
        api.failures = 1
        telegram = adapter(api, events, errors)
        await telegram.start()
        try:
            await until(lambda: errors, 3)
            assert 'Bad Gateway' in errors[0] and TOKEN not in errors[0]
            await until(lambda: telegram.connected, 5)
            api.push('一')
            api.push('二')
            await until(lambda: len(events) == 2, 3)
            await asyncio.sleep(0.3)
            assert [item['message']['text'] for item in events] == ['一', '二']
            assert await telegram.identify() == f'telegram:{BOT}'
        finally:
            await telegram.close()
        await telegram.wait_terminated()
        assert not telegram.connected


@pytest.mark.asyncio
async def test_a_token_of_another_bot_fails_the_start():
    with BotAPI(bot=424242) as api:
        telegram = adapter(api)
        with pytest.raises(ValueError, match='belongs to 424242'):
            await telegram.start()


@pytest.mark.asyncio
async def test_send_text_with_reply_and_mention_and_report_refusals():
    with BotAPI() as api:
        telegram = adapter(api)
        await telegram.start()
        try:
            message = ChatMessage(id='x', platform='telegram', bot_id=f'telegram:{BOT}', scene=SCENE,
                                  platform_message_id=None, sender=Sender(f'telegram:{BOT}', None, None, None),
                                  time=0.0, segments=[Segment('reply', {'id': '300'}), Segment('text', {'text': '你好 '}),
                                                      Segment('mention', {'user': 'telegram:7001'})],
                                  reply_to='300', mentions_bot=False, is_self=True, send_status='sent')
            result = await telegram.send_message(message)
            assert (result.status, result.platform_message_id) == ('sent', '7001')
            method, params = api.sent[0]
            assert method == 'sendMessage' and params['chat_id'] == GROUP and params['text'] == '你好 @7001'
            assert params['reply_parameters'] == {'message_id': 300, 'allow_sending_without_reply': True}
            assert params['entities'] == [{'type': 'text_mention', 'offset': 3, 'length': 5, 'user': {'id': 7001}}]
            with pytest.raises(PlatformCallError, match='chat not found') as refused:
                await telegram.call('sendChatAction', {'chat_id': 1, 'action': 'typing'})
            assert refused.value.submitted is False
            bad = await telegram.send_message(replace(message, scene='onebot:group:1'))
            assert bad.status == 'failed' and len(api.sent) == 1
        finally:
            await telegram.close()


@asynccontextmanager
async def telegram_host(tmp_path, api):
    write_config(tmp_path, onebot=None, delivery='telegram', bot_id=f'telegram:{BOT}', owners=['telegram:7009'],
                 telegram={'bot_token': TOKEN, 'api_base': api.base, 'poll_timeout_seconds': 1,
                           'request_timeout_seconds': 2},
                 scenes={SCENE: {'persona': 'persona', 'attention': {'only_direct': True}}})
    config = load_host_config(tmp_path)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as model:
            runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(tmp_path / 'persona'))],
                                     store, model)
            running = asyncio.create_task(runtime.run(manage_signals=False))
            await until(lambda: runtime.status == 'running', 5)
            try:
                yield runtime, store
            finally:
                runtime.stop()
                await asyncio.wait_for(running, 5)


@pytest.mark.asyncio
async def test_a_telegram_host_stores_group_messages_and_answers_commands(tmp_path):
    with BotAPI() as api:
        async with telegram_host(tmp_path, api) as (runtime, store):
            assert runtime.platform.name == 'telegram' and runtime.accepting
            api.push('/id')
            await until(lambda: api.sent, 5)
            method, params = api.sent[0]
            assert method == 'sendMessage' and params['chat_id'] == GROUP
            assert params['text'] == f'场景：{SCENE}\n你的账号：telegram:7001\n机器人账号：telegram:{BOT}'
            assert params['reply_parameters']['message_id'] == 300
            api.push('普通的一句话')
            await until(lambda: store.pending_messages(SCENE), 5)
            assert len(api.sent) == 1
            api.push('/help@lenbot_fixture_bot', entities=[{'type': 'bot_command', 'offset': 0, 'length': 24}])
            await until(lambda: len(api.sent) == 2, 5)
            assert '/id' in api.sent[1][1]['text']
            stored = len(store.pending_messages(SCENE))
            api.push('/help@other_bot', entities=[{'type': 'bot_command', 'offset': 0, 'length': 15}])
            await until(lambda: len(store.pending_messages(SCENE)) > stored, 5)
            await asyncio.sleep(.1)
            assert len(api.sent) == 2


@pytest.mark.asyncio
async def test_scene_titles_come_from_the_bot_api(tmp_path):
    from len_bot.next.runtime.scene_titles import SceneTitles
    with BotAPI() as api:
        async with telegram_host(tmp_path, api) as (runtime, store):
            await until(lambda: runtime.platform.connected, 5)
            titles, errors = await SceneTitles(runtime).read(['telegram:private:7001'])
            assert errors == {}
            assert titles == {SCENE: '脱敏群', 'telegram:private:7001': '脱敏 群友'}
            assert await runtime.platform.scene_title(SCENE) == ('脱敏群', 42)


@pytest.mark.parametrize(('changes', 'message'), [
    ({'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'}, 'delivery': 'telegram'}, 'not both'),
    ({'onebot': None, 'delivery': 'telegram', 'bot_id': 'onebot:90001'}, 'bot_id telegram:'),
    ({'onebot': None, 'delivery': 'telegram', 'telegram': None}, 'requires telegram transport'),
])
def test_telegram_configuration_is_checked(tmp_path, changes, message):
    source = {'bot_id': f'telegram:{BOT}', 'owners': ['telegram:7009'],
              'telegram': {'bot_token': TOKEN}, 'scenes': {SCENE: {'persona': 'persona'}}, **changes}
    write_config(tmp_path, **source)
    with pytest.raises(ValueError, match=message):
        load_host_config(tmp_path)


def test_the_say_tool_mentions_accounts_of_the_scene_platform(tmp_path):
    from len_bot.next.chat.tools import build_tools
    write_config(tmp_path, onebot=None, delivery='telegram', bot_id=f'telegram:{BOT}', owners=['telegram:7009'],
                 telegram={'bot_token': TOKEN}, scenes={SCENE: {'persona': 'persona'}})
    config = load_host_config(tmp_path).scene_config(SCENE)
    persona = load_persona(config.persona).model_copy(update={'tools': ['say']})
    say = next(tool for tool in build_tools(config, persona, platform=True) if tool['function']['name'] == 'say')
    mention = say['function']['parameters']['properties']['mention']
    assert mention['anyOf'][0]['pattern'] == '^telegram:[1-9][0-9]*$' and 'telegram:70001' in mention['description']


def test_the_bot_token_is_a_log_secret(tmp_path):
    from len_bot.next.runtime.logs import credentials
    write_config(tmp_path, onebot=None, delivery='telegram', bot_id=f'telegram:{BOT}', owners=['telegram:7009'],
                 telegram={'bot_token': TOKEN}, scenes={SCENE: {'persona': 'persona'}})
    assert TOKEN in credentials(load_host_config(tmp_path))
