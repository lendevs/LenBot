"""Timeline pagination and read latency at the HTTP boundary."""

from dataclasses import asdict
import json
import time

import pytest

from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message
from test_next_panel_acts_as_owner import SCENE, exercise, write_instance
from test_host_stream import login, panel


def seed(root, count, *, same_time=False):
    with Store(root / 'host.sqlite3', now=lambda: START + count) as store:
        rows = []
        for number in range(count):
            raw = message(70001, number + 1, f'合成消息 {number}')
            if number == count - 1:
                raw['message'] += [{'type': 'image', 'data': {'url': 'https://example.invalid/image.png'}},
                                   {'type': 'reply', 'data': {'id': '1'}}]
                raw['sender']['card'] = '群名片'
            parsed = parse_message(raw, own_message_ids=set())
            rows.append((SCENE, str(number + 1), json.dumps(asdict(parsed)), json.dumps(raw),
                         START if same_time else START + number, json.dumps({
                             'woke': False, 'channel': None, 'reason': '合成判定', 'score': 0.2, 'threshold': 1.0})))
        with store.db:
            store.db.executemany('INSERT INTO messages(scene,platform_id,body,raw,received_at,wake_verdict) VALUES(?,?,?,?,?,?)', rows)
        for _ in range(3):
            if same_time:
                store.now = lambda: START
            turn_id = store.start_turn(SCENE, wake_channel='direct')
            call_id = store.start_call(turn_id, 'mind', {'messages': [
                {'role': 'system', 'content': '合成设定'},
                {'role': 'user', 'content': '\n<相关长期记忆>\n不是 JSON，是群友粘贴的文本\n</相关长期记忆>'}]})
            store.end_call(call_id, {'message': {'role': 'assistant', 'content': '合成输出'}}, None,
                           tokens={'input': 100, 'output': 20, 'cached': 10})
            store.end_turn(turn_id, 'settled')


def test_timeline_cursor_orders_ties_without_gaps_and_validates_requests(tmp_path):
    write_instance(tmp_path, ['onebot:70001'])
    seed(tmp_path, 5, same_time=True)

    async def check(client):
        url = f'/api/host/scenes/{SCENE}/timeline'
        before, found = None, []
        while True:
            response = await client.get(url, params={'limit': 2, **({} if before is None else {'before': before})})
            assert response.status_code == 200, response.text
            page = response.json()
            found = page['items'] + found
            before = page['next_before']
            if before is None:
                break
        assert len(found) == 8
        assert [e['message_seq'] for e in found if e['type'] == 'message'] == [1, 2, 3, 4, 5]
        assert len({e['turn_id'] for e in found if e['type'] == 'turn'}) == 3
        assert [e['type'] for e in found] == ['message'] * 5 + ['turn'] * 3
        pictured = found[4]
        assert pictured['sender']['card'] == '群名片'
        assert pictured['images'][0]['url'] == 'https://example.invalid/image.png'
        assert pictured['reply']['platform_message_id'] == '1'
        assert pictured['verdict']['reason'] == '合成判定'
        turn = found[-1]
        assert turn['steps'] == 1 and turn['tokens']['input'] == 100 and turn['expressions'] == 0
        detail = (await client.get(f'/api/host/scenes/{SCENE}/turns/{turn["turn_id"]}')).json()
        assert detail['recall'] is None
        assert (await client.get(url, params={'before': 'invalid'})).status_code == 400
        assert (await client.get(url, params={'limit': 0})).status_code == 422
        assert (await client.get('/api/host/scenes/onebot:group:other/timeline')).status_code == 404
        await client.post('/api/auth/logout')
        assert (await client.get(url)).status_code == 401

    exercise(tmp_path, check)


@pytest.mark.asyncio
async def test_timeline_first_page_with_5000_messages(tmp_path):
    async with panel(tmp_path) as (_, client, __):
        seed(tmp_path, 5000)
        await login(client)
        start = time.perf_counter()
        response = await client.get(f'/api/host/scenes/{SCENE}/timeline')
        elapsed = time.perf_counter() - start
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page['items']) == 50 and page['next_before'] is not None
        assert elapsed < .1, elapsed
        print(f'5000 messages timeline first HTTP page: {elapsed * 1000:.1f} ms')
