"""Failover between same-protocol providers at the HTTP boundary, with a per-candidate circuit breaker."""
import json

import pytest

from len_bot.next.configuration.models import Failover, Models
from len_bot.next.models.client import ChatModel, ModelHTTPError, ModelSettings
from len_bot.next.models.failover import FailoverModel, ProviderHealth, open_model
from test_next_model import recorded_text_response
from test_next_native_models import peer_server

OK = (200, 'application/json', json.dumps(recorded_text_response()).encode())
LIMITED = (429, 'application/json', b'{"error":{"message":"rate limited"}}')
DOWN = (503, 'text/plain', b'upstream unavailable')
BAD = (400, 'application/json', b'{"error":{"message":"invalid request"}}')


def endpoint(server):
    return f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'


def settings(server, model):
    return ModelSettings(api='openai-chat', base_url=endpoint(server), api_key='synthetic-key', model=model)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def ask(model):
    return await model.complete([{'role': 'user', 'content': '你好'}], [])


@pytest.mark.asyncio
async def test_rate_limit_moves_to_the_backup_and_records_who_served():
    primary_seen, backup_seen = [], []
    primary = await peer_server([LIMITED], primary_seen)
    backup = await peer_server([OK], backup_seen)
    async with primary, backup:
        health = ProviderHealth(Failover(failure_threshold=3, cooldown_seconds=60))
        async with FailoverModel('mind', [('primary', settings(primary, 'mind-a')),
                                          ('backup', settings(backup, 'mind-b'))], health) as model:
            reply = await ask(model)
    assert reply.text
    assert reply.served_by['provider'] == 'backup' and reply.served_by['model'] == 'mind-b'
    assert reply.served_by['failed_before'][0]['provider'] == 'primary'
    assert 'HTTP 429' in reply.served_by['failed_before'][0]['error']
    assert backup_seen[0][2]['model'] == 'mind-b'
    state = health.state()['roles']['mind']
    assert [row['state'] for row in state['candidates']] == ['closed', 'closed']
    assert state['candidates'][0]['consecutive_failures'] == 1
    assert state['last_served']['provider'] == 'backup'


@pytest.mark.asyncio
async def test_a_request_the_provider_refused_is_not_sent_elsewhere():
    primary_seen, backup_seen = [], []
    primary = await peer_server([BAD], primary_seen)
    backup = await peer_server([OK], backup_seen)
    async with primary, backup:
        health = ProviderHealth()
        async with FailoverModel('mind', [('primary', settings(primary, 'a')),
                                          ('backup', settings(backup, 'b'))], health) as model:
            with pytest.raises(ModelHTTPError, match='HTTP 400') as raised:
                await ask(model)
    assert raised.value.status_code == 400
    assert backup_seen == []
    assert health.state()['roles']['mind']['candidates'][0]['failures'] == 0


@pytest.mark.asyncio
async def test_open_circuit_is_skipped_until_cooldown_then_one_trial_closes_it():
    clock = Clock()
    primary_seen, backup_seen = [], []
    primary = await peer_server([DOWN, DOWN, OK], primary_seen)
    backup = await peer_server([OK, OK, OK], backup_seen)
    async with primary, backup:
        health = ProviderHealth(Failover(failure_threshold=2, cooldown_seconds=30), clock=clock)
        async with FailoverModel('mind', [('primary', settings(primary, 'a')),
                                          ('backup', settings(backup, 'b'))], health) as model:
            assert (await ask(model)).served_by['provider'] == 'backup'
            assert (await ask(model)).served_by['provider'] == 'backup'
            primary_row = health.state()['roles']['mind']['candidates'][0]
            assert primary_row['state'] == 'open' and primary_row['reopens_in_seconds'] == 30
            # Open: the primary is not contacted at all.
            assert (await ask(model)).served_by['failed_before'] == []
            assert len(primary_seen) == 2
            clock.now += 31
            assert health.state()['roles']['mind']['candidates'][0]['state'] == 'half_open'
            assert (await ask(model)).served_by['provider'] == 'primary'
    row = health.state()['roles']['mind']['candidates'][0]
    assert (row['state'], row['consecutive_failures'], row['successes'], row['failures']) == ('closed', 0, 1, 2)
    assert len(backup_seen) == 3


