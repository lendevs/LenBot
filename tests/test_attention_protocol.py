"""Model tool and OneBot boundaries for persistent attention; loopback HTTP, no paid calls."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.declarations import AttentionArguments
from len_bot.next.chat.session import Chat
from len_bot.next.configuration.chat import AttentionDeclarations, TurnDisposition
from len_bot.next.models.client import ChatModel, ToolCall
from len_bot.next.storage.store import Store
from test_native_tool_calls import SCENE, _instance, _unused_wait
from test_next_native_models import peer_server

START = 1790000000.0


def message(user, ident, text, *, direct=False, reply=None):
    segments = [{'type': 'text', 'data': {'text': text}}]
    if direct:
        segments.insert(0, {'type': 'at', 'data': {'qq': '90001'}})
    if reply is not None:
        segments.insert(0, {'type': 'reply', 'data': {'id': str(reply)}})
    return {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
            'user_id': user, 'message_id': ident, 'time': int(START),
            'sender': {'nickname': '匿名成员', 'role': 'member'}, 'message': segments}


def response(name, args, ident):
    body = {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]},
        'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
    return 200, 'application/json', json.dumps(body).encode()


def config_for(root, mode='enforce'):
    config, persona = _instance(root)
    config.attention.declarations = AttentionDeclarations(mode=mode)
    config.attention.disposition = TurnDisposition(mode='record' if mode == 'record' else 'enforce')
    config.attention.activity = 0
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    config.attention.direct_idle_seconds = config.attention.focus_idle_seconds = 0
    return config, persona


@pytest.mark.parametrize('args', [
    {'action': 'resolve'}, {'action': 'drop', 'id': 'i1', 'reason': 'extra'},
    {'action': 'intend', 'when': [], 'minutes': 2, 'reason': '等待'},
    {'action': 'intend', 'when': [{'type': 'at', 'minutes': 2}], 'minutes': 2, 'reason': '等待'},
    {'action': 'intend', 'when': [{'type': 'at', 'minutes': 3}], 'minutes': 2, 'reason': '等待'},
    {'action': 'intend', 'when': [{'type': 'at', 'minutes': 1}, {'type': 'person', 'people': ['onebot:1']}],
     'match': 'all', 'minutes': 2, 'reason': '等待'},
    {'action': 'intend', 'when': [{'type': 'topic', 'keywords': [' ']}], 'minutes': 2, 'reason': '等待'},
    {'action': 'intend', 'when': [{'type': 'person', 'people': ['unqualified']}], 'minutes': 2, 'reason': '等待'},
])
def test_tool_rejects_incomplete_or_unexecutable_conditions(args):
    with pytest.raises(ValidationError):
        AttentionArguments.model_validate(args)


@pytest.mark.parametrize('value', [{'max_intents': 0}, {'max_minutes': 0}, {'max_conditions': True}, {'sweep_pressure': 2}])
def test_configuration_rejects_invalid_bounds_and_removed_experiments(value):
    with pytest.raises(ValidationError):
        AttentionDeclarations.model_validate(value)


@pytest.mark.asyncio
async def test_model_intent_survives_unrelated_closed_turn_and_restart(tmp_path):
    config, persona = config_for(tmp_path)
    closed = {'state': 'closed', 'minutes': 5}
    replies = [
        response('attention', {'action': 'intend', 'when': [{'type': 'person', 'people': ['onebot:70001']}],
                              'minutes': 60, 'reason': '等待报错日志', 'end_turn': True, 'disposition': closed}, 'c1'),
        response('end_turn', {'disposition': closed}, 'c2'),
        response('attention', {'action': 'keep', 'id': 'i1', 'end_turn': True}, 'c3'),
        response('attention', {'action': 'resolve', 'id': 'i1', 'end_turn': True, 'disposition': closed}, 'c4'),
    ]
    requests, events, now = [], [], [START]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                def runner():
                    value = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), events.append)
                    value.closing = True
                    return value
                live = runner()
                live.receive(message(70001, 1, '安装失败', direct=True))
                await asyncio.wait_for(live.run(), 5)
                assert live.state.declared.find('i1').reason == '等待报错日志'
                now[0] += 10
                live.receive(message(70002, 2, '天气如何', direct=True))
                await asyncio.wait_for(live.run(), 5)
                assert live.state.disposition.state == 'closed'
                live = runner()
                now[0] += 10
                receipt = live.receive(message(70001, 3, '先去吃饭'))
                assert receipt['wake_verdict']['woke'] and receipt['wake_verdict']['channel'] == 'attention'
                assert live.state.pending.channel == 'attention'
                await asyncio.wait_for(live.run(), 5)
                assert live.state.declared.find('i1')
                now[0] += 10
                live.receive(message(70001, 4, '报错日志如下'))
                await asyncio.wait_for(live.run(), 5)
                assert live.state.declared.intents == []
                now[0] += 1
                live.receive(message(70001, 5, '吃完了'))
                assert live.state.pending is None
    turns = [event for event in events if 'turn_id' in event]
    assert len(turns) == len(requests) == 4
    assert all(turn['status'] == 'settled' and turn['failed_tools'] == 0 for turn in turns)
    assert '本轮候选' in json.dumps(requests[-1][2], ensure_ascii=False)
    assert 'i1' in json.dumps(requests[-1][2], ensure_ascii=False)


@pytest.mark.asyncio
async def test_timer_wakes_without_messages_once_and_expires(tmp_path):
    config, persona = config_for(tmp_path)
    requests, events, now = [], [], [START]
    replies = [response('attention', {'action': 'intend', 'when': [{'type': 'at', 'minutes': 1}],
                'minutes': 3, 'reason': '查看赛果', 'end_turn': True}, 't1'),
               response('attention', {'action': 'keep', 'id': 'i1', 'end_turn': True}, 't2')]
    server = await peer_server(replies, requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                live = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), events.append)
                live.closing = True
                live.receive(message(70001, 1, '稍后查看赛果', direct=True))
                await asyncio.wait_for(live.run(), 5)
                assert live.schedule_deadline(now[0]) == START + 60
                now[0] += 60
                await asyncio.wait_for(live.run(), 5)
                assert len(requests) == 2
                assert live.state.declared.find('i1')
                await asyncio.wait_for(live.run(), 5)
                assert len(requests) == 2
                now[0] = START + 180
                await live.ready_messages(wait=False)
                assert live.state.declared.intents == []
                assert live.schedule_deadline(now[0]) is None
    assert [event['channel'] for event in events if 'turn_id' in event] == ['direct', 'attention']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['record', 'context'])
async def test_nonexecuting_modes_keep_baseline_wakes_and_validate_tool_actions(tmp_path, mode):
    config, persona = config_for(tmp_path, mode)
    config.attention.focus_seconds = 0
    now = [START]
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        turn = store.start_turn(SCENE)
        tool = ToolCall('x1', 'attention', {'action': 'intend', 'when': [{'type': 'person', 'people': ['onebot:70001']}],
                                        'minutes': 10, 'reason': '等待'})
        result, _, _ = await live.chat.toolset.execute(turn, tool, _unused_wait)
        assert json.loads(result)['id'] == 'i1'
        live.receive(message(70001, 1, '补充信息'))
        assert live.state.pending is None
        with pytest.raises(ValueError, match='没有生效'):
            await live.chat.toolset.execute(turn, ToolCall('x2', 'attention', {'action': 'resolve', 'id': 'missing'}), _unused_wait)
        assert live.state.declared.find('i1')
        with pytest.raises(ValueError, match='closed'):
            await live.chat.toolset.execute(turn, ToolCall('x3', 'end_turn', {'disposition': {
                'state': 'closed', 'minutes': 2, 'people': ['onebot:70001']}}), _unused_wait)
        assert live.chat.toolset.turn_disposition is None


@pytest.mark.asyncio
async def test_disabled_tool_is_not_executable_and_off_state_keeps_original_shape(tmp_path):
    config, persona = _instance(tmp_path)
    with Store(config.database) as store:
        live = SceneRunner(Chat(config, persona, store, None), lambda event: None)
        assert 'declared' not in store.load_attention(SCENE)
        assert 'disposition' not in store.load_attention(SCENE)
        assert not {'attention', 'end_turn'} & live.chat.toolset.tool_names
        turn = store.start_turn(SCENE)
        with pytest.raises(ValueError, match='未开放'):
            await live.chat.toolset.execute(turn, ToolCall('x', 'attention', {'action': 'drop', 'id': 'i1'}), _unused_wait)


@pytest.mark.asyncio
async def test_candidates_batch_without_resolving_and_all_filters_unrelated_messages(tmp_path):
    config, persona = config_for(tmp_path)
    config.attention.focus_seconds = 0
    now = [START]
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        turn = store.start_turn(SCENE)
        for ident, match in [('any', 'any'), ('all', 'all')]:
            await live.chat.toolset.execute(turn, ToolCall(ident, 'attention', {
                'action': 'intend', 'when': [{'type': 'person', 'people': ['onebot:70001']},
                                            {'type': 'topic', 'keywords': ['日志']}],
                'match': match, 'minutes': 10, 'reason': ident}), _unused_wait)
        live.receive(message(70001, 1, '闲聊'))
        assert [item['intent'] for item in live.state.declared.matches] == ['i1']
        live.receive(message(70001, 2, '日志如下'))
        assert [item['intent'] for item in live.state.declared.matches] == ['i1', 'i2']
        assert live.state.pending.channel == 'attention'
        assert len(live.state.declared.intents) == 2
        # Duplicate platform delivery must not add another candidate.
        live.receive(message(70001, 2, '日志如下'))
        assert len(live.state.declared.matches) == 2
        await live.chat.toolset.execute(turn, ToolCall('drop', 'attention', {'action': 'drop', 'id': 'i1'}), _unused_wait)
        assert [item['intent'] for item in live.state.declared.matches] == ['i2']
        await live.chat.toolset.execute(turn, ToolCall('resolve', 'attention', {'action': 'resolve', 'id': 'i2'}), _unused_wait)
        assert live.state.pending is None


@pytest.mark.asyncio
async def test_attention_respects_blacklist_only_direct_and_quiet_and_role_removal(tmp_path):
    config, persona = config_for(tmp_path)
    config.attention.focus_seconds = 0
    now = [START]
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        turn = store.start_turn(SCENE)
        await live.chat.toolset.execute(turn, ToolCall('create', 'attention', {
            'action': 'intend', 'when': [{'type': 'topic', 'keywords': ['日志']}],
            'minutes': 10, 'reason': '等待日志'}), _unused_wait)
        live.receive(message(70005, 1, '日志'))  # Existing fixture blacklists this account.
        assert live.state.pending is None and live.state.declared.matches == []
        config.attention.only_direct = True
        live.receive(message(70001, 2, '日志'))
        assert live.state.pending is None
        config.attention.only_direct = False
        live.set_temporary_quiet(30, 'allow', 'onebot:70001')
        live.receive(message(70001, 3, '日志'))
        assert live.state.pending is None
        now[0] += 31
        live.receive(message(70001, 4, '日志'))
        assert live.state.pending.channel == 'attention'
        persona.tools = ['say']
        restarted = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        assert restarted.state.declared is None and restarted.state.pending is None
        assert 'attention' not in restarted.chat.toolset.tool_names


@pytest.mark.asyncio
async def test_context_timer_does_not_schedule_execution_and_expiry_cancels_queued_candidate(tmp_path):
    config, persona = config_for(tmp_path, 'context')
    config.attention.focus_seconds = 0
    now = [START]
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        turn = store.start_turn(SCENE)
        await live.chat.toolset.execute(turn, ToolCall('timer', 'attention', {
            'action': 'intend', 'when': [{'type': 'at', 'minutes': 1}],
            'minutes': 2, 'reason': '稍后检查'}), _unused_wait)
        store.end_turn(turn, 'settled')
        assert live.schedule_deadline(now[0]) == START + 120
        now[0] += 60
        assert await live.ready_messages(wait=False) is None
        config.attention.declarations.mode = 'enforce'
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        await live.ready_messages(wait=False)
        assert live.state.pending.channel == 'attention'
        now[0] = START + 120
        assert await live.ready_messages(wait=False) is None
        assert live.state.pending is None


class Draws:
    def __init__(self, *values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def test_exploration_draws_only_outside_rules_and_yields_to_ambient(tmp_path):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 0
    config.attention.explore_probability = 0.25
    now = [START]
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        live.random = Draws(0.5, 0.1)
        live.receive(message(70001, 1, '哈哈'))
        assert live.state.pending is None
        live.receive(message(70002, 2, '哈哈'))
        assert (live.state.pending.channel, live.state.pending.score) == ('explore', 0.0)
        assert live.wake_reason() == '[群里在聊]'
        assert live.deadline() == START + config.attention.focus_idle_seconds
        live.receive(message(70003, 3, '你们觉得怎么办？'))
        assert (live.state.pending.channel, live.state.pending.explored) == ('ambient', True)
        assert live.random.values == []
        live.receive(message(70001, 4, '下雨了', direct=True))
        assert (live.state.pending.channel, live.state.pending.explored) == ('direct', True)


def test_participation_wake_can_hide_its_score(tmp_path):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 0
    now = [START]
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        for seq, text in enumerate(('哈哈', '哈哈', '你们觉得怎么办？'), 1):
            live.receive(message(70001 + seq, seq, text))
        assert live.state.pending.channel == 'ambient'
        assert live.wake_reason() == f'[群里在聊；参与分 {live.state.pending.score:.3f}]'
        config.attention.ambient_score_in_reason = False
        assert live.wake_reason() == '[群里在聊]'


def test_exploration_off_keeps_rule_wakes(tmp_path):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 0
    with Store(config.database, now=lambda: START) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: START), lambda event: None)
        live.random = Draws()
        live.receive(message(70001, 1, '哈哈'))
        assert live.state.pending is None
        live.receive(message(70002, 2, '你们觉得怎么办？'))
        assert (live.state.pending.channel, live.state.pending.explored) == ('ambient', False)


@pytest.mark.asyncio
async def test_exploration_draw_stays_on_turn_after_ambient_takes_over(tmp_path):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 0
    config.attention.explore_probability = 0.25
    now, turns = [START], []
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        live.random = Draws(0.1)
        live.closing = True

        async def turn(channel, **kwargs):
            turns.append((channel, kwargs['channels']))
            live.state.pending = None

        live._turn = turn
        live.receive(message(70001, 1, '哈哈'))
        live.receive(message(70002, 2, '你们觉得怎么办？'))
        now[0] += config.attention.focus_max_seconds
        await asyncio.wait_for(live.run(), 5)
    assert turns == [('ambient', {'ambient', 'explore'})]


@pytest.mark.asyncio
async def test_silent_exploration_turn_keeps_ambient_backoff(tmp_path):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 0
    config.attention.activity = 0
    config.attention.explore_probability = 1
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '不接话'}, 'finish_reason': 'stop'}],
                       'usage': {'prompt_tokens': 100, 'completion_tokens': 4}}).encode()
    requests, events, now = [], [], [START]
    server = await peer_server([(200, 'application/json', body)], requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                live = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), events.append)
                live.closing = True
                live.receive(message(70001, 1, '今天吃什么'))
                assert live.state.pending.channel == 'explore'
                now[0] += config.attention.focus_max_seconds
                await asyncio.wait_for(live.run(), 5)
    [turn] = [event for event in events if 'turn_id' in event]
    assert (turn['channel'], turn['status'], turn['silence_level']) == ('explore', 'settled', 0)
    assert '[群里在聊]' in json.dumps(requests[0][2], ensure_ascii=False)
    assert '参与分' not in json.dumps(requests[0][2], ensure_ascii=False)


def test_chat_status_names_the_reason_and_when_it_changes(tmp_path):
    from len_bot.next.configuration.chat import QuietHours
    from len_bot.next.models.limits import record_speech
    config, persona = config_for(tmp_path)
    config.attention.quiet_hours = QuietHours(start='23:00', end='07:00')
    config.limits.messages_per_hour = 1
    now = [START]
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        # START is 14:13:20 UTC; the configured quiet hours begin at 23:00.
        assert live.chat_status() == {'status': 'chatting', 'changes_at': START + 31600}
        record_speech(store, SCENE)
        assert live.chat_status() == {'status': 'limited', 'changes_at': START + 3600}
        live.set_temporary_quiet(600, 'allow', None)
        assert live.chat_status() == {'status': 'quiet', 'changes_at': START + 600}
        live.set_paused(True)
        assert live.chat_status() == {'status': 'paused', 'changes_at': None}


@pytest.mark.asyncio
@pytest.mark.parametrize(('channel', 'idle', 'maximum'), [('direct', 1.5, 4), ('named', 3, 8), ('focus', 4, 12)])
async def test_onebot_bursts_wait_for_image_caption_extend_same_speaker_and_keep_channel_cap(channel, idle, maximum):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location('latency_cases', Path(__file__).parents[1] / 'scripts/first_reply_latency.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    measured = await module.batches()
    rows = {row['case']: row for row in measured['rows'] if row['channel'] == channel}
    assert rows['single-text']['first_batch_seconds'] == idle
    assert rows['same-speaker']['first_batch_seconds'] == pytest.approx(idle * 1.4)
    assert rows['different-speaker']['first_batch_seconds'] == idle
    assert rows['several-speakers']['first_batch_seconds'] == idle
    assert rows['image-only']['first_batch_seconds'] == min(idle * 2, maximum)
    assert rows['image-then-caption']['consumed'] == [0, 1]
    assert not rows['image-then-caption']['cut']
    assert rows['at-cap']['first_batch_seconds'] == maximum
    assert all(row['within_cap'] and row['model_requests'] == 0 for row in rows.values())
