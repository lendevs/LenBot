"""New chat can pause an unread reply before the first or a later platform send."""

import asyncio
from contextlib import asynccontextmanager
import json

import pytest

from len_bot.next.chat.session import Chat
from len_bot.next.models.client import ChatModel
from len_bot.next.models.limits import speech_quota
from len_bot.next.platform.messages import SendResult, plain_text
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store

from test_next_message_reaction import incoming
from test_next_native_models import peer_server
from test_next_turn_speed import SCENE, _calls, _instance, _snapshot, _unused_wait


QUESTION = '这周团建是周几来着'
ANSWER = '团建在周六。'
SAY = ('say', {'content': ANSWER, 'reply_to': '50001', 'end_turn': True})


def receive(store, message_id, text, *, user=70002, reply_to=None, mention_bot=False):
    raw = {**incoming(), 'message_id': message_id, 'user_id': user, 'time': int(store.now())}
    segments = []
    if reply_to is not None:
        segments.append({'type': 'reply', 'data': {'id': reply_to}})
    if mention_bot:
        segments.append({'type': 'at', 'data': {'qq': '90001'}})
    segments.append({'type': 'text', 'data': {'text': text}})
    raw['message'] = segments
    store.enqueue(parse_message(raw, own_message_ids=store.own_ids(SCENE)), raw, store.now())


@asynccontextmanager
async def model_turn(root, replies):
    config, persona = _instance(root)
    config.max_steps = 3
    requests = []
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        async with ChatModel(config.model_settings('mind')) as mind:
            yield config, persona, mind, requests


def live_chat(config, persona, store, mind, sent, **kwargs):
    async def send(message, *, image_bytes=None):
        sent.append(message)
        return SendResult('sent', str(60000 + len(sent)), None)

    return Chat(config, persona, store, mind, send_message=send, now=store.now, **kwargs)


async def run(chat, *, direct=False):
    store = chat.store

    def batch():
        pending = store.pending_messages(SCENE)
        return pending[-1][0], [chat.context.batch([message for _, message, _ in pending])]

    async def append_new(continuing, turn_id):
        if not store.pending_messages(SCENE):
            return False
        assert continuing
        through, contents = batch()
        store.append_batch(SCENE, through, contents, turn_id=turn_id)
        return True

    return await chat.run_turn(batch=batch(), append_new=append_new, wait_for_messages=_unused_wait,
                               attention_state={}, direct=direct, channel='direct' if direct else 'ambient')


@pytest.mark.asyncio
@pytest.mark.parametrize(('arrival', 'reply_to', 'next_call'), [
    pytest.param('周六', 50001, ('end_turn', {}), id='quoted-answer'),
    pytest.param('周六', None, ('end_turn', {}), id='unquoted-answer'),
    pytest.param('中午吃黄焖鸡还是猪脚饭', None, SAY, id='unrelated-chat'),
])
async def test_unread_chatter_during_a_lookup_returns_once_to_the_same_mind(tmp_path, arrival, reply_to, next_call):
    replies = [_calls(('recall_chat', {'action': 'recent'}), SAY), _calls(next_call)]
    sent = []
    async with model_turn(tmp_path, replies) as (config, persona, mind, requests):
        with Store(config.database) as store:
            chat = live_chat(config, persona, store, mind, sent)
            receive(store, 50001, QUESTION, user=70001)
            execute = chat.toolset.execute
            say_calls = 0

            async def execute_as_messages_arrive(turn_id, call, *args, **kwargs):
                nonlocal say_calls
                if call.name == 'recall_chat':
                    result = await execute(turn_id, call, *args, **kwargs)
                    await asyncio.sleep(0)
                    receive(store, 50002, arrival, reply_to=reply_to)
                    return result
                elif call.name == 'say':
                    say_calls += 1
                    if say_calls == 2:
                        receive(store, 50003, '再加一份青菜', user=70003)
                return await execute(turn_id, call, *args, **kwargs)

            chat.toolset.execute = execute_as_messages_arrive
            result = await run(chat)
            assert result['status'] == 'settled' and result['failed_tools'] == 0, result
            assert result['extensions'] == 1
            first, second = (request for _, _, request in requests)
            assert first['messages'][0] == second['messages'][0]
            assert _snapshot(first) in first['messages'][-2]['content']
            assert first['messages'][-1] == second['messages'][2]
            assert arrival in second['messages'][-1]['content']
            held = next(message for message in second['messages'] if message.get('tool_call_id') == 'call-1')
            assert held['content'] == 'say 未发：发送前收到新消息，本条共 1 段均未发出（0/1）。'
            turn = store.turn_detail(SCENE, result['turn_id'])['turn']
            if next_call[0] == 'end_turn':
                assert sent == [] and result['expressions'] == []
                assert all(not message.is_self for message in store.recent(SCENE, 10))
                assert turn['first_expression_at'] is None
                assert not speech_quota(store, config).times
            else:
                assert [plain_text(message) for message in sent] == [ANSWER]
                assert len(result['expressions']) == chat.turn_messages == chat.turn_expressions == 1
                assert turn['first_expression_at'] is not None
                assert store.find_message(SCENE, '50003') is not None


