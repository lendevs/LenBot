"""recall_chat search: newest-first by default, all keywords of a query must match, context width is adjustable."""

import re
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from len_bot.next.chat.recall import RECALL_TOOL, RecallArguments, recall_chat
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store

SCENE = 'onebot:group:80001'
BASE = 1790000000


def _receive(store: Store, message_id: int, text: str, *, at: int, user: int = 70001) -> int:
    raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
           'user_id': user, 'message_id': message_id, 'time': at,
           'sender': {'nickname': f'成员{user}', 'role': 'member'}, 'message': [{'type': 'text', 'data': {'text': text}}]}
    return store.enqueue(parse_message(raw, own_message_ids=set()), raw, at)


def _search(store: Store, **arguments) -> str:
    return recall_chat(store, SCENE, 'UTC', RecallArguments.model_validate({'action': 'search', **arguments}))


def _at(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def _records(listing: str) -> list[int]:
    return [int(number) for number in re.findall(r'，record=(\d+)', listing)]


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / 'state.sqlite3') as opened:
        yield opened


def _topic(store: Store, count: int) -> None:
    for number in range(count):
        _receive(store, 100 + number, f'合成话题第{number}条', at=BASE + number)


def test_search_defaults_to_newest_and_pages_backwards(store):
    _topic(store, 25)
    first = _search(store, query='合成话题')
    assert _records(first) == list(range(25, 15, -1))
    assert 'search（最新优先） 第 1 页，共 10 条' in first
    assert '还有更早的记录' in first and 'order=newest、snapshot=25、offset=10' in first

    # A message arriving after the first page does not shift the later pages.
    _receive(store, 900, '合成话题新到的', at=BASE + 100)
    second = _search(store, query='合成话题', order='newest', snapshot=25, offset=10)
    assert _records(second) == list(range(15, 5, -1))
    third = _search(store, query='合成话题', snapshot=25, offset=20)
    assert _records(third) == [5, 4, 3, 2, 1] and '没有下一页了' in third


def test_search_oldest_pages_forwards(store):
    _topic(store, 25)
    first = _search(store, query='合成话题', order='oldest')
    assert _records(first) == list(range(1, 11))
    assert 'search（最早优先）' in first and '还有更晚的记录' in first and 'order=oldest、snapshot=25、offset=10' in first
    last = _search(store, query='合成话题', order='oldest', snapshot=25, offset=20)
    assert _records(last) == [21, 22, 23, 24, 25] and '没有下一页了' in last


def test_search_without_query_and_with_filters_follows_order(store):
    for number in range(6):
        _receive(store, 100 + number, f'第{number}条', at=BASE + number * 60, user=70001 + number % 2)
    assert _records(_search(store)) == [6, 5, 4, 3, 2, 1]
    assert _records(_search(store, order='oldest', who='onebot:70002')) == [2, 4, 6]
    assert _records(_search(store, who='onebot:70002')) == [6, 4, 2]
    assert _records(_search(store, before=_at(BASE + 300))) == [5, 4, 3, 2, 1]
    assert _records(_search(store, order='oldest', after=_at(BASE + 120))) == [3, 4, 5, 6]
    assert _records(_search(store, after=_at(BASE + 60), before=_at(BASE + 240))) == [4, 3, 2]


def test_same_instant_messages_keep_record_order(store):
    for number in range(4):
        _receive(store, 100 + number, f'同一秒{number}', at=BASE)
    assert _records(_search(store, query='同一秒', order='oldest')) == [1, 2, 3, 4]
    assert _records(_search(store, query='同一秒')) == [4, 3, 2, 1]
    around = recall_chat(store, SCENE, 'UTC', RecallArguments(action='context', record=2, context_before=1, context_after=1))
    assert _records(around) == [1, 2, 3]


def test_all_keywords_must_match(store):
    _receive(store, 100, '周六下午三点在东门集合', at=BASE)
    _receive(store, 101, '周六下午改到西门', at=BASE + 1)
    _receive(store, 102, '东门集合后一起吃饭', at=BASE + 2)
    _receive(store, 103, '下午 东门 集合', at=BASE + 3)
    assert _records(_search(store, query='东门集合')) == [3, 1]
    assert _records(_search(store, query='周六下午 东门集合')) == [1]
    assert _records(_search(store, query='周六下午 西门')) == [2]
    assert '没有符合条件的记录' in _search(store, query='周六下午 吃饭')
    # Any whitespace separates keywords, and a repeated keyword counts once.
    assert _records(_search(store, query='  周六下午\t东门集合\n周六下午　东门集合 ')) == [1]


