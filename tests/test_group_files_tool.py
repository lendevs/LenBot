"""The group_files tool lists this group's actual files; downloads stay within the size limit."""

import asyncio
import json

import httpx
import pytest

from len_bot.next.platform.platform_tools import GroupFilesArguments, download_group_file, list_group_files

ROOT = {'status': 'ok', 'retcode': 0, 'data': {
    'files': [
        {'file_id': '/a1', 'busid': 102, 'file_name': '销量.xlsx', 'file_size': 2048,
         'upload_time': 1792800000, 'uploader_name': '群友甲'},
        {'file_id': '/b2', 'busid': 102, 'file_name': '会议纪要.pdf', 'file_size': 4096,
         'upload_time': 1792803600, 'uploader_name': '群友乙'},
    ],
    'folders': [{'folder_id': '/f1', 'folder_name': '资料', 'total_file_count': 3}]}}


def test_files_are_listed_for_this_group_and_filtered_by_name() -> None:
    calls = []

    async def call(action, params):
        calls.append((action, params))
        return ROOT

    result = json.loads(asyncio.run(list_group_files('onebot:group:80001', 'Asia/Shanghai',
                                                     GroupFilesArguments(name='XLSX'), call)))
    assert calls[0][0] == 'get_group_root_files' and calls[0][1]['group_id'] == 80001
    assert [item['name'] for item in result['files']] == ['销量.xlsx']
    assert result['files'][0]['uploaded'] == '2026-10-24T08:00+08:00'
    assert result['folders'] == [{'folder_id': '/f1', 'name': '资料', 'files': 3}]


def test_download_reads_the_address_onebot_gives_and_refuses_large_files() -> None:
    async def call(action, params):
        assert (action, params) == ('get_group_file_url', {'group_id': 80001, 'file_id': '/a1', 'busid': 102})
        return {'status': 'ok', 'retcode': 0, 'data': {'url': 'https://files.example/a1'}}

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * 100))
    assert asyncio.run(download_group_file(call, '80001', '/a1', 102, 100, transport=transport)) == b'x' * 100
    with pytest.raises(ValueError, match='max_file_bytes'):
        asyncio.run(download_group_file(call, '80001', '/a1', 102, 99, transport=transport))


def test_panel_delegate_downloads_the_picked_group_files(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from len_bot.next.config import load_host_config
    from len_bot.next.models.client import ChatModel
    from len_bot.next.panel.app import create_app
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.platform import platform_tools
    from len_bot.next.runtime.network import NetworkRuntime
    from len_bot.next.storage.store import Store
    from test_next_panel_acts_as_owner import SCENE, write_instance

    write_instance(tmp_path, ['onebot:70001'])
    path = tmp_path / 'lenbot.config.json'
    path.write_text(json.dumps({**json.loads(path.read_text()),
                                'onebot': {'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'}}))
    config = load_host_config(tmp_path)
    downloaded, delegated = [], []

    async def download(call, group_id, file_id, busid, max_bytes):
        downloaded.append((group_id, file_id, busid, max_bytes))
        return b'month,total\n10,3\n'

    async def delegate(scene, **fields):
        delegated.append((scene, fields))
        return {'id': 1}

    monkeypatch.setattr(platform_tools, 'download_group_file', download)

    async def run():
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                runtime = NetworkRuntime(config, [(config.scene_config(SCENE), load_persona(config.scenes[SCENE].persona))],
                                         store, mind)
                runtime.tasks = SimpleNamespace(settings=SimpleNamespace(max_file_bytes=1024), delegate=delegate)
                app = create_app(config, runtime, root=tmp_path)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                    await client.post('/api/auth/login', json={'username': 'host-operator', 'password': 'synthetic-password'})
                    body = {'goal': '汇总销量', 'deliverable': 'summary.csv'}
                    plain = await client.post(f'/api/host/tasks/delegate?scene={SCENE}', json=body)
                    assert plain.status_code == 200, plain.text
                    picked = await client.post(f'/api/host/tasks/delegate?scene={SCENE}', json={
                        **body, 'group_files': [{'file_id': '/a1', 'busid': 102, 'name': 'sales.csv'}]})
                    assert picked.status_code == 200, picked.text
    asyncio.run(run())

    assert downloaded == [('80001', '/a1', 102, 1024)]
    assert [fields['downloads'] for _, fields in delegated][0] == []
    [item] = delegated[1][1]['downloads']
    assert (item.name, item.data, item.source) == ('sales.csv', b'month,total\n10,3\n',
                                                   {'group_file': {'file_id': '/a1', 'busid': 102}})
    assert 'group_files' not in delegated[1][1]
