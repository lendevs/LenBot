"""Reverse WebSocket handshake: access token carriers, role casing and the rejection log."""

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from len_bot.next.configuration.onebot import OneBotReverse
from len_bot.next.platform.onebot import OneBot

TOKEN = 'synthetic-token'


async def _handshake(headers: dict, query: str = '', token: str = TOKEN) -> tuple[int, list[str]]:
    """The HTTP status the listener answers with (101 when the connection was accepted) and its error log."""
    errors = []
    settings = OneBotReverse(mode='reverse_ws', listen_host='127.0.0.1', listen_port=0, access_token=token)
    async with OneBot(settings, bot_id='onebot:90001', on_event=lambda event: None, on_error=errors.append) as bot:
        url = f'ws://127.0.0.1:{bot.addresses[0][1]}/{query}'
        try:
            async with connect(url, proxy=None, additional_headers={'X-Self-ID': '90001', **headers}):
                return 101, errors
        except InvalidStatus as error:
            return error.response.status_code, errors


@pytest.mark.asyncio
@pytest.mark.parametrize('headers, query', [
    ({'Authorization': f'Bearer {TOKEN}', 'X-Client-Role': 'Universal'}, ''),
    ({'Authorization': f'Token {TOKEN}', 'X-Client-Role': 'Universal'}, ''),
    ({'Authorization': f'bEaReR {TOKEN}', 'X-Client-Role': 'Universal'}, ''),
    ({'Authorization': f'TOKEN {TOKEN}', 'X-Client-Role': 'Universal'}, ''),
    ({'X-Client-Role': 'Universal'}, f'?access_token={TOKEN}'),
    ({'X-Client-Role': 'Universal'}, '?foo=1&access_token=synthetic%2Dtoken'),
    ({'Authorization': f'Bearer {TOKEN}', 'X-Client-Role': 'universal'}, ''),
    ({'Authorization': f'Bearer {TOKEN}', 'X-Client-Role': 'UNIVERSAL'}, ''),
    ({'x-client-role': 'universal'}, f'?access_token={TOKEN}'),
])
async def test_token_in_header_or_query_and_role_in_any_case_are_accepted(headers, query):
    status, errors = await _handshake(headers, query)
    assert status == 101 and errors == []


@pytest.mark.asyncio
@pytest.mark.parametrize('headers, query', [
    ({'Authorization': 'Bearer wrong-token', 'X-Client-Role': 'Universal'}, ''),
    ({'Authorization': f'Basic {TOKEN}', 'X-Client-Role': 'Universal'}, ''),
    ({'Authorization': TOKEN, 'X-Client-Role': 'Universal'}, ''),
    ({'X-Client-Role': 'Universal'}, '?access_token=wrong-token'),
    ({'X-Client-Role': 'Universal'}, '?access_token='),
    ({'X-Client-Role': 'Universal'}, ''),
])
async def test_missing_or_wrong_token_is_refused_and_the_log_never_holds_the_token(headers, query):
    status, errors = await _handshake(headers, query)
    assert status == 403
    log = '\n'.join(errors)
    assert 'access_token' in log and TOKEN not in log and 'wrong-token' not in log


@pytest.mark.asyncio
async def test_a_wrong_role_is_refused_with_the_expected_value_in_the_log():
    status, errors = await _handshake({'Authorization': f'Bearer {TOKEN}', 'X-Client-Role': 'Event'})
    assert status == 400
    assert any('X-Client-Role' in error and 'Event' in error and 'Universal' in error and TOKEN not in error
               for error in errors)


@pytest.mark.asyncio
async def test_without_a_configured_token_any_connection_with_the_role_is_accepted():
    status, errors = await _handshake({'X-Client-Role': 'Universal'}, token='')
    assert status == 101 and errors == []


@pytest.mark.asyncio
async def test_another_account_is_refused_with_both_ids_in_the_log():
    status, errors = await _handshake({'Authorization': f'Bearer {TOKEN}', 'X-Client-Role': 'Universal',
                                       'X-Self-ID': '90002'})
    assert status == 403
    assert any('90002' in error and '90001' in error for error in errors)
