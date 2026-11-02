"""Telegram and Feishu in the first-run wizard and on the connection page: tests, saves and the group list."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path

import httpx
import pytest

from len_bot.next.config import load_host_config
from len_bot.next.memory.service import open_memory
from len_bot.next.models.client import ChatModel
from len_bot.next.panel import setup as first_run
from len_bot.next.panel.app import create_app
from len_bot.next.panel.setup import FirstSetup, create_setup_app, initialize
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform import feishu, telegram
from len_bot.next.runtime.lifecycle import HostLifecycle
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_next_host_manage_permissions_config import instance

TOKEN = '7001:' + 'T' * 35
NEW_TOKEN = '7002:' + 'N' * 35


def telegram_api(requests: list):
    """A Bot API stand-in: getMe, and one pending group message from a person."""
    def answer(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit('/', 1)[1]
        requests.append((request.url.path, json.loads(request.content or b'{}')))
        if method == 'getMe':
            return httpx.Response(200, json={'ok': True, 'result': {'id': 7001, 'is_bot': True, 'first_name': 'Len',
                                                                    'username': 'len_bot'}})
        if method == 'getUpdates':
            return httpx.Response(200, json={'ok': True, 'result': [{'update_id': 5, 'message': {
                'message_id': 1, 'date': 1, 'text': 'hi',
                'chat': {'id': -100123, 'type': 'supergroup', 'title': '合成群'},
                'from': {'id': 70001, 'is_bot': False, 'first_name': '合成', 'last_name': '用户'}}}]})
        return httpx.Response(200, json={'ok': False, 'error_code': 404, 'description': 'Not Found'})
    return httpx.MockTransport(answer)


def feishu_api(requests: list, *, chats_allowed: bool = True):
    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == '/open-apis/auth/v3/tenant_access_token/internal':
            body = json.loads(request.content)
            if body['app_secret'] != 'fixture-secret':
                return httpx.Response(200, json={'code': 10014, 'msg': 'app secret invalid'})
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 't-fixture', 'expire': 7200})
        assert request.headers['Authorization'] == 'Bearer t-fixture'
        if request.url.path == '/open-apis/bot/v3/info':
            return httpx.Response(200, json={'code': 0, 'bot': {'open_id': 'ou_bot', 'app_name': '合成应用'}})
        if request.url.path == '/open-apis/im/v1/chats':
            if not chats_allowed:
                return httpx.Response(200, json={'code': 99991672, 'msg': 'no permission'})
            page = request.url.params.get('page_token')
            items = [{'chat_id': 'oc_two', 'name': '第二群'}] if page else [{'chat_id': 'oc_one', 'name': '第一群'}]
            return httpx.Response(200, json={'code': 0, 'data': {'items': items, 'has_more': not page,
                                                                 'page_token': '' if page else 'next'}})
        return httpx.Response(404)
    return httpx.MockTransport(answer)


@pytest.mark.asyncio
async def test_telegram_probe_reads_the_bot_and_pending_chats_without_confirming(monkeypatch):
    requests = []
    monkeypatch.setattr(telegram, '_transport', lambda proxy: telegram_api(requests))
    result = await telegram.probe(TOKEN, updates=True)
    assert result == {'bot_id': 'telegram:7001', 'name': '@len_bot',
                      'groups': [{'id': '-100123', 'name': '合成群'}],
                      'people': [{'id': '70001', 'name': '合成 用户'}]}
    updates = [body for path, body in requests if path.endswith('/getUpdates')]
    assert updates == [{'timeout': 0, 'allowed_updates': ['message']}]
    requests.clear()
    assert (await telegram.probe(TOKEN))['groups'] == []
    assert [path.rsplit('/', 1)[1] for path, _ in requests] == ['getMe']


@pytest.mark.asyncio
async def test_telegram_probe_names_the_refusal_without_the_token(monkeypatch):
    monkeypatch.setattr(telegram, '_transport', lambda proxy: httpx.MockTransport(
        lambda request: httpx.Response(401, json={'ok': False, 'error_code': 401, 'description': 'Unauthorized'})))
    with pytest.raises(telegram.TelegramCallError, match='Unauthorized') as caught:
        await telegram.probe(TOKEN)
    assert TOKEN not in str(caught.value)


@pytest.mark.asyncio
async def test_feishu_probe_reads_the_bot_and_every_page_of_chats(monkeypatch):
    requests = []
    monkeypatch.setattr(feishu, '_transport', lambda: feishu_api(requests))
    result = await feishu.probe('cli_fixture', 'fixture-secret')
    assert result == {'bot_id': 'feishu:ou_bot', 'name': '合成应用',
                      'groups': [{'id': 'oc_one', 'name': '第一群'}, {'id': 'oc_two', 'name': '第二群'}]}
    monkeypatch.setattr(feishu, '_transport', lambda: feishu_api([], chats_allowed=False))
    assert (await feishu.probe('cli_fixture', 'fixture-secret'))['groups'] == []
    with pytest.raises(feishu.FeishuCallError, match='10014'):
        await feishu.probe('cli_fixture', 'wrong-secret')


@pytest.mark.asyncio
async def test_setup_tests_telegram_and_feishu_before_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(telegram, '_transport', lambda proxy: telegram_api([]))
    monkeypatch.setattr(feishu, '_transport', lambda: feishu_api([]))
    app = create_setup_app(tmp_path, 'fixture-token', asyncio.Event())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1',
                                 headers={'X-Setup-Token': 'fixture-token'}) as client:
        found = await client.post('/api/setup/telegram', json={'bot_token': TOKEN})
        assert found.status_code == 200, found.text
        assert found.json()['bot_id'] == 'telegram:7001' and found.json()['people'][0]['id'] == '70001'
        found = await client.post('/api/setup/feishu', json={'app_id': 'cli_fixture', 'app_secret': 'fixture-secret'})
        assert found.status_code == 200, found.text
        assert found.json()['bot_id'] == 'feishu:ou_bot' and len(found.json()['groups']) == 2
        refused = await client.post('/api/setup/feishu', json={'app_id': 'cli_fixture', 'app_secret': 'wrong'})
        assert refused.status_code == 422 and 'wrong' not in refused.text
    assert not (tmp_path / 'lenbot.config.json').exists()


def setup_body(**changes) -> dict:
    return {
        'bot_id': 'telegram:7001', 'owners': ['telegram:70001'], 'timezone': 'Asia/Shanghai',
        'onebot': None, 'telegram': {'bot_id': 'telegram:7001', 'bot_token': TOKEN},
        'provider': {'api': 'openai-chat', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'synthetic-secret'},
        'mind': {'provider': 'primary', 'model': 'fixture', 'context_window_tokens': 8192},
        'compaction': {'input_tokens': 6000},
        'scene': 'telegram:group:-100123', 'panel_port': 8088, 'username': 'fixture', 'password': 'synthetic-password',
        **changes,
    }


@pytest.mark.parametrize('platform', ['telegram', 'feishu'])
def test_setup_with_only_telegram_or_feishu_runs_live(tmp_path: Path, platform):
    body = setup_body() if platform == 'telegram' else setup_body(
        bot_id='feishu:ou_bot', owners=['feishu:ou_owner'], telegram=None, scene='feishu:group:oc_one',
        feishu={'bot_id': 'feishu:ou_bot', 'app_id': 'cli_fixture', 'app_secret': 'fixture-secret'})
    initialize(tmp_path, FirstSetup.model_validate(body))
    config = load_host_config(tmp_path)
    assert config.delivery == 'live' and config.platform_names == (platform,)
    assert config.bot_for(body['scene']) == body['bot_id'] and body['scene'] in config.scenes


def test_setup_without_any_platform_stays_simulated():
    assert first_run.setup_source(FirstSetup.model_validate(setup_body(telegram=None)))['delivery'] == 'simulated'


@asynccontextmanager
async def panel(root: Path, **changes):
    source = instance(root)
    source.update(changes)
    (root / 'lenbot.config.json').write_text(json.dumps(source))
    config = load_host_config(root)
    role = load_persona(config.scenes['onebot:group:80001'].persona)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind, open_memory(config, store) as memory:
            runtime = NetworkRuntime(config, [(config.scene_config(scene), role) for scene in config.scenes],
                                     store, mind, memory=memory, lifecycle=HostLifecycle())
            app = create_app(config, runtime, root=root)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                assert (await client.post('/api/auth/login', json={'username': 'operator',
                                                                   'password': 'fixture-password'})).status_code == 200
                yield client, runtime


def connection(snapshot: dict, **changes) -> dict:
    saved = snapshot['saved']['connection']
    onebot = saved['onebot'] and {key: value for key, value in saved['onebot'].items()
                                  if key != 'access_token_configured'}
    return {'onebot': onebot, 'owners': saved['owners'], 'timezone': saved['timezone'],
            'max_steps': saved['max_steps'], 'turn_timeout_seconds': saved['turn_timeout_seconds'],
            'max_model_requests': saved['max_model_requests'], 'text_delivery': saved['text_delivery'], **changes}


@pytest.mark.asyncio
async def test_connection_page_adds_telegram_and_feishu_and_keeps_their_secrets(tmp_path):
    async with panel(tmp_path) as (client, _):
        snapshot = (await client.get('/api/host/settings')).json()
        assert snapshot['saved']['connection']['telegram'] is None
        refused = await client.put('/api/host/settings/connection', json=connection(snapshot, telegram={}))
        assert refused.status_code == 422 and 'Bot 令牌' in refused.text
        saved = await client.put('/api/host/settings/connection', json=connection(
            snapshot, telegram={'proxy': 'http://127.0.0.1:7890'}, telegram_token=TOKEN,
            feishu={'bot_id': 'feishu:ou_bot', 'app_id': 'cli_fixture'}, feishu_secret='fixture-secret'))
        assert saved.status_code == 200, saved.text
        projected = saved.json()['saved']['connection']
        assert projected['telegram']['bot_id'] == 'telegram:7001' and 'bot_token' not in projected['telegram']
        assert projected['feishu']['app_id'] == 'cli_fixture' and 'app_secret' not in projected['feishu']
        assert TOKEN not in saved.text and 'fixture-secret' not in saved.text
        assert saved.json()['restart_required']['connection'] is False

        # Leaving the sections out, or sending them without secrets for the same address, keeps the secrets.
        snapshot = saved.json()
        kept = await client.put('/api/host/settings/connection', json=connection(snapshot))
        assert kept.status_code == 200, kept.text
        kept = await client.put('/api/host/settings/connection', json=connection(
            snapshot, telegram={'proxy': None}, feishu={'bot_id': 'feishu:ou_bot', 'app_id': 'cli_fixture',
                                                       'domain': 'feishu'}))
        assert kept.status_code == 200, kept.text
        config = load_host_config(tmp_path)
        assert config.telegram.bot_token == TOKEN and config.telegram.proxy is None
        assert config.feishu.app_secret == 'fixture-secret'

        moved = await client.put('/api/host/settings/connection', json=connection(
            snapshot, telegram={'api_url': 'https://bot-api.example'}))
        assert moved.status_code == 422 and '重新填写 Bot 令牌' in moved.text
        moved = await client.put('/api/host/settings/connection', json=connection(
            snapshot, feishu={'bot_id': 'feishu:ou_bot', 'app_id': 'cli_other'}))
        assert moved.status_code == 422 and '重新填写 App Secret' in moved.text
        replaced = await client.put('/api/host/settings/connection', json=connection(
            snapshot, telegram={}, telegram_token=NEW_TOKEN, feishu=None))
        assert replaced.status_code == 200, replaced.text
        config = load_host_config(tmp_path)
        assert config.telegram.bot_id == 'telegram:7002' and config.feishu is None


@pytest.mark.asyncio
async def test_connection_page_takes_the_qq_account_when_the_root_account_is_another_platform(tmp_path):
    telegram_only = {'bot_id': 'telegram:7001', 'onebot': None, 'telegram': {'bot_id': 'telegram:7001', 'bot_token': TOKEN},
                     'scenes': {'onebot:group:80001': {'persona': 'persona'},
                                'telegram:group:-100123': {'persona': 'persona'}}}
    async with panel(tmp_path, **telegram_only) as (client, _):
        snapshot = (await client.get('/api/host/settings')).json()
        onebot = {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9', 'action_transport': 'websocket',
                  'http_url': None, 'request_timeout_seconds': 10.0, 'ping_interval_seconds': 20.0,
                  'ping_timeout_seconds': 20.0, 'max_frame_bytes': 1048576}
        missing = await client.put('/api/host/settings/connection', json=connection(snapshot, onebot=onebot))
        assert missing.status_code == 422 and 'Bot QQ 号' in missing.text
        saved = await client.put('/api/host/settings/connection', json=connection(
            snapshot, onebot=onebot, bot_id='onebot:90001'))
        assert saved.status_code == 200, saved.text
        config = load_host_config(tmp_path)
        assert config.bot_id == 'onebot:90001' and config.bot_for('telegram:group:-100123') == 'telegram:7001'
        fixed = await client.put('/api/host/settings/connection', json=connection(
            saved.json(), onebot=onebot, bot_id='onebot:90002'))
        assert fixed.status_code == 422


@pytest.mark.asyncio
async def test_connection_test_uses_the_saved_secret_and_never_reads_telegram_updates(tmp_path, monkeypatch):
    requests = []
    monkeypatch.setattr(telegram, '_transport', lambda proxy: telegram_api(requests))
    monkeypatch.setattr(feishu, '_transport', lambda: feishu_api([]))
    async with panel(tmp_path, telegram={'bot_id': 'telegram:7001', 'bot_token': TOKEN}) as (client, _):
        tested = await client.post('/api/host/settings/connection/test', json={'platform': 'telegram', 'telegram': {}})
        assert tested.status_code == 200, tested.text
        assert tested.json() == {'bot_id': 'telegram:7001', 'name': '@len_bot'}
        assert [path.rsplit('/', 1)[1] for path, _ in requests] == ['getMe']
        missing = await client.post('/api/host/settings/connection/test', json={
            'platform': 'feishu', 'feishu': {'bot_id': 'feishu:ou_bot', 'app_id': 'cli_fixture'}})
        assert missing.status_code == 422 and 'App Secret' in missing.text
        tested = await client.post('/api/host/settings/connection/test', json={
            'platform': 'feishu', 'feishu': {'bot_id': 'feishu:ou_x', 'app_id': 'cli_fixture'},
            'feishu_secret': 'fixture-secret'})
        assert tested.status_code == 200 and tested.json()['bot_id'] == 'feishu:ou_bot'


@pytest.mark.asyncio
async def test_available_groups_come_from_every_connected_platform(tmp_path):
    async with panel(tmp_path, telegram={'bot_id': 'telegram:7001', 'bot_token': TOKEN},
                     feishu={'bot_id': 'feishu:ou_bot', 'app_id': 'cli_fixture', 'app_secret': 'fixture'}) as (client, runtime):
        members = {name: runtime.platform.member(name) for name in ('onebot', 'telegram', 'feishu')}
        refused = await client.get('/api/host/settings/scenes/available')
        assert refused.status_code == 409
        members['telegram']._connected = True
        members['telegram']._remember({'chat': {'id': -100123, 'type': 'supergroup', 'title': '合成群'},
                                       'from': {'id': 70001, 'first_name': '合成'}})
        members['telegram']._remember({'chat': {'id': 70001, 'type': 'private'}, 'from': {'id': 70001}})
        listed = await client.get('/api/host/settings/scenes/available')
        assert listed.status_code == 200, listed.text
        assert listed.json()['items'] == [{'scene': 'telegram:group:-100123', 'name': '合成群', 'members': None}]
        state = (await client.get('/api/host/state')).json()
        assert state['connection']['platforms'] == {'onebot': False, 'telegram': True, 'feishu': False}
