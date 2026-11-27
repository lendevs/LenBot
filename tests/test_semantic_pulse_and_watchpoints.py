"""Scene admission and persisted watchpoints across the Pulse and Mind requests."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from string import Template

import httpx
import pytest

from len_bot.next import prompt_files
from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.declarations import AttentionArguments, REWAKE_SECONDS
from len_bot.next.chat.pulse import request_pulse
from len_bot.next.chat.schedule_store import ScheduleStore
from len_bot.next.chat.session import Chat
from len_bot.next.models.client import ChatModel, ModelReply
from len_bot.next.storage.store import Store
from test_attention_protocol import START, config_for, message
from test_native_tool_calls import SCENE
from test_next_native_models import response


@asynccontextmanager
async def running(config, persona, now, pulse_reply, events):
    async with ChatModel(config.model_settings('mind')) as model:
        with Store(config.database, now=lambda: now[0]) as store:
            calls = []

            async def complete(messages, tools, *, max_output_tokens, **options):
                role = 'pulse' if max_output_tokens == 160 else 'mind'
                calls.append((role, messages, tools, options))
                content = await pulse_reply() if role == 'pulse' else '继续旁听'
                return ModelReply({'role': 'assistant', 'content': content}, content, [], 'stop', None, None)

            model.complete = complete
            runner = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), events.append)
            yield runner, store, calls


@asynccontextmanager
async def live_runner(runner):
    task = asyncio.create_task(runner.run())
    try:
        yield task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def wait_for_sample(runner, through):
    async with asyncio.timeout(5):
        while runner.state.pulse_through < through:
            await asyncio.sleep(0.001)


def configured(root, mode='active'):
    config, persona = config_for(root)
    config.attention.pulse.mode = mode
    config.attention.named_idle_seconds = 0
    return config, persona


async def silent():
    return '{"decision":"silent"}'


def roles(calls):
    return [call[0] for call in calls]


def turn_channels(events):
    return [event['channel'] for event in events if 'turn_id' in event]


def add_watch(runner, *conditions):
    return runner.declare(AttentionArguments.model_validate({
        'action': 'intend', 'when': list(conditions), 'match': 'all', 'minutes': 10, 'reason': '等地图开服时间',
    }), 'test-turn', 'test-call')['id']


@pytest.mark.asyncio
@pytest.mark.parametrize(('source', 'channel'), [
    ('private', 'direct'), ('mention', 'direct'), ('reply', 'direct'), ('focus', 'focus'), ('schedule', 'schedule'),
])
async def test_precise_wakes_bypass_pulse(tmp_path, source, channel):
    config, persona = configured(tmp_path)
    if source == 'private':
        config.scene = 'onebot:private:70001'
    now, events = [START], []
    async with running(config, persona, now, silent, events) as (runner, store, calls):
        add_watch(runner, {'type': 'topic', 'watch': '新地图的开服时间'})
        if source != 'private':
            runner.receive(message(70003, 10, f'{persona.name}在别处提过吧'))
            assert runner.state.pending.channel == 'named'
        raw = message(70001, 11, '新地图今晚开', direct=source == 'mention', reply=9 if source == 'reply' else None)
        if source == 'private':
            raw['message_type'] = 'private'
            del raw['group_id']
        elif source == 'reply':
            runner.receive(message(90001, 9, '地图几点开？'))
        elif source == 'focus':
            runner.state.followups['onebot:70001'] = START - 1
        elif source == 'schedule':
            ScheduleStore(store).create_schedule(SCENE, due_at=START, timezone='UTC', note='看开服时间',
                                                 target='self', requester='onebot:70001', limit=5)
        if source != 'schedule':
            runner.receive(raw)
        runner.close_input()
        await asyncio.wait_for(runner.run(), 5)
        assert roles(calls) == ['mind']
        assert turn_channels(events) == [channel]
        assert store.load_attention(config.scene)['pulse_through'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('channel', ['ambient', 'named'])
async def test_active_silence_preserves_messages_for_the_next_direct_turn(tmp_path, channel):
    config, persona = configured(tmp_path)
    now, events = [START], []
    async with running(config, persona, now, silent, events) as (runner, store, calls):
        text = f'刚才有人提到了{persona.name}' if channel == 'named' else '大家商量一下明天几点集合'
        offered = runner.receive(message(70003, 10, text))
        assert offered['wake_channel'] == channel
        runner.close_input()
        await asyncio.wait_for(runner.run(), 5)
        assert roles(calls) == ['pulse'] and turn_channels(events) == []
        saved = store.load_attention(SCENE)
        assert saved['pending'] is None
        assert (saved['pulse_through'], saved['pulse_last_at']) == (offered['message_seq'], START)
        if channel == 'ambient':
            assert saved['ambient_last_at'] == START
        assert store.session_through(SCENE) == 0
        assert [seq for seq, _, _ in store.pending_messages(SCENE)] == [offered['message_seq']]
        now[0] += 1
        runner.receive(message(70001, 11, '你来定个时间', direct=True))
        await asyncio.wait_for(runner.run(), 5)
        assert roles(calls) == ['pulse', 'mind'] and turn_channels(events) == ['direct']
        assert text in json.dumps(calls[-1][1], ensure_ascii=False)


@pytest.mark.asyncio
async def test_shadow_silence_records_the_verdict_and_opens_the_baseline_turn(tmp_path, caplog):
    config, persona = configured(tmp_path, 'shadow')
    now, events = [START], []
    async with running(config, persona, now, silent, events) as (runner, store, calls):
        received = runner.receive(message(70003, 10, '这个队伍还缺两个人'))
        runner.close_input()
        with caplog.at_level(logging.INFO):
            await asyncio.wait_for(runner.run(), 5)
        [log] = [record.fields for record in caplog.records if getattr(record, 'event', None) == 'semantic_pulse']
        assert log == {'mode': 'shadow', 'decision': 'silent', 'channel': 'ambient',
                       'matched_watch_ids': [], 'target_msg_id': None}
        assert roles(calls) == ['pulse', 'mind'] and turn_channels(events) == ['ambient']
        saved = store.load_attention(SCENE)
        assert (saved['pulse_through'], saved['pulse_last_at']) == (received['message_seq'], START)


@pytest.mark.asyncio
async def test_direct_message_supersedes_an_in_flight_pulse(tmp_path):
    config, persona = configured(tmp_path)
    now, events = [START], []
    started, cancelled, turned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def in_flight():
        assert not runner.execution.locked()
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def emit(event):
        events.append(event)
        if event.get('channel') == 'direct' and event.get('status') == 'settled':
            turned.set()

    async with running(config, persona, now, in_flight, events) as (runner, store, calls):
        runner.emit = emit
        runner.receive(message(70003, 10, '这个队伍还缺两个人'))
        async with live_runner(runner) as task:
            await asyncio.wait_for(started.wait(), 5)
            runner.receive(message(70001, 11, '算上我', direct=True))
            await asyncio.wait_for(turned.wait(), 5)
            assert cancelled.is_set()
            runner.close_input()
            await asyncio.wait_for(task, 5)
        assert roles(calls) == ['pulse', 'mind'] and turn_channels(events) == ['direct']
        saved = store.load_attention(SCENE)
        assert saved['pulse_through'] == 0 and saved['pulse_last_at'] is None
        assert '算上我' in json.dumps(calls[-1][1], ensure_ascii=False)


@pytest.mark.asyncio
async def test_silent_pulse_keeps_a_new_named_candidate(tmp_path):
    config, persona = configured(tmp_path)
    config.attention.pulse.sample_interval_seconds = 120
    now, events = [START], []
    started, finish = asyncio.Event(), asyncio.Event()

    async def in_flight():
        started.set()
        await finish.wait()
        return await silent()

    async with running(config, persona, now, in_flight, events) as (runner, store, calls):
        first = runner.receive(message(70001, 10, f'刚才提到{persona.name}'))
        async with live_runner(runner):
            await asyncio.wait_for(started.wait(), 5)
            now[0] += 1
            second = runner.receive(message(70002, 11, f'另一个人在找{persona.name}'))
            finish.set()
            await wait_for_sample(runner, first['message_seq'])
            saved = store.load_attention(SCENE)
            assert saved['pulse_through'] == first['message_seq']
            assert saved['pending']['channel'] == 'named'
            assert saved['pending']['first_at'] == START + 1
            assert saved['pending']['people'] == ['onebot:70002']
            assert roles(calls) == ['pulse']
            now[0] = saved['pulse_last_at'] + 120
            runner.changed.set()
            await wait_for_sample(runner, second['message_seq'])
            assert roles(calls) == ['pulse', 'pulse'] and turn_channels(events) == []
            assert '另一个人在找' in calls[-1][1][-1]['content']


@pytest.mark.asyncio
async def test_active_named_wakes_share_the_pulse_interval(tmp_path):
    config, persona = configured(tmp_path)
    config.attention.pulse.sample_interval_seconds = 120
    now, events = [START], []

    async with running(config, persona, now, silent, events) as (runner, _, calls):
        first = runner.receive(message(70001, 10, f'有人提到{persona.name}'))
        async with live_runner(runner):
            await wait_for_sample(runner, first['message_seq'])
            now[0] = START + 1
            second = runner.receive(message(70002, 11, f'刚刚有人在找{persona.name}'))
            assert second['wake_channel'] == 'named'
            assert await runner.ready_messages(wait=False, sample_watch=True) is None
            assert roles(calls) == ['pulse'] and turn_channels(events) == []
            now[0] = START + 120
            runner.changed.set()
            await wait_for_sample(runner, second['message_seq'])
            assert roles(calls) == ['pulse', 'pulse'] and turn_channels(events) == []
            assert runner.state.pulse_last_at == START + 120


@pytest.mark.asyncio
async def test_shadow_samples_watch_without_opening_mind(tmp_path, caplog):
    config, persona = configured(tmp_path, 'shadow')
    config.attention.pulse.sample_interval_seconds = 120
    now, events = [START], []

    async def matched():
        return '{"decision":"wake","target_msg_id":"11","matched_watch_ids":["i1"]}'

    async with running(config, persona, now, matched, events) as (runner, store, calls):
        add_watch(runner, {'type': 'topic', 'watch': '新地图的开服时间'})
        first = runner.receive(message(70003, 10, '地图时间还没定', reply=1))
        assert first['wake_channel'] is None
        async with live_runner(runner):
            await wait_for_sample(runner, first['message_seq'])
            now[0] = START + 1
            second = runner.receive(message(70003, 11, '今晚八点开放', reply=1))
            assert second['wake_channel'] is None
            assert await runner.ready_messages(wait=False, sample_watch=True) is None
            assert roles(calls) == ['pulse']
            now[0] = START + 120
            with caplog.at_level(logging.INFO):
                caplog.clear()
                runner.changed.set()
                await wait_for_sample(runner, second['message_seq'])
        assert roles(calls) == ['pulse', 'pulse'] and turn_channels(events) == []
        assert '候选渠道 watch' in calls[-1][1][-1]['content']
        saved = store.load_attention(SCENE)
        assert (saved['pulse_through'], saved['pulse_last_at']) == (second['message_seq'], START + 120)
        assert saved['declared']['matches'] == []
        [log] = [record.fields for record in caplog.records if getattr(record, 'event', None) == 'semantic_pulse']
        assert log == {'mode': 'shadow', 'decision': 'wake', 'channel': 'watch',
                       'matched_watch_ids': ['i1'], 'target_msg_id': '11'}


@pytest.mark.asyncio
async def test_watch_all_checks_the_pulse_target_message(tmp_path):
    config, persona = configured(tmp_path)
    now, events = [START], []

    async def matched():
        return '{"decision":"wake","target_msg_id":"11","matched_watch_ids":["i1"]}'

    async with running(config, persona, now, matched, events) as (runner, store, calls):
        add_watch(runner, {'type': 'person', 'people': ['onebot:70001']},
                  {'type': 'topic', 'watch': '新地图的开服时间'})
        runner.receive(message(70001, 10, '今天外卖到了', reply=1))
        target = runner.receive(message(70002, 11, '今晚八点开服', reply=1))
        runner.close_input()
        await asyncio.wait_for(runner.run(), 5)
        assert roles(calls) == ['pulse'] and turn_channels(events) == []
        assert all(body in calls[0][1][-1]['content'] for body in ('今天外卖到了', '今晚八点开服'))
        saved = store.load_attention(SCENE)
        assert saved['pulse_through'] == target['message_seq'] and saved['declared']['matches'] == []


@pytest.mark.asyncio
async def test_pulse_uses_the_fallback_anthropic_thinking_budget(tmp_path):
    config, persona = configured(tmp_path)
    config.models.providers['synthetic'].api = 'anthropic'
    binding = config.models.roles.mind
    binding.temperature = None
    binding.thinking_budget_tokens = 1024
    binding.max_output_tokens = 2048
    body = response('anthropic')
    body['content'][0]['text'] = '{"decision":"silent"}'
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    settings = config.model_settings('mind')
    async with ChatModel(settings) as model:
        await model._client.aclose()
        model._client = httpx.AsyncClient(base_url=settings.base_url, transport=httpx.MockTransport(respond))
        with Store(config.database) as store:
            chat = Chat(config, persona, store, model)
            verdict = await request_pulse(chat, model, [{'role': 'user', 'content': '地图今晚开'}])
    [request] = requests
    assert request['max_tokens'] == 1184
    assert request['thinking'] == {'type': 'enabled', 'budget_tokens': 1024}
    assert verdict is not None and verdict.decision == 'silent'


@pytest.mark.asyncio
@pytest.mark.parametrize('require_person', [False, True])
async def test_watch_matches_and_rewakes_only_after_the_intent_window(tmp_path, require_person):
    config, persona = configured(tmp_path)
    config.attention.pulse.sample_interval_seconds = 10
    now, events = [START], []
    target = '10'

    async def matched():
        return '```json\n' + json.dumps({'decision': 'wake', 'target_msg_id': target, 'matched_watch_ids': ['i1']}) + '\n```'

    async with running(config, persona, now, matched, events) as (runner, store, calls):
        conditions = [{'type': 'topic', 'watch': '等新地图开放的时间'}]
        if require_person:
            conditions.insert(0, {'type': 'person', 'people': ['onebot:70002']})
        intent = add_watch(runner, *conditions)
        assert intent == 'i1'
        target_uids = []
        run_turn = runner.chat.run_turn

        async def record_targets(**kwargs):
            target_uids.append(kwargs['target_uids'])
            return await run_turn(**kwargs)

        runner.chat.run_turn = record_targets
        runner.close_input()
        runner.receive(message(70003, 10, '新地图今晚开', reply=1))
        assert runner.state.pending is None
        await asyncio.wait_for(runner.run(), 5)
        if require_person:
            assert roles(calls) == ['pulse'] and turn_channels(events) == []
            now[0] += 10
            target = '12'
            runner.receive(message(70003, 11, '对，时间定了', reply=1))
            runner.receive(message(70002, 12, '今晚八点开', reply=1))
            await asyncio.wait_for(runner.run(), 5)
            assert roles(calls) == ['pulse', 'pulse', 'mind']
        else:
            assert roles(calls) == ['pulse', 'mind']
        assert turn_channels(events) == ['attention']
        assert target_uids == [('onebot:70002' if require_person else 'onebot:70003',)]
        first_wake = now[0]

        now[0] += 5
        target = '13'
        runner.receive(message(70002, 13, '改成九点了', reply=1))
        await asyncio.wait_for(runner.run(), 5)
        assert runner.state.pulse_last_at == first_wake
        now[0] += 5
        await asyncio.wait_for(runner.run(), 5)
        assert roles(calls)[-1] == 'pulse' and runner.state.pulse_last_at == now[0]
        assert turn_channels(events) == ['attention']
        assert store.load_attention(SCENE)['declared']['matches'][0]['message_id'] == '13'
        assert runner.schedule_deadline(now[0]) == first_wake + REWAKE_SECONDS

        now[0] = first_wake + REWAKE_SECONDS
        await asyncio.wait_for(runner.run(), 5)
        assert roles(calls)[-2:] == ['pulse', 'mind'] and turn_channels(events) == ['attention', 'attention']
        assert runner.state.declared.find(intent).woke_at == now[0]


def test_local_watch_fallback_and_legacy_keywords_json(tmp_path):
    config, persona = configured(tmp_path)
    with Store(config.database, now=lambda: START) as store:
        runner = SceneRunner(Chat(config, persona, store, None, now=lambda: START), lambda _: None)
        watch = add_watch(runner, {'type': 'topic', 'watch': '有人讨论：新地图，怎么开放？'})
        legacy = add_watch(runner, {'type': 'topic', 'keywords': ['新地图']})
        runner = SceneRunner(Chat(config, persona, store, None, now=lambda: START), lambda _: None)
        assert runner.state.declared.find(legacy).conditions == [{'type': 'topic', 'keywords': ['新地图']}]
        assert runner.receive(message(70003, 10, '今晚新地图开'))['wake_channel'] == 'attention'
        assert [match['intent'] for match in runner.state.declared.matches] == [watch, legacy]


def test_pulse_prompt_has_the_three_checked_template_slots():
    name = 'next_pulse.md'
    content = prompt_files.bundled(name)
    prompt_files.check(name, content)
    assert set(Template(content).get_identifiers()) == {'name', 'brief', 'aliases'}
