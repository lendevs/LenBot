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
