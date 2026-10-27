"""Per-group wake usage and the per-model usage ledger."""
from len_bot.next.chat import usage
from len_bot.next.storage.store import Store


def test_group_wake_usage_filters_token_rows_by_scene(tmp_path, monkeypatch):
    now = 1790618400.
    with Store(tmp_path / 'state.db', now=lambda: now) as store:
        for scene, tokens in (('onebot:group:80001', 100), ('onebot:group:80002', 900), ('onebot:group:80002', 900)):
            turn = store.start_turn(scene, wake_channel='direct')
            call = store.start_call(turn, 'mind', {'provider': 'fixture'})
            store.end_call(call, {}, None, tokens={'input': tokens - 10, 'output': 10, 'cached': None}, model=('fixture', 'fixture-model'))
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


def test_usage_ledger_keeps_each_model_after_the_call_rows_are_gone(tmp_path):
    from len_bot.next.models.usage import summarize, usage_rows
    day = 1790618400.
    with Store(tmp_path / 'state.db', now=lambda: day) as store:
        for model, at, tokens in (('model-a', day, 100), ('model-b', day, 40), ('model-a', day + 86400, 60)):
            store.now = lambda at=at: at
            call = store.start_scene_call('onebot:group:80001', 'upkeep', {'provider': 'main'})
            store.end_call(call, {}, None, tokens={'input': tokens - 10, 'output': 10, 'cached': 5}, model=('main', model))
        unreported = store.start_scene_call('onebot:group:80001', 'upkeep', {'provider': 'main'})
        store.end_call(unreported, {}, None, model=('main', 'model-a'))
        with store.db:
            store.db.execute('DELETE FROM model_calls')
        result = summarize(usage_rows(store.db, None, day, day + 2 * 86400), 'UTC')
    assert [(row['model'], row['calls'], row['input'], row['output']) for row in result['models']] == [
        ('model-a', 2, 140, 20), ('model-b', 1, 30, 10)]
    assert [(row['day'], row['model'], row['calls']) for row in result['days']] == [
        ('2026-09-28', 'model-a', 1), ('2026-09-28', 'model-b', 1), ('2026-09-29', 'model-a', 1)]
    assert result['groups'] == [{'scene': 'onebot:group:80001', 'purpose': 'upkeep', 'calls': 3,
                                 'input': 170, 'output': 30, 'cached': 15}]
