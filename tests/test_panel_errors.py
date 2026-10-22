"""业务面板和首次配置使用同一错误合同，校验错误不回显凭据。"""

import asyncio

import httpx

from len_bot.next.panel.setup import create_setup_app
from test_next_panel_acts_as_owner import SCENE, exercise, write_instance


def check_error(response, status, code=None):
    assert response.status_code == status, response.text
    payload = response.json()
    assert set(payload) == {'detail'}
    detail = payload['detail']
    assert isinstance(detail['message'], str) and detail['message']
    assert detail['code'] == code
    assert set(detail) <= {'message', 'code', 'data'}
    return detail


def test_host_http_validation_origin_and_resource_errors(tmp_path):
    write_instance(tmp_path, ['onebot:70001'])
    async def check(client):
        await client.post('/api/auth/logout')
        check_error(await client.get('/api/host/state'), 401)
        invalid = await client.post('/api/auth/login', json={'password': 'secret-validation-marker'})
        detail = check_error(invalid, 422, 'validation_error')
        assert detail['data']['errors'][0]['loc'] == ['body', 'username']
        assert all(set(item) == {'loc', 'msg', 'type'} for item in detail['data']['errors'])
        assert 'secret-validation-marker' not in invalid.text
        await client.post('/api/auth/login', json={'username': 'host-operator', 'password': 'synthetic-password'})
        check_error(await client.put('/api/host/control/chat', json={'enabled': True},
                                    headers={'Origin': 'http://other.example'}), 403)
        check_error(await client.get('/api/host/missing'), 404)
        check_error(await client.post('/api/host/state'), 405)
        missing = await client.get(f'/api/host/scenes/{SCENE}/messages/999/images/0')
        check_error(missing, 404)
        assert missing.headers['cache-control'] == 'no-store'
        invalid = await client.post(f'/api/host/schedules?scene={SCENE}',
                                    content='{"note":', headers={'Content-Type': 'application/json'})
        check_error(invalid, 422, 'validation_error')
    exercise(tmp_path, check)


def test_setup_http_and_validation_errors(tmp_path):
    app = create_setup_app(tmp_path, 'test-token', asyncio.Event())
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://localhost') as client:
            check_error(await client.get('/api/setup/plugins'), 401)
            invalid = await client.post('/api/setup', json={'password': 'setup-secret-marker'},
                                       headers={'X-Setup-Token': 'test-token'})
            check_error(invalid, 422, 'validation_error')
            assert 'setup-secret-marker' not in invalid.text
            check_error(await client.get('/api/setup/missing'), 404)
            assert not (tmp_path / 'lenbot.config.json').exists()
    asyncio.run(run())
