"""QQ card payloads keep readable fields through the OneBot message boundary."""

import json

import pytest

from len_bot.next.platform.messages import render_batch, render_body
from len_bot.next.platform.onebot_messages import parse_message


@pytest.mark.parametrize('card,expected', [
    ({'app': 'com.tencent.miniapp_01', 'prompt': '[QQ小程序]视频标题',
      'meta': {'detail_1': {'title': '哔哩哔哩', 'desc': '视频简介', 'qqdocurl': 'https://example.org/video'}}},
     '[卡片：[QQ小程序]视频标题｜哔哩哔哩｜视频简介]'),
    ({'app': 'com.tencent.structmsg', 'prompt': '[分享]文章标题',
      'meta': {'news': {'title': '文章标题', 'desc': '文章简介', 'jumpUrl': 'https://example.org/article'}}},
     '[卡片：[分享]文章标题｜文章标题｜文章简介]'),
    ({'app': 'com.tencent.structmsg', 'prompt': '[分享]歌曲标题',
      'meta': {'music': {'title': '歌曲标题', 'desc': '歌手', 'musicUrl': 'https://example.org/audio'}}},
     '[卡片：[分享]歌曲标题｜歌曲标题｜歌手]'),
    ({'prompt': '标题', 'meta': {'news': {'title': '标题', 'desc': '长' * 100}}}, '[卡片：标题｜' + '长' * 80 + ']'),
    ({'meta': {'news': {'jumpUrl': 'https://example.org'}}}, '[json]'),
    ('{broken', '[json]'),
    ([], '[json]'),
    ({'prompt': 7, 'meta': {'news': {'title': None, 'desc': []}}}, '[json]'),
])
def test_qq_card_rendering(card, expected):
    payload = card if isinstance(card, str) else json.dumps(card, ensure_ascii=False)
    message = parse_message({
        'post_type': 'message', 'message_type': 'group', 'user_id': 70001, 'self_id': 90001,
        'message_id': 1, 'group_id': 80001, 'time': 1790000000,
        'sender': {'nickname': '群友'}, 'message': [{'type': 'json', 'data': {'data': payload}}],
    }, own_message_ids=set())
    assert message.segments[0].data == {'data': payload}
    assert render_body(message.segments) == expected
    assert render_batch([(message, None, {})], timezone='UTC').endswith('  ' + expected)