def test_short_keywords_match_by_substring_together_with_long_ones(store):
    _receive(store, 100, '明天 deadline 到了', at=BASE)
    _receive(store, 101, '明天不上课', at=BASE + 1)
    _receive(store, 102, 'deadline 推迟了', at=BASE + 2)
    assert _records(_search(store, query='明天')) == [2, 1]
    assert _records(_search(store, query='明天 到')) == [1]
    assert _records(_search(store, query='明天 deadline')) == [1]
    assert _records(_search(store, query='ok 明天')) == []
    assert _records(_search(store, query='DEADLINE 推')) == [3]


def test_keyword_characters_are_literal(store):
    _receive(store, 100, '他说"你好啊"然后走了', at=BASE)
    _receive(store, 101, 'AND OR NOT 都是普通词', at=BASE + 1)
    assert _records(_search(store, query='"你好啊"')) == [1]
    assert _records(_search(store, query='AND OR NOT')) == [2]
    assert _records(_search(store, query='普通词 NOT')) == [2]


def test_keyword_count_is_capped_after_removing_duplicates(store):
    _receive(store, 100, ' '.join(f'词{number}' for number in range(8)), at=BASE)
    eight = ' '.join(f'词{number}' for number in range(8))
    assert _records(_search(store, query=eight + ' ' + eight)) == [1]
    with pytest.raises(ValidationError, match='at most 8'):
        RecallArguments(query=eight + ' 词8')


def test_blank_query_is_rejected():
    for query in ('', '   ', '\n\u3000'):
        with pytest.raises(ValidationError, match='keyword'):
            RecallArguments(query=query)


def test_context_width_is_adjustable(store):
    _topic(store, 30)
    default = recall_chat(store, SCENE, 'UTC', RecallArguments(action='context', record=15))
    assert _records(default) == list(range(12, 19)) and 'record=15，查询的这条]' in default
    wide = recall_chat(store, SCENE, 'UTC', RecallArguments(action='context', record=15, context_before=10, context_after=1))
    assert _records(wide) == list(range(5, 17))
    only = recall_chat(store, SCENE, 'UTC', RecallArguments(action='context', record=15, context_before=0, context_after=0))
    assert _records(only) == [15]
    edge = recall_chat(store, SCENE, 'UTC', RecallArguments(action='context', record=3, context_before=20, context_after=20))
    assert _records(edge) == list(range(1, 24))
    start = recall_chat(store, SCENE, 'UTC', RecallArguments(action='context', record=1, context_before=5, context_after=2))
    assert _records(start) == [1, 2, 3]


def test_argument_validation():
    for value in (-1, 21):
        with pytest.raises(ValidationError):
            RecallArguments(action='context', record=1, context_before=value)
        with pytest.raises(ValidationError):
            RecallArguments(action='context', record=1, context_after=value)
    with pytest.raises(ValidationError):
        RecallArguments(order='latest')
    with pytest.raises(ValidationError, match='does not accept order'):
        RecallArguments(action='recent', order='newest')
    with pytest.raises(ValidationError, match='does not accept order'):
        RecallArguments(action='context', record=1, order='oldest')
    with pytest.raises(ValidationError, match='does not accept context_before'):
        RecallArguments(action='search', context_before=2)
    with pytest.raises(ValidationError, match='does not accept context_before'):
        RecallArguments(action='read', record=1, context_after=2)
    assert RecallArguments().order == 'newest'
    assert RecallArguments.model_validate({'action': 'context', 'record': 1, 'context_before': 20}).context_before == 20


def test_tool_definition_describes_the_new_parameters():
    properties = RECALL_TOOL['function']['parameters']['properties']
    assert properties['order']['default'] == 'newest' and set(properties['order']['enum']) == {'newest', 'oldest'}
    assert properties['context_before']['maximum'] == 20 and properties['context_after']['default'] == 3
    description = RECALL_TOOL['function']['description']
    assert all(word in description for word in ('order', 'context_before', 'context_after', '关键词'))
