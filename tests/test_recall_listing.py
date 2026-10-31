"""recall_chat returns history in the chat input layout, with record numbers and paging in plain words."""

from len_bot.next.chat.recall import RecallArguments, recall_chat
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store

SCENE = 'onebot:group:80001'


def _receive(store: Store, message_id: int, text: str, *, at: int) -> None:
    raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90001, 'group_id': 80001,
           'user_id': 70001, 'message_id': message_id, 'time': at,
           'sender': {'nickname': '合成成员', 'role': 'member'}, 'message': [{'type': 'text', 'data': {'text': text}}]}
    store.enqueue(parse_message(raw, own_message_ids=set()), raw, at)


def test_search_lists_messages_like_chat_input(tmp_path):
    with Store(tmp_path / 'state.sqlite3') as store:
        for number in range(12):
            _receive(store, 100 + number, f'合成话题第{number}条', at=1790000000 + number)
        _receive(store, 200, '长' * 300, at=1790086400)
        first = recall_chat(store, SCENE, 'UTC', RecallArguments(query='合成话题', order='oldest'))
        assert first.count('2026-') == 1 and SCENE + '｜' not in first
        assert '"合成成员"(onebot:70001) [id="100"，record=1]' in first and '  合成话题第0条' in first
        assert 'snapshot=13、offset=10' in first and 'previews' not in first and 'total_chars' not in first
        second = recall_chat(store, SCENE, 'UTC', RecallArguments(query='合成话题', order='oldest', snapshot=13, offset=10))
        assert '第 2 页，共 2 条' in second and '没有下一页了' in second

        recent = recall_chat(store, SCENE, 'UTC', RecallArguments(action='recent'))
        assert '（共 300 字，用 read 读全文）' in recent and recent.count('2026-') == 2
        full = recall_chat(store, SCENE, 'UTC', RecallArguments(action='read', record=13))
        assert '长' * 300 in full and '共' in full and '续读' not in full

        around = recall_chat(store, SCENE, 'UTC', RecallArguments(action='context', record=5))
        assert 'record=5，查询的这条]' in around
        assert '没有符合条件的记录' in recall_chat(store, SCENE, 'UTC', RecallArguments(query='不存在的词'))
