"""Per-group wake usage reads only that group's mind calls (audit C-3)."""
from len_bot.next.chat import usage
from len_bot.next.storage.store import Store


def test_group_wake_usage_filters_token_rows_by_scene(tmp_path, monkeypatch):
    now = 1790618400.
    with Store(tmp_path / 'state.db', now=lambda: now) as store:
        for scene, tokens in (('onebot:group:80001', 100), ('onebot:group:80002', 900), ('onebot:group:80002', 900)):
            turn = store.start_turn(scene, wake_channel='direct')
            call = store.start_call(turn, 'mind', {'provider': 'fixture'})
            store.end_call(call, {}, None, tokens={'input': tokens - 10, 'output': 10, 'cached': None})
            store.end_turn(turn, 'settled')
        decoded = []
        real = usage.json.loads
        monkeypatch.setattr(usage.json, 'loads', lambda body: decoded.append(body) or real(body))
        rows = usage.wake_usage(store, ['onebot:group:80001'], now - 1, now + 1, 'UTC')
        assert [(row['scene'], row['wakes']) for row in rows] == [('onebot:group:80001', 1)]
        assert len(decoded) == 1
        decoded.clear()
        assert sum(row['wakes'] for row in usage.wake_usage(store, None, now - 1, now + 1, 'UTC')) == 3
        assert len(decoded) == 3
