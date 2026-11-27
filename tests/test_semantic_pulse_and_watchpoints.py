"""Scene admission and persisted watchpoints across the Pulse and Mind requests."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from string import Template

import pytest

from len_bot.next import prompt_files
from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.declarations import AttentionArguments, REWAKE_SECONDS
from len_bot.next.chat.schedule_store import ScheduleStore
from len_bot.next.chat.session import Chat
from len_bot.next.models.client import ChatModel, ModelReply
from len_bot.next.storage.store import Store
from test_attention_protocol import START, config_for, message
from test_native_tool_calls import SCENE


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
    started, finish = asyncio.Event(), asyncio.Event()

    async def in_flight():
        assert not runner.execution.locked()
        started.set()
        await finish.wait()
        return await silent()

    async with running(config, persona, now, in_flight, events) as (runner, store, calls):
        runner.receive(message(70003, 10, '这个队伍还缺两个人'))
        runner.close_input()
        task = asyncio.create_task(runner.run())
        try:
            await asyncio.wait_for(started.wait(), 5)
            runner.receive(message(70001, 11, '算上我', direct=True))
            finish.set()
            await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert roles(calls) == ['pulse', 'mind'] and turn_channels(events) == ['direct']
        saved = store.load_attention(SCENE)
        assert saved['pulse_through'] == 0 and saved['pulse_last_at'] is None
        assert '算上我' in json.dumps(calls[-1][1], ensure_ascii=False)


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
            runner.receive(message(70002, 11, '对，时间定了', reply=1))
            runner.receive(message(70003, 12, '今晚八点开', reply=1))
            await asyncio.wait_for(runner.run(), 5)
            assert roles(calls) == ['pulse', 'pulse', 'mind']
        else:
            assert roles(calls) == ['pulse', 'mind']
        assert turn_channels(events) == ['attention']
        assert target_uids == [('onebot:70003',)]
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
