"""An unprompted wake states how fresh the talk that woke it is, without judging the topic."""

from len_bot.next.chat.freshness import topic_freshness
from len_bot.next.platform.messages import ChatMessage, Segment, Sender

START = 1790000000.0


def _message(ident: int, user: str, text: str, at: float, *, own: bool = False) -> ChatMessage:
    return ChatMessage(str(ident), 'onebot', 'onebot:90001', 'onebot:group:80001', str(ident),
                       Sender(user, f'成员{ident}', None, 'member'), at, [Segment('text', {'text': text})],
                       None, False, own, 'sent' if own else 'received')


def _pending(*rows):
    return [(seq, _message(seq, user, text, at, own=user == 'onebot:90001'), at)
            for seq, (user, text, at) in enumerate(rows, start=1)]


def _facts(pending, woke_at, now):
    return topic_freshness(pending, woke_at=woke_at, now=now, timezone='UTC', excluded=('onebot:90001',))


def test_talk_that_moved_on_after_a_pause_is_described():
    pending = _pending(('onebot:70001', '有人玩过那个钓鱼游戏吗', START),
                       ('onebot:70002', '晚饭吃啥', START + 900), ('onebot:70003', '楼下新开了面馆', START + 960),
                       ('onebot:70002', '面馆排队吗', START + 1000))
    text = _facts(pending, START, START + 1020)
    assert '<话题新鲜度>' in text and '17 分钟前' in text
    assert '之后又有 3 条、2 个人在说，都没有和它相同的字词' in text
    assert '最后一条在 20 秒前' in text and '中间停过 1 次，最长停了 15 分钟' in text


def test_talk_still_on_the_same_thing_is_described_as_such():
    pending = _pending(('onebot:70001', '钓鱼游戏新版本出了', START), ('onebot:70002', '新版本加了船', START + 20),
                       ('onebot:90001', '我也在玩', START + 25), ('onebot:70003', '钓鱼好难', START + 40))
    text = _facts(pending, START, START + 45)
    assert '之后又有 2 条、2 个人在说，其中 2 条和它用到相同的字词' in text and '停过' not in text


def test_the_waking_message_is_the_one_received_at_the_wake():
    pending = _pending(('onebot:70001', '早上好', START), ('onebot:70002', '下午去爬山吗', START + 600))
    text = _facts(pending, START + 600, START + 610)
    assert '10 秒前' in text and '之后没有新消息' in text


def test_a_timer_wake_after_older_messages_gives_nothing():
    pending = _pending(('onebot:70001', '有人玩过那个钓鱼游戏吗', START), ('onebot:70002', '晚饭吃啥', START + 60))
    assert _facts(pending, START + 1800, START + 1800) is None


def test_only_own_messages_give_nothing():
    assert _facts(_pending(('onebot:90001', '我在', START)), START, START + 1) is None
