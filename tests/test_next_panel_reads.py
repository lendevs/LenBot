"""Panel reads must leave the message loop available while SQLite is locked."""

import asyncio
import sqlite3
import time

import pytest

from test_next_panel_acts_as_owner import exercise, write_instance, SCENE


@pytest.mark.parametrize('path,status', [
    ('/api/host/overview', 200),
    ('/api/host/usage', 200),
    (f'/api/host/scenes/{SCENE}/turns/missing', 404),
    (f'/api/host/scenes/{SCENE}/turns/missing/export', 404),
])
def test_panel_database_reads_do_not_block_the_loop(tmp_path, path, status):
    write_instance(tmp_path, ['onebot:70001'])

    async def check(client):
        with sqlite3.connect(tmp_path / 'host.sqlite3') as blocker:
            blocker.execute('BEGIN EXCLUSIVE')
            request = asyncio.create_task(client.get(path))
            started = time.perf_counter()
            await asyncio.sleep(0.03)
            delay = time.perf_counter() - started
            pending = not request.done()
            blocker.rollback()
        response = await request
        assert delay < 0.1
        assert pending
        assert response.status_code == status, response.text
        if path == '/api/host/overview':
            cached = await client.get(path)
            assert cached.json() == response.json()

    exercise(tmp_path, check)
