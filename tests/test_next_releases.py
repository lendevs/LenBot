"""Published release list parsing and the newer-version answer the panel shows."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from packaging.version import Version

from len_bot.next.panel.routes.updates import register_host_updates
from len_bot.next.runtime.releases import ReleaseCheck, compare, current_version, github_releases


def _release(tag: str, *, prerelease: bool = False, draft: bool = False, body: str | None = '说明') -> dict:
    # Shape of https://api.github.com/repos/<owner>/<repo>/releases, trimmed to the fields that are read.
    return {'tag_name': tag, 'prerelease': prerelease, 'draft': draft, 'body': body,
            'html_url': f'https://github.com/lendevs/LenBot/releases/tag/{tag}', 'assets': []}


def test_github_list_keeps_published_version_tags_newest_first():
    raw = [_release('v0.2.0'), _release('v0.3.0rc1', prerelease=True), _release('v0.2.1', body=None),
           _release('v0.4.0', draft=True), _release('nightly'), _release('vnext')]
    assert github_releases(raw) == [
        {'tag': 'v0.3.0rc1', 'version': '0.3.0rc1', 'prerelease': True, 'notes': '说明'},
        {'tag': 'v0.2.1', 'version': '0.2.1', 'prerelease': False, 'notes': ''},
        {'tag': 'v0.2.0', 'version': '0.2.0', 'prerelease': False, 'notes': '说明'},
    ]


def test_github_error_body_is_refused_with_its_text():
    with pytest.raises(ValueError, match='API rate limit exceeded'):
        github_releases({'message': 'API rate limit exceeded for 203.0.113.1.'})


@pytest.mark.parametrize(('current', 'latest', 'update', 'preview'), [
    ('0.2.0', '0.2.1', True, '0.3.0rc1'),
    ('0.2.1', '0.2.1', False, '0.3.0rc1'),
    ('0.3.0rc1', '0.2.1', False, None),
    ('0.4.0', '0.2.1', False, None),
])
def test_compare_names_newest_stable_and_a_newer_prerelease(current, latest, update, preview):
    releases = github_releases([_release('v0.2.0'), _release('v0.2.1'), _release('v0.3.0rc1', prerelease=True)])
    result = compare(releases, current)
    assert (result['latest'], result['update_available'], result['latest_prerelease']) == (latest, update, preview)
    assert [release['newer'] for release in result['releases']] == [
        Version(release['version']) > Version(current) for release in result['releases']]


@pytest.mark.asyncio
async def test_check_keeps_the_last_answer_and_the_last_error():
    answers = [github_releases([_release('v9.0.0')]), ValueError('GitHub releases response is not a list: {}')]

    async def load():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    check = ReleaseCheck(load, enabled=False, current='0.2.0')
    assert check.state()['update_available'] is None and check.state()['checked_at'] is None
    assert [release['newer'] for release in await check.refresh()] == [True]
    assert check.state()['latest'] == '9.0.0' and check.state()['update_available'] is True
    with pytest.raises(ValueError):
        await check.refresh()
    state = check.state()
    assert state['error'] == 'ValueError: GitHub releases response is not a list: {}'
    assert state['latest'] == '9.0.0'  # The previous answer stays visible next to the newer error.


def test_update_status_reports_version_and_check_without_network(tmp_path):
    def operator(request: Request) -> str:
        return 'operator'

    app = FastAPI()
    check = register_host_updates(app, root=tmp_path, user=operator, check_enabled=False)
    with TestClient(app) as client:
        body = client.get('/api/host/updates').json()
    assert check.enabled is False
    assert body['version'] == current_version() and body['managed'] is False and body['status'] is None
    assert body['notice'] is None and body['rollback_loses_data'] is False
    assert body['check'] == {'enabled': False, 'current': current_version(), 'checked_at': None, 'error': None,
                             'latest': None, 'update_available': None, 'latest_prerelease': None}


def test_managed_update_status_warns_that_rolling_back_loses_later_data(tmp_path):
    """A real updater controller over HTTP; its status and the confirmation notice reach the panel."""
    import sys
    import threading
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/updater'))
    import controller as updater
    from common import write_json

    write_json(tmp_path / 'deployment.json', {'mode': 'native', 'platform': 'linux', 'uv': 'uv', 'release_api': 'x'})
    write_json(tmp_path / 'current.json', {'version': '0.1.0'})
    (tmp_path / 'instance').mkdir()
    control = updater.Controller(tmp_path)
    write_json(control.state_file, {'status': 'rolled_back', 'stage': 'rolled_back', 'rolled_back_from': '0.2.0',
                                    'error': '更新到 0.2.0 失败，已自动恢复到 0.1.0：TimeoutError: x'})
    control.state = updater.read_json(control.state_file)
    for name in ('20261001-080000-0000000a', '20261020-093000-0000000b'):
        (tmp_path / 'backups' / name).mkdir(parents=True)
        (tmp_path / 'backups' / name / 'snapshot.json').write_bytes(b'[]\n')
    http = updater.server(control)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    def operator(request: Request) -> str:
        return 'operator'

    try:
        app = FastAPI()
        register_host_updates(app, root=tmp_path / 'instance', user=operator, check_enabled=False)
        with TestClient(app) as client:
            body = client.get('/api/host/updates').json()
            listed = client.get('/api/host/updates/snapshots').json()
            assert client.delete('/api/host/updates/snapshots/..%2Fupdates').status_code == 404
            assert client.delete('/api/host/updates/snapshots/manual-copy').status_code == 422
            control.state.update(status='failed', snapshot=str(tmp_path / 'backups/20261020-093000-0000000b'),
                                 snapshot_complete=True)
            refused = client.delete('/api/host/updates/snapshots/20261020-093000-0000000b')
            left = client.delete('/api/host/updates/snapshots/20261001-080000-0000000a')
            missing = client.delete('/api/host/updates/snapshots/20261001-080000-0000000a')
    finally:
        http.shutdown()
        http.server_close()
        thread.join()
        control.log.close()
        control.records.close()
    assert body['managed'] is True and body['rollback_loses_data'] is True
    assert body['status']['status'] == 'rolled_back' and body['status']['actions'] == ['prepare']
    assert body['status']['rolled_back_from'] == '0.2.0'
    assert any('丢弃更新开始后写入的数据' in line for line in body['notice'])
    assert any('backups/' in line for line in body['notice'])
    assert [item['name'] for item in listed] == ['20261020-093000-0000000b', '20261001-080000-0000000a']
    assert listed[0] == {'name': '20261020-093000-0000000b', 'created': listed[0]['created'], 'bytes': 3,
                         'complete': True, 'restore': False}
    assert refused.status_code == 409 and '恢复需要使用此快照' in refused.json()['detail']
    assert left.status_code == 200 and [item['name'] for item in left.json()] == ['20261020-093000-0000000b']
    assert missing.status_code == 404 and missing.json()['detail'] == '快照不存在'
