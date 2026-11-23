"""Timeline pagination and read latency at the HTTP boundary."""

from dataclasses import asdict
import json
import time

import pytest

from len_bot.next.platform.onebot_messages import parse_message, parse_notice
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
                             'woke': False, 'channel': None, 'reason': '合成判定', 'score': 0.2, 'threshold': 1.0,
                             'effect_factor': 0.75, 'parts': {'messages': 2, 'base': 0.4, 'question': 1.0, 'self_share': -0.5,
                                                             'raw': 0.9, 'activity': 0.3}})))
        with store.db:
            store.db.executemany('INSERT INTO messages(scene,platform_id,body,raw,received_at,wake_verdict) VALUES(?,?,?,?,?,?)', rows)
        for number in range(3):
            if same_time:
                store.now = lambda: START
            turn_id = store.start_turn(SCENE, wake_channel='direct', wake_received_at=START - 4 if number == 0 else None)
            call_id = store.start_call(turn_id, 'mind', {'messages': [
                {'role': 'system', 'content': '合成设定'},
                {'role': 'user', 'content': '\n<相关长期记忆>\n不是 JSON，是群友粘贴的文本\n</相关长期记忆>'}]})
            store.end_call(call_id, {'message': {'role': 'assistant', 'content': '合成输出'}}, None,
                           tokens={'input': 100, 'output': 20, 'cached': 10}, model=('fixture', 'fixture-model'))
            if number < 2:
                with store.db:
                    store.db.execute('UPDATE turns SET first_expression_at=started+6 WHERE id=?', (turn_id,))
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
        # From the waking message when known, otherwise from the turn's start; none without an expression.
        waits = sorted((e['first_expression_wait'] for e in found if e['type'] == 'turn'), key=lambda value: (value is None, value))
        assert waits == [6, 10, None]
        pictured = found[4]
        assert pictured['sender']['card'] == '群名片'
        assert pictured['images'][0]['url'] == 'https://example.invalid/image.png'
        assert pictured['reply']['platform_message_id'] == '1'
        assert (pictured['verdict']['reason'], pictured['verdict']['effect_factor']) == ('合成判定', 0.75)
        assert pictured['verdict']['parts'] == {'messages': 2, 'base': 0.4, 'question': 1.0, 'self_share': -0.5,
                                                'raw': 0.9, 'activity': 0.3}
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


def test_timeline_places_notices_between_messages_and_turns(tmp_path):
    write_instance(tmp_path, ['onebot:70001'])
    seed(tmp_path, 5, same_time=True)
    with Store(tmp_path / 'host.sqlite3', now=lambda: START) as store:
        store.save_notice(parse_notice({'time': START, 'self_id': 90001, 'post_type': 'notice', 'group_id': 80001,
                                        'notice_type': 'group_increase', 'sub_type': 'approve',
                                        'operator_id': 0, 'user_id': 70002}))
        store.save_notice(parse_notice({'time': START, 'self_id': 90001, 'post_type': 'notice', 'group_id': 80001,
                                        'notice_type': 'group_recall', 'operator_id': 70001, 'user_id': 70001,
                                        'message_id': 3}))

    async def check(client):
        url = f'/api/host/scenes/{SCENE}/timeline'
        before, found = None, []
        while True:
            response = await client.get(url, params={'limit': 3, **({} if before is None else {'before': before})})
            assert response.status_code == 200, response.text
            page = response.json()
            found = page['items'] + found
            before = page['next_before']
            if before is None:
                break
        assert [e['type'] for e in found] == ['message'] * 5 + ['notice'] * 2 + ['turn'] * 3
        joined, recall = (e for e in found if e['type'] == 'notice')
        assert (joined['kind'], joined['sub_type'], joined['user_id'], joined['user_name']) == (
            'group_increase', 'approve', 'onebot:70002', None)
        assert (recall['kind'], recall['user_name'], recall['platform_message_id']) == ('group_recall', '群名片', '3')
        assert recall['raw']['message_id'] == 3
        assert found[2]['recalled'] is True

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


