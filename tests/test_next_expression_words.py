"""Learned expressions reach the prompt without embeddings, ranked by words shared with the recent chat."""

from __future__ import annotations

import json

import pytest

from len_bot.next.learning.expression_match import grams, overlap, select_by_words
from len_bot.next.learning.store import LearningStore
from len_bot.next.storage.store import Store

import test_next_turn_speed as turns


def test_grams_pair_han_characters_and_keep_latin_words():
    assert grams('打游戏 GPT5 好') == {'打游', '游戏', 'gpt5', '好'}
    assert overlap('周六去打游戏', '周六打游戏吗') > overlap('周六去打游戏', '下雨了')


def test_select_by_words_ranks_by_how_much_of_the_situation_the_chat_mentions():
    adopted = [{'id': 1, 'situation': '有人约周末打游戏', 'style': '冲！'},
               {'id': 2, 'situation': '有人抱怨下雨', 'style': '又下雨了啊'},
               {'id': 3, 'situation': '周末', 'style': '躺平'}]
    ranked = select_by_words(adopted, '这周末一起打游戏吗')
    assert [item['id'] for item in ranked] == [3, 1]
    assert select_by_words(adopted, '今天天气不错') == []


@pytest.mark.asyncio
async def test_turn_without_embeddings_offers_matching_expressions(tmp_path):
    config, persona = turns._instance(tmp_path)
    source = json.loads((tmp_path / 'lenbot.config.json').read_text())
    source['learning'] = {'extract': False}
    (tmp_path / 'lenbot.config.json').write_text(json.dumps(source, ensure_ascii=False))
    config = turns.load_config(tmp_path)
    with Store(config.database) as store:
        turns._receive(store, '周末打游戏好开心', user=70002, message_id=40001)
        seq = store.max_message_seq(turns.SCENE)
        records = LearningStore(store)
        records.initialize(turns.SCENE, 0)
        batch = records.begin(turns.SCENE, 0, seq, {})
        records.complete(batch, [('有人提到周末打游戏', '冲冲冲', [seq]), ('有人抱怨下雨', '又下雨了', [seq])],
                         auto_adopt=True)
    result, bodies = await turns._turn(config, persona, [turns._calls(('say', {'content': '好', 'end_turn': True}))])
    assert result['status'] == 'settled', result['error']
    prompt = json.dumps(bodies[0]['messages'], ensure_ascii=False)
    assert '冲冲冲' in prompt and '又下雨了' not in prompt
