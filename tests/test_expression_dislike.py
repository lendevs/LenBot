"""Learned expressions whose verbatim use drew corrections or dislike rank behind the rest, without review changes."""

import json

import pytest

from len_bot.next.chat.session import Chat
from len_bot.next.configuration.learning import LearningSettings
from len_bot.next.learning.store import LearningStore
from len_bot.next.models.client import ChatModel
from len_bot.next.storage.store import Store
from test_native_tool_calls import SCENE, _instance, _no_new_messages, _receive, _unused_wait
from test_next_native_models import peer_server

STYLES = ['冲冲冲', '走起走起', '安排上了', '我也来', '算我一个', '马上上线']


def _adopt(store: Store) -> list[int]:
    records = LearningStore(store)
    records.initialize(SCENE, 0)
    batch = records.begin(SCENE, 0, 1, {})
    records.complete(batch, [(f'有人约周末打游戏{index}', style, []) for index, style in enumerate(STYLES)],
                     auto_adopt=True)
    return [item['id'] for item in sorted(records.adopted(SCENE), key=lambda item: item['id'])]


def _used(store: Store, turn: str, offered: list[int], text: str, reaction: str, *, scene: str = SCENE) -> None:
    """A turn offered ``offered``, said ``text`` and the group reacted with ``reaction``."""
    _receive(store, 70009, 59000 + store.max_message_seq(SCENE), text)
    seq = store.max_message_seq(SCENE)
    now = store.now()
    with store.db:
        # Only the offered ids of the recorded request matter here; an unfinished call is no usage anchor.
        store.db.execute("INSERT INTO model_calls(turn_id,role,started,request,scene) VALUES (?,?,?,?,?)",
                         (turn, 'mind', now, json.dumps({'expression_ids': offered}), scene))
        store.db.execute(
            "INSERT INTO reply_effects(scene,entry_seq,turn_id,channels,message_seqs,planned_parts,first_sent_at,"
            "last_sent_at,deadline,observed_seqs,closed_at,reaction,reason) VALUES (?,?,?,?,?,1,?,?,?,'[1]',?,?,?)",
            (scene, seq, turn, '["ambient"]', json.dumps([seq]), now, now, now + 180, now + 180, reaction, '合成判定'))


def test_only_verbatim_use_followed_by_correction_or_dislike_counts(tmp_path):
    config, _ = _instance(tmp_path)
    with Store(config.database) as store:
        ids = _adopt(store)
        _used(store, 't1', ids[:3], '冲冲冲！周末见', 'negative')
        _used(store, 't2', ids[:3], '冲冲冲，安排上了', 'correct')
        # Offered but not used, used but not offered, or welcomed: none of these count.
        _used(store, 't3', ids[3:], '冲冲冲', 'negative')
        _used(store, 't4', ids[:2], '走起走起', 'continue')
        _used(store, 't5', [], '算我一个', 'negative')
        assert LearningStore(store).disliked(SCENE, 0) == {ids[0]: 2, ids[2]: 1}
        assert LearningStore(store).disliked(SCENE, store.now() + 1) == {}
        listed = {item['id']: item['disliked'] for item in LearningStore(store).expressions(
            SCENE, status='adopted', limit=20, offset=0)['items']}
        assert listed[ids[0]] == 2 and listed[ids[1]] == 0
        assert {item['status'] for item in LearningStore(store).expressions(
            SCENE, status=None, limit=20, offset=0)['items']} == {'adopted'}


@pytest.mark.asyncio
@pytest.mark.parametrize('disliked', [False, True])
async def test_disliked_expression_drops_out_of_the_five_shown_to_the_mind(tmp_path, disliked):
    config, persona = _instance(tmp_path)
    config.learning = LearningSettings(extract=False)
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    received = []
    body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '合成结束'}, 'finish_reason': 'stop'}],
                       'usage': {'prompt_tokens': 100, 'completion_tokens': 4}}).encode()
    server = await peer_server([(200, 'application/json', body)], received)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database) as store:
            ids = _adopt(store)
            if disliked:
                _used(store, 'old', ids, '冲冲冲', 'negative', scene=SCENE)
            _receive(store, 70001, 50001, '周末打游戏吗')
            async with ChatModel(config.model_settings('mind')) as mind:
                chat = Chat(config, persona, store, mind)
                pending = store.pending_messages(SCENE)
                result = await chat.run_turn(batch=(pending[-1][0], [chat.context.batch([pending[-1][1]])]),
                                             append_new=lambda *args: _no_new_messages(), wait_for_messages=_unused_wait,
                                             attention_state={}, direct=True)
                assert result['error'] is None, result['error']
            shown = json.loads(store.db.execute(
                "SELECT request FROM model_calls WHERE role='mind' AND turn_id!='old' ORDER BY id DESC LIMIT 1"
            ).fetchone()[0])['expression_ids']
    assert len(shown) == 5
    assert (ids[0] in shown) is not disliked
