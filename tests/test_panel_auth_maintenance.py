"""Password formats and trusted proxies at the panel authentication boundary."""
import hashlib

import httpx
import pytest
from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from len_bot.next.configuration.maintenance import PanelSettings
from len_bot.next.panel.auth import install_panel_auth
from len_bot.web.auth import hash_password, verify_password


def test_password_hash_records_its_iterations():
    salt, password = 'fixture-salt', '密码 fixture'
    stored = hash_password(password, salt)
    assert stored.startswith('pbkdf2_sha256$600000$')
    assert verify_password(password, stored)
    assert not verify_password('wrong', stored)
    PanelSettings(host='127.0.0.1', port=8080, username='fixture', password_hash=stored)
    legacy = salt + '$' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
    assert not verify_password(password, legacy)


def test_iterations_are_limited_to_1_through_10_million(monkeypatch):
    digest = '0' * 64
    calls = []
    monkeypatch.setattr(hashlib, 'pbkdf2_hmac', lambda *arguments: calls.append(arguments[3]) or bytes(32))
    for iterations in ('1', '10000000'):
        record = f'pbkdf2_sha256${iterations}$fixture${digest}'
        PanelSettings(host='127.0.0.1', port=8080, username='fixture', password_hash=record)
        assert verify_password('password', record)
    assert calls == [1, 10_000_000]
    calls.clear()
    for iterations in ('0', '10000001', '99999999', '123456789', '9' * 5000):
        record = f'pbkdf2_sha256${iterations}$fixture${digest}'
        assert not verify_password('password', record)
        with pytest.raises(ValueError, match='password_hash'):
            PanelSettings(host='127.0.0.1', port=8080, username='fixture', password_hash=record)
    assert calls == []


def panel():
    app = FastAPI()
    settings = PanelSettings(host='127.0.0.1', port=8080, username='fixture', password_hash=hash_password('password'))
    install_panel_auth(app, settings, on_logout=lambda: None)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize('peer,trusted,origin,status', [
    ('198.51.100.2', ['127.0.0.1'], 'http://panel.example', 200),
    ('198.51.100.2', ['127.0.0.1'], 'https://panel.example', 403),
    ('127.0.0.1', ['127.0.0.1'], 'https://panel.example', 200),
    ('192.0.2.8', ['192.0.2.0/24'], 'https://panel.example', 200),
])
async def test_origin_and_login_throttle_share_trusted_proxy_scope(peer, trusted, origin, status):
    app = ProxyHeadersMiddleware(panel(), trusted_hosts=trusted)
    headers = {'Origin': origin, 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '203.0.113.7'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=(peer, 1234)),
                                 base_url='http://panel.example') as client:
        response = await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'password'}, headers=headers)
        assert response.status_code == status
        if status == 200:
            port = 443 if origin.startswith('https') else 80
            assert f'lenbot_session_p{port}' in response.cookies
            for _ in range(5):
                response = await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'wrong'}, headers=headers)
                assert response.status_code == 401
            assert (await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'wrong'}, headers=headers)).status_code == 429
            from len_bot.web.auth import clear_login_failures, login_blocked
            identity = '203.0.113.7' if origin.startswith('https') else peer
            assert login_blocked(f'isolated:{identity}')
            clear_login_failures(f'isolated:{identity}')


ROUTES = ('Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n'
          'eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n'
          'eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n')


def test_the_container_trusts_its_docker_gateway(tmp_path, monkeypatch):
    from len_bot.next.panel import auth
    routes = tmp_path / 'route'
    routes.write_text(ROUTES, encoding='ascii')
    assert auth.default_gateway(routes) == '172.18.0.1'
    assert auth.default_gateway(tmp_path / 'missing') is None
    routes.write_text(ROUTES.splitlines(keepends=True)[0] + ROUTES.splitlines(keepends=True)[1], encoding='ascii')
    assert auth.default_gateway(routes) is None
    monkeypatch.setattr(auth, 'default_gateway', lambda: '172.18.0.1')
    settings = PanelSettings(host='0.0.0.0', port=11307, username='fixture', password_hash=hash_password('password'))
    assert auth.trusted_proxies(settings, container=False) == ['127.0.0.1']
    assert auth.trusted_proxies(settings, container=True) == ['127.0.0.1', '172.18.0.1']
    custom = settings.model_copy(update={'trusted_proxies': ['172.18.0.1']})
    assert auth.trusted_proxies(custom, container=True) == ['172.18.0.1']


@pytest.mark.asyncio
async def test_a_reverse_proxy_in_front_of_the_container_keeps_https_writes_and_its_own_throttle(monkeypatch):
    from len_bot.next.panel import auth
    from len_bot.web.auth import clear_login_failures, login_blocked
    monkeypatch.setattr(auth, 'default_gateway', lambda: '172.18.0.1')
    settings = PanelSettings(host='0.0.0.0', port=11307, username='fixture', password_hash=hash_password('password'))
    app = ProxyHeadersMiddleware(panel(), trusted_hosts=auth.trusted_proxies(settings, container=True))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('172.18.0.1', 1234)),
                                 base_url='http://panel.example') as client:
        stranger = {'Origin': 'https://panel.example', 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '203.0.113.7'}
        for _ in range(5):
            assert (await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'wrong'},
                                      headers=stranger)).status_code == 401
        owner = {**stranger, 'X-Forwarded-For': '198.51.100.9'}
        response = await client.post('/api/auth/login', json={'username': 'fixture', 'password': 'password'}, headers=owner)
        assert response.status_code == 200 and login_blocked('isolated:203.0.113.7')
    clear_login_failures('isolated:203.0.113.7')