@pytest.mark.asyncio
async def test_failed_trial_reopens_and_all_open_still_tries_in_reopening_order():
    clock = Clock()
    primary_seen, backup_seen = [], []
    primary = await peer_server([DOWN, DOWN], primary_seen)
    backup = await peer_server([DOWN, OK], backup_seen)
    async with primary, backup:
        health = ProviderHealth(Failover(failure_threshold=1, cooldown_seconds=10), clock=clock)
        async with FailoverModel('mind', [('primary', settings(primary, 'a')),
                                          ('backup', settings(backup, 'b'))], health) as model:
            with pytest.raises(ModelHTTPError, match='HTTP 503') as raised:
                await ask(model)
            assert '所有备用模型都失败' in ''.join(raised.value.__notes__)
            assert [row['state'] for row in health.state()['roles']['mind']['candidates']] == ['open', 'open']
            clock.now += 11
            # Both cooled down: the primary's trial fails and reopens it, the backup serves.
            reply = await ask(model)
    assert reply.served_by['provider'] == 'backup'
    rows = health.state()['roles']['mind']['candidates']
    assert [row['state'] for row in rows] == ['open', 'closed']


def test_roles_without_fallbacks_keep_a_plain_chat_model():
    models = Models.model_validate({
        'providers': {'p': {'api': 'openai-chat', 'base_url': 'https://p.example/v1', 'api_key': 'k'},
                      'q': {'api': 'openai-chat', 'base_url': 'https://q.example/v1', 'api_key': 'k'}},
        'roles': {'mind': {'provider': 'p', 'model': 'm', 'context_window_tokens': 8192},
                  'memory': {'provider': 'p', 'model': 'm', 'context_window_tokens': 8192,
                             'fallbacks': [{'provider': 'q', 'model': 'n'}]}},
        'failover': {'failure_threshold': 4, 'cooldown_seconds': 5}})
    health = ProviderHealth()
    assert type(open_model(models, 'mind', health)) is ChatModel
    memory = open_model(models, 'memory', health)
    assert isinstance(memory, FailoverModel)
    assert [(provider, item.model) for provider, item in memory.candidates] == [('p', 'm'), ('q', 'n')]
    assert memory.settings.model == 'm'
    assert health.settings.failure_threshold == 4


@pytest.mark.asyncio
async def test_model_call_log_names_the_provider_that_served(tmp_path, caplog):
    import logging
    from test_next_persona_permissions import _config, _package
    from len_bot.next.models.request import request_model
    from len_bot.next.storage.store import Store
    package = _package(tmp_path, 'plain', tools=['say'], documents={})
    config = _config(tmp_path / 'instance', package)
    primary = await peer_server([DOWN], [])
    backup = await peer_server([OK], [])
    async with primary, backup:
        with Store(config.database) as store:
            turn = store.start_turn(config.scene)
            async with FailoverModel('mind', [('synthetic', settings(primary, 'synthetic-mind')),
                                              ('spare', settings(backup, 'spare-mind'))], ProviderHealth()) as model:
                with caplog.at_level(logging.INFO):
                    reply = await request_model(config, store, model, [{'role': 'user', 'content': '你好'}], [],
                                                scene=config.scene, role='mind', turn_id=turn)
    assert reply.served_by['provider'] == 'spare'
    record = next(item for item in caplog.records if getattr(item, 'event', None) == 'model_call')
    assert record.fields['provider'] == 'synthetic'
    assert (record.fields['served_provider'], record.fields['served_model']) == ('spare', 'spare-mind')
    assert record.fields['failed_before'][0]['provider'] == 'synthetic'
    assert any(getattr(item, 'event', None) == 'model_failover' for item in caplog.records)
