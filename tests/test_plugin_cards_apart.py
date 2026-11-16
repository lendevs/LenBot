"""Plugin cards go out under the bot's account but are not the bot speaking: a burst of them leaves the speech pace,
the count of what the bot said, and follow-ups to the model's own words."""

import asyncio
import json

import pytest

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.session import Chat
from len_bot.next.models.client import ChatModel
from len_bot.next.models.limits import speech_quota
from len_bot.plugin import Text
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message, response
from test_native_tool_calls import SCENE, _instance
from test_next_native_models import peer_server


@pytest.mark.asyncio
async def test_a_burst_of_plugin_cards_leaves_the_bot_free_to_join_in(tmp_path):
    config, persona = _instance(tmp_path)
    config.limits.messages_per_hour = 2
    config.attention.speech_burst, config.attention.speech_interval_seconds = 1, 600
    config.attention.focus_seconds = 120
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    requests, now = [], [START]
    server = await peer_server([response('say', {'content': '我也想看', 'end_turn': True}, 'call-0')], requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                live = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), lambda _: None)
                live.closing = True
                for index in range(4):
                    sent = await live.chat.expression.send_plugin_content(
                        'bilibili', [Text(f'合成主播{index} 开播了')], reply_to=None)
                    assert sent.status == 'simulated'
                    now[0] += 1
                assert speech_quota(store, config).used == 0 and live.pace_until() is None
                assert store.own_expressions_after(SCENE, 0) == [] and live.state.followups == {}
                live.receive(message(70001, 1, '今晚谁一起看直播？'))
                assert live.state.pending.channel == 'ambient'
                await asyncio.wait_for(live.run(), 5)
                assert speech_quota(store, config).used == 1
                assert [entry.segments[0].data['text'] for _, entry in store.own_expressions_after(SCENE, 0)] == ['我也想看']
                assert set(live.state.followups) == {'*'}
    assert len(requests) == 1
    attention = json.dumps(requests[0], ensure_ascii=False)
    assert '你说了 0 句' in attention
    # The cards still reach the model, marked as the plugin's and not its own words.
    assert '[插件 bilibili 在本场景直接发送' in attention and '这条没有经过你' in attention