def test_received_notice_is_announced_to_the_panel(tmp_path):
    from test_next_persona_switch import run_host

    async def exercise(client, runtime, store):
        runtime.accepting = True
        published = []
        publish = runtime.events.publish

        def record(type, scene=None, **fields):
            published.append((type, scene, fields))
            publish(type, scene, **fields)

        runtime.events.publish = record
        runtime._receive({'time': int(time.time()), 'self_id': 90001, 'post_type': 'notice', 'group_id': 80001,
                          'notice_type': 'group_decrease', 'sub_type': 'leave', 'operator_id': 70002, 'user_id': 70002})
        assert ('notice.received', SCENE, {'kind': 'group_decrease'}) in published
        page = (await client.get(f'/api/host/scenes/{SCENE}/timeline')).json()
        assert [(e['kind'], e['user_id']) for e in page['items'] if e['type'] == 'notice'] == [
            ('group_decrease', 'onebot:70002')]

    run_host(tmp_path, exercise)


def test_turn_detail_strips_large_raw_payloads_by_default_and_turn_export_filters_log_dates(tmp_path):
    import io
    import zipfile
    from datetime import datetime, timezone

    write_instance(tmp_path, ['onebot:70001'])
    turn_ts = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc).timestamp()
    with Store(tmp_path / 'host.sqlite3', now=lambda: turn_ts) as store:
        turn_id = store.start_turn(SCENE, wake_channel='direct')
        call_id = store.start_call(turn_id, 'mind', {
            'provider': 'local',
            'settings': {'api': 'openai-chat', 'model': 'fixture-model'},
            'system': 'S' * 40000,
            'tools': [{'type': 'function', 'function': {'name': 'say', 'description': 'T' * 40000}}],
            'messages': [{'role': 'user', 'content': 'M' * 40000}],
        })
        store.end_call(
            call_id,
            {'message': {'role': 'assistant', 'content': '简短回复'}, 'finish_reason': 'stop', 'raw': {'blob': 'R' * 40000}},
            {'prompt_tokens': 100, 'completion_tokens': 20},
            tokens={'input': 100, 'output': 20, 'cached': None},
            model=('local', 'fixture-model'),
        )
        store.end_turn(turn_id, 'settled')

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir(exist_ok=True)
    record = json.dumps({'ts': '2026-09-20T12:00:01.000+00:00', 'level': 'INFO', 'source': 'test',
                         'event': 'turn', 'message': 'turn-log-marker', 'turn_id': turn_id})
    (logs_dir / 'lenbot.jsonl.2026-09-20').write_text(record + '\n', encoding='utf-8')
    # Unrelated historical archive outside ±1 day must be skipped even if it contains invalid JSON.
    (logs_dir / 'lenbot.jsonl.2026-01-01').write_text('{not-json-should-never-be-read\n', encoding='utf-8')

    async def check(client):
        compact_resp = await client.get(f'/api/host/scenes/{SCENE}/turns/{turn_id}')
        assert compact_resp.status_code == 200, compact_resp.text
        compact = compact_resp.json()
        assert compact['steps'][0]['text'] == '简短回复'
        call = compact['calls'][0]
        assert call['id'] == call_id and call['tokens'] == {'input': 100, 'output': 20, 'cached': None}
        assert call['request']['provider'] == 'local'
        assert not ({'messages', 'tools', 'system'} & call['request'].keys())
        assert 'raw' not in call['response']
        assert len(compact_resp.content) < 4096

        full_resp = await client.get(f'/api/host/scenes/{SCENE}/turns/{turn_id}', params={'include_raw': 'true'})
        assert full_resp.status_code == 200, full_resp.text
        full_call = full_resp.json()['calls'][0]
        assert 'messages' in full_call['request'] and 'tools' in full_call['request'] and 'raw' in full_call['response']

        exported = await client.get(f'/api/host/scenes/{SCENE}/turns/{turn_id}/export')
        assert exported.status_code == 200, exported.text
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            text = archive.read('diagnostic.txt').decode('utf-8')
        assert 'turn-log-marker' in text

    exercise(tmp_path, check)
