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
