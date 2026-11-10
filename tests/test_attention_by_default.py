"""The model declares what to keep following by default; the interjection interval is the fallback."""

import json

import pytest

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.declarations import REWAKE_SECONDS
from len_bot.next.chat.session import Chat
from len_bot.next.config import load_config
from len_bot.next.models.client import ToolCall
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message
from test_native_tool_calls import SCENE, _instance, _unused_wait


def test_a_new_config_offers_the_attention_tool(tmp_path):
    config, persona = _instance(tmp_path)
    assert config.attention.declarations is not None and config.attention.declarations.mode == 'enforce'
    with Store(config.database) as store:
        live = SceneRunner(Chat(config, persona, store, None), lambda event: None)
        assert 'attention' in live.chat.toolset.tool_names
        assert 'declared' in store.load_attention(SCENE)


@pytest.mark.parametrize('version,saved,enabled', [
    (5, None, True),                     # the panel saved the old default off as null
    (5, {'mode': 'record'}, True),
    (6, None, False),                    # from format 6 on, null turns intents off
    (6, {'mode': 'record'}, True),
])
def test_format_5_null_becomes_the_new_default_and_format_6_null_stays_off(tmp_path, version, saved, enabled):
    _instance(tmp_path)
    path = tmp_path / 'lenbot.config.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    source.update(config_version=version, attention={'only_direct': False, 'declarations': saved})
    path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
    config = load_config(tmp_path)
    assert (config.attention.declarations is not None) is enabled
    if saved is not None:
        assert config.attention.declarations.mode == 'record'


async def _intent_runner(tmp_path, now, condition, reason):
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 0
    store = Store(config.database, now=lambda: now[0])
    live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
    turn = store.start_turn(SCENE)
    await live.chat.toolset.execute(turn, ToolCall('t', 'attention', {
        'action': 'intend', 'when': [condition], 'minutes': 60, 'reason': reason}), _unused_wait)
    store.end_turn(turn, 'settled', None)
    return store, live


async def _topic_runner(tmp_path, now):
    return await _intent_runner(tmp_path, now, {'type': 'topic', 'keywords': ['新地图']}, '想接着聊新地图')


@pytest.mark.asyncio
async def test_one_intent_opens_one_turn_per_rewake_window(tmp_path):
    now = [START]
    store, live = await _topic_runner(tmp_path, now)
    with store:
        assert live.receive(message(70002, 1, '新地图今晚开'))['wake_channel'] == 'attention'
        live.state = live.consumed_state(new_turn=True)   # the turn opens on it
        woke_at = live.state.declared.find('i1').woke_at
        now[0] += REWAKE_SECONDS / 4
        held = live.receive(message(70003, 2, '新地图好大'))
        now[0] += REWAKE_SECONDS / 4
        live.receive(message(70004, 3, '新地图在哪'))
        # Not woken now: both matches wait for the end of the window and wake it once.
        assert held['wake_channel'] == 'ambient'
        assert [item['intent'] for item in live.state.declared.matches] == ['i1']
        assert live.schedule_deadline(now[0]) == woke_at + REWAKE_SECONDS
        now[0] = woke_at + REWAKE_SECONDS
        await live.ready_messages(wait=False)
        assert live.state.pending.channel == 'attention'
        live.state = live.consumed_state(new_turn=True)
        assert live.schedule_deadline(now[0]) == live.state.declared.find('i1').until
        now[0] += REWAKE_SECONDS
        assert live.receive(message(70002, 4, '新地图有隐藏关'))['wake_channel'] == 'attention'


async def _waiting_for_log(tmp_path, now):
    store, live = await _intent_runner(tmp_path, now, {'type': 'person', 'people': ['onebot:70002']}, '等他发日志')
    assert live.receive(message(70002, 1, '等下啊我找找'))['wake_channel'] == 'attention'
    live.state = live.consumed_state(new_turn=True)   # the model looks and stays silent
    return store, live


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['日志发群文件了，你看下', '6'])
async def test_a_held_reply_wakes_once_the_window_ends(tmp_path, text):
    now = [START]
    store, live = await _waiting_for_log(tmp_path, now)
    with store:
        woke_at = live.state.declared.find('i1').woke_at
        now[0] += 30
        live.receive(message(70002, 2, text))
        assert live.state.pending is None or live.state.pending.channel == 'ambient'
        assert await live.ready_messages(wait=False) is None
        assert live.schedule_deadline(now[0]) == woke_at + REWAKE_SECONDS
        # The deferred wake is kept across a restart.
        live = SceneRunner(Chat(live.config, live.chat.persona, store, None, now=lambda: now[0]), lambda event: None)
        assert live.schedule_deadline(now[0]) == woke_at + REWAKE_SECONDS
        now[0] = woke_at + REWAKE_SECONDS
        assert await live.ready_messages(wait=False) is not None   # the turn opens now
        assert live.state.pending.channel == 'attention'
        pending = store.pending_messages(SCENE)
        _, contents = live.with_freshness(live.batch(pending, live.wake_reason()), pending)
        # The held reply is the trigger, not the older message the first wake already showed.
        assert '<话题新鲜度>' in contents[-1] and '之后没有新消息' in contents[-1]


@pytest.mark.asyncio
async def test_a_turn_opened_inside_the_window_leaves_no_deferred_wake(tmp_path):
    now = [START]
    store, live = await _waiting_for_log(tmp_path, now)
    with store:
        woke_at = live.state.declared.find('i1').woke_at
        now[0] += 30
        live.receive(message(70002, 2, '6'))
        now[0] += 10
        assert live.receive(message(70003, 3, '@机器人 在吗', direct=True))['wake_channel'] == 'direct'
        live.state = live.consumed_state(new_turn=True)   # the direct turn takes the held match with it
        assert live.state.declared.matches == []
        assert live.schedule_deadline(now[0]) != woke_at + REWAKE_SECONDS
        now[0] = woke_at + REWAKE_SECONDS
        await live.ready_messages(wait=False)
        assert live.state.pending is None


@pytest.mark.asyncio
async def test_a_declared_wake_restarts_the_interjection_interval(tmp_path):
    now = [START]
    store, live = await _topic_runner(tmp_path, now)
    with store:
        assert live.state.ambient_last_at is None
        live.receive(message(70002, 1, '新地图今晚开'))
        now[0] += 5
        live.state = live.consumed_state(new_turn=True)
        assert live.state.ambient_last_at == now[0]


@pytest.mark.asyncio
async def test_an_ambient_batch_ends_with_its_freshness(tmp_path):
    now = [START]
    config, persona = _instance(tmp_path)
    config.attention.focus_seconds = 0
    with Store(config.database, now=lambda: now[0]) as store:
        live = SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)
        assert live.receive(message(70002, 1, '周末去不去看展'))['wake_channel'] == 'ambient'
        now[0] += 700
        live.receive(message(70003, 2, '我在修电脑'))
        pending = store.pending_messages(SCENE)
        _, contents = live.with_freshness(live.batch(pending, live.wake_reason()), pending)
        assert contents[-1].rstrip().endswith('</话题新鲜度>')
        assert '之后又有 1 条' in contents[-1]