@pytest.mark.asyncio
async def test_direct_wake_holds_both_says_and_completes_the_native_group(tmp_path):
    replies = [_calls(SAY, ('say', {'content': '另一段'})), _calls(('end_turn', {}))]
    sent = []
    async with model_turn(tmp_path, replies) as (config, persona, mind, requests):
        with Store(config.database) as store:
            chat = live_chat(config, persona, store, mind, sent)
            receive(store, 50001, QUESTION, user=70001, mention_bot=True)
            execute = chat.toolset.execute

            async def execute_as_direct_arrives(turn_id, call, *args, **kwargs):
                if call.name == 'say' and call.id == 'call-0':
                    receive(store, 50002, '已经确认是周六', mention_bot=True)
                return await execute(turn_id, call, *args, **kwargs)

            chat.toolset.execute = execute_as_direct_arrives
            result = await run(chat, direct=True)
            assert result['status'] == 'settled' and result['failed_tools'] == 0, result
            assert result['extensions'] == 1 and sent == [] and result['expressions'] == []
            assert chat.turn_messages == chat.turn_expressions == 0
            tools = [message for message in requests[1][2]['messages'] if message['role'] == 'tool']
            assert [(message['tool_call_id'], message['content']) for message in tools] == [
                ('call-0', 'say 未发：发送前收到新消息，本条共 1 段均未发出（0/1）。'),
                ('call-1', 'say 未发：前序表达因收到新消息暂停，本条未发。'),
            ]


@pytest.mark.asyncio
async def test_a_reply_stops_after_the_confirmed_first_part_and_recovers_without_resending(tmp_path):
    first, second = '周六下午集合。', '地点是东门。'
    say = ('say', {'content': first + second, 'reply_to': '50001', 'end_turn': True})
    sent = []
    async with model_turn(tmp_path, [_calls(say), _calls(('end_turn', {}))]) as (config, persona, mind, requests):
        config.max_steps = 1
        config.text_delivery.max_chars = len(first)
        config.text_delivery.min_interval_seconds = 0.05
        with Store(config.database) as store:
            def receipt(event):
                if event['type'] == 'message.sent':
                    chat.on_update = during_interpart_delay

            def during_interpart_delay():
                # This notification follows the receipt and quota writes. The scheduled callback
                # runs when delivery yields for the interpart delay.
                chat.on_update = None
                asyncio.get_running_loop().call_soon(receive_answer)

            def receive_answer():
                assert store.find_message(SCENE, '60001').send_status == 'sent'
                receive(store, 50002, '周六，东门集合', reply_to=50001)

            chat = live_chat(config, persona, store, mind, sent, on_trace=receipt)
            receive(store, 50001, QUESTION, user=70001)
            result = await run(chat)
            assert result['status'] == 'settled' and result['failed_tools'] == 0, result
            assert len(result['expressions']) == chat.turn_messages == chat.turn_expressions == 1
            turn = store.turn_detail(SCENE, result['turn_id'])
            assert turn['turn']['first_expression_at'] is not None
            assert len(speech_quota(store, config).times) == 1
            [tool] = turn['calls'][0]['tool_results']
            assert first in tool['content']
            assert tool['content'].endswith(f'共 2 段，第 1..1 段已发出；余段因收到新消息未发：\n{second}')
            assert result['expressions'] == [tool['content']]

        with Store(config.database) as reopened:
            chat = live_chat(config, persona, reopened, mind, sent)
            assert chat.restore()
            resumed = await run(chat)
            assert resumed['status'] == 'settled' and resumed['failed_tools'] == 0, resumed
            assert [plain_text(message) for message in sent] == [first]
            [row] = reopened.db.execute("SELECT platform_id,body FROM messages WHERE scene=? AND "
                                        "json_extract(body,'$.is_self')=1", (SCENE,)).fetchall()
            saved = json.loads(row['body'])
            assert row['platform_id'] == '60001' and saved['send_status'] == 'sent'
            assert saved['semantic_reply_to'] == '50001' and saved['reply_to'] is None
            assert not any(segment['type'] == 'reply' for segment in saved['segments'])
            assert tool in requests[1][2]['messages']
