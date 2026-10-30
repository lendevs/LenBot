"""The chat-data tools a task worker calls on the host: what each network mode and role offers, and what they refuse.

The worker is the stand-in of ``test_task_lifecycle`` in each sandbox; its calls take the real task bridge and
route. Search and reader services are keyed providers on a local peer, so the host's own requests are observable.
"""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil
import sys

import pytest

from len_bot.next.chat.tools import task_data_tools
from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from len_bot.next.tools import http_read
from len_bot.next.tools.skills import select_skills, worker_catalog
from len_bot.next.work.service import WorkTasks
from test_next_native_models import peer_server
from test_next_panel_acts_as_owner import SCENE, write_instance
import test_task_lifecycle as lifecycle
from test_task_lifecycle import ADMIN, StandinSandbox, WHITELISTED, reached, task_runtime

# The sandbox parametrization and the model endpoint of the task lifecycle tests.
environment = lifecycle.environment
upstream = lifecycle.upstream

PAGE = 'https://page.example/a'
GUIDE = '# 守则\n\n值班同学每周五更新清单。\n'


def extraction(url: str, text: str = '正文内容') -> tuple[int, str, bytes]:
    body = {'results': [{'url': url, 'raw_content': f'# 页面\n{text}'}], 'failed_results': []}
    return 200, 'application/json', json.dumps(body).encode()


def search_results(*urls: str) -> tuple[int, str, bytes]:
    body = {'query': 'q', 'results': [{'title': f'T{n}', 'url': url, 'content': f'片段{n}', 'score': .9}
                                      for n, url in enumerate(urls)]}
    return 200, 'application/json', json.dumps(body).encode()


def write_config(root: Path, upstream_port: int, peer_port: int | None, environment: str, egress: dict, *,
                 tools: tuple[str, ...], web_read: dict | None) -> None:
    write_instance(root, ['onebot:70001'])
    persona = root / 'persona' / 'persona.yaml'
    persona.write_text(persona.read_text().replace('tools: [tool_search, schedule, schedule_list, schedule_cancel]',
                                                   f'tools: [{", ".join(("tool_search", *tools))}]'))
    (root / 'persona' / 'knowledge').mkdir()
    (root / 'persona' / 'knowledge' / '守则.md').write_text(GUIDE, encoding='utf-8')
    path = root / 'lenbot.config.json'
    source = json.loads(path.read_text())
    source['models']['providers']['local']['base_url'] = f'http://127.0.0.1:{upstream_port}/v1'
    source['models']['roles']['mind']['context_window_tokens'] = 65536
    if peer_port is not None:
        source['models']['providers']['web'] = {'api': 'tavily', 'base_url': f'http://127.0.0.1:{peer_port}',
                                                'api_key': 'synthetic-web-key'}
        source['web_search'] = {'provider': 'tavily', 'connection': 'web'}
    if web_read is not None:
        source['web_read'] = web_read
    sandbox = ({'sandbox': 'bwrap', 'bwrap_binary': str(shutil.which('bwrap')), 'task_runtime': str(task_runtime(root))}
               if environment == 'bwrap' else
               {'docker_binary': str(root / 'docker'), 'docker_host': 'unix:///var/run/docker.sock',
                'image': 'lenbot-worker:local', 'uid': 1000, 'gid': 1000})
    source['worker'] = {**sandbox, 'model_reasoning': False, 'workspace_root': str(root / 'workspaces'),
                        'runtime_root': str(root / 'runtime'), 'delivery_root': str(root / 'deliveries'),
                        'command_timeout_seconds': 10.0, 'egress': egress}
    source['scenes'][SCENE]['tasks'] = {'enabled': True, 'admins': [ADMIN], 'whitelist': [WHITELISTED]}
    path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')


@asynccontextmanager
async def data_host(root: Path, upstream_port: int, environment: str, mode: str, *, replies=(), allowed_hosts=(),
                    tools=('knowledge', 'web_read', 'web_search'), web_read: dict | None = None,
                    max_task_bytes: int | None = None):
    """A host runtime with the scene's tasks wired as in ``host.run``; yields the task service and the peer's requests."""
    if mode != 'off' and sys.platform == 'win32':
        pytest.skip('the egress bridge runs inside the Linux task container; the stand-in cannot host it on Windows')
    received: list = []
    server = await peer_server(list(replies), received)
    async with server:
        egress = {'mode': mode, 'allowed_hosts': list(allowed_hosts),
                  **({} if max_task_bytes is None else {'max_task_bytes': max_task_bytes})}
        write_config(root, upstream_port, server.sockets[0].getsockname()[1], environment, egress, tools=tools,
                     web_read=web_read or {'provider': 'tavily', 'connection': 'web'})
        config = load_host_config(root)
        persona = load_persona(config.scenes[SCENE].persona)
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                tasks = WorkTasks(config, store, None, lambda scene: None,
                                  skills={SCENE: select_skills(worker_catalog(config.worker, SCENE), persona.skills)},
                                  memory=None,
                                  data_tools={SCENE: task_data_tools(config.scene_config(SCENE), persona, platform=False,
                                                                     memory=None)},
                                  skill_permissions={SCENE: persona.skills}, tool_permissions={SCENE: persona.tools})
                NetworkRuntime(config, [(config.scene_config(SCENE), persona)], store, mind, tasks=tasks)
                if config.worker.sandbox == 'docker':
                    tasks.sandbox = tasks.files.sandbox = StandinSandbox(tasks.sandbox.settings)
                await tasks.recover()
                await tasks.start()
                try:
                    yield tasks, received
                finally:
                    await tasks.close()


async def data_task(tasks: WorkTasks, calls: list[dict]) -> tuple[int, list[str], list[dict]]:
    """The data tools the task was offered, and the answer to each call it made."""
    created = await tasks.delegate(SCENE, requester=WHITELISTED, goal='查资料 [数据]', deliverable='无',
                                   context='数据：' + json.dumps(calls, ensure_ascii=False))
    done = await reached(tasks, created['id'], 'done', 'failed', seconds=30)
    assert done['status'] == 'done', done['error']
    lines = done['summary'].splitlines()
    offered = json.loads(next(line for line in lines if line.startswith('数据工具：')).split('：', 1)[1])
    answers = json.loads(next(line for line in lines if line.startswith('数据结果：')).split('：', 1)[1])
    return created['id'], offered, answers


def events(tasks: WorkTasks, id: int, kind: str) -> list[dict]:
    rows = tasks.store.db.execute('SELECT body FROM task_events WHERE scene=? AND task_id=? AND kind=? ORDER BY id',
                                  (SCENE, id, kind))
    return [json.loads(row[0]) for row in rows]


def web_read(url: str) -> dict:
    return {'route': '/task/web-read', 'body': {'url': url}}


@pytest.mark.asyncio
@pytest.mark.parametrize(('mode', 'web'), [('off', []), ('allowlist', ['web_read']), ('public', ['web_read', 'web_search'])])
async def test_the_offered_tools_follow_the_network_mode_and_the_role(tmp_path, upstream, environment, mode, web):
    async with data_host(tmp_path, upstream[0], environment, mode) as (tasks, received):
        _, offered, _ = await data_task(tasks, [])
        assert offered == sorted(['knowledge', *web])
    assert received == []


@pytest.mark.asyncio
async def test_knowledge_follows_the_role_and_the_web_tools_follow_the_mode(tmp_path, upstream, environment):
    guide = {'route': '/task/knowledge', 'body': {'action': 'read', 'scope': 'persona', 'filename': '守则.md'}}
    async with data_host(tmp_path, upstream[0], environment, 'off') as (tasks, received):
        id, offered, [read, search, page] = await data_task(tasks, [
            guide, {'route': '/task/web-search', 'body': {'query': '新闻'}}, web_read(PAGE)])
        assert offered == ['knowledge'] and '每周五更新清单' in read['content']
        for refused in (search, page):
            assert refused['status'] == 502 and 'PermissionError' in refused['error'], refused
        assert [event['ok'] for event in events(tasks, id, 'data_tool')] == [True]
        assert egress_hosts(tasks, id) == []
    assert received == []


@pytest.mark.asyncio
async def test_a_role_without_knowledge_gets_no_knowledge_route(tmp_path, upstream, environment):
    guide = {'route': '/task/knowledge', 'body': {'action': 'list'}}
    async with data_host(tmp_path, upstream[0], environment, 'public', tools=('web_read', 'web_search'),
                         replies=[]) as (tasks, _):
        _, offered, [answer] = await data_task(tasks, [guide])
    assert offered == ['web_read', 'web_search']
    assert answer['status'] == 502 and 'PermissionError' in answer['error']


def egress_hosts(tasks: WorkTasks, id: int) -> list[tuple[str, str]]:
    return [(event['host'], event['status']) for event in events(tasks, id, 'egress_connection')]


@pytest.mark.asyncio
async def test_allowlist_reads_listed_hosts_and_refuses_the_rest_before_any_request(tmp_path, upstream, environment):
    replies = [extraction(PAGE), extraction('https://elsewhere.example/z'), extraction('https://cdn.page.example/b')]
    async with data_host(tmp_path, upstream[0], environment, 'allowlist', replies=replies,
                         allowed_hosts=['page.example', '*.page.example']) as (tasks, received):
        id, offered, answers = await data_task(tasks, [
            web_read(PAGE), web_read('https://other.example/x'), web_read('https://page.example/moved'),
            web_read('https://cdn.page.example/b')])
        assert offered == ['knowledge', 'web_read']
        first, unlisted, moved, subdomain = answers
        assert '正文内容' in first['content'] and PAGE in first['content']
        assert unlisted['status'] == 502 and 'other.example 不在出网域名名单中' in unlisted['error']
        # The service answers for another address than the one asked for: that result is discarded.
        assert moved['status'] == 502 and 'elsewhere.example 不在出网域名名单中' in moved['error']
        assert 'elsewhere' not in json.dumps(moved.get('content', ''))
        assert '正文内容' in subdomain['content']
        # The unlisted address never reaches the provider; each of the other three does.
        assert [body['urls'][0] for _, _, body in received] == [
            PAGE, 'https://page.example/moved', 'https://cdn.page.example/b']
        calls = events(tasks, id, 'data_tool')
        assert [(call['name'], call['ok']) for call in calls] == [('web_read', True)] + [('web_read', False)] * 2 + [
            ('web_read', True)]
        refused = [event for event in events(tasks, id, 'egress_connection') if event['status'] == 'refused']
        assert [event['host'] for event in refused] == ['other.example', 'elsewhere.example']
        assert tasks.status(SCENE, id)['network']['down'] > 0


@pytest.mark.asyncio
async def test_public_mode_searches_and_reads_through_the_host_and_counts_the_bytes(tmp_path, upstream, environment):
    replies = [search_results(PAGE, 'https://page.example/b'), extraction(PAGE, '头条'), extraction(PAGE, '全文')]
    async with data_host(tmp_path, upstream[0], environment, 'public', replies=replies) as (tasks, received):
        id, offered, [searched, read] = await data_task(tasks, [
            {'route': '/task/web-search', 'body': {'query': '新闻'}}, web_read(PAGE)])
        assert offered == ['knowledge', 'web_read', 'web_search']
        assert PAGE in searched['content'] and '全文' in read['content']
        assert [line.split(' ')[1] for line, _, _ in received] == ['/search', '/extract', '/extract']
        usage = tasks.status(SCENE, id)['network']
        assert usage['up'] > 0 and usage['down'] > 0
        assert [call['name'] for call in events(tasks, id, 'data_tool')] == ['web_search', 'web_read']


@pytest.mark.asyncio
async def test_host_side_reads_count_toward_the_task_limit(tmp_path, upstream, environment):
    big = extraction(PAGE, '字' * 4000)
    async with data_host(tmp_path, upstream[0], environment, 'public', replies=[big, big],
                         max_task_bytes=3000) as (tasks, received):
        id, _, [answer, again] = await data_task(tasks, [web_read(PAGE), web_read(PAGE)])
        assert answer['status'] == 502 and '限额 3000' in answer['error'], answer
        assert again['status'] == 502 and '限额 3000' in again['error']
        assert [call['ok'] for call in events(tasks, id, 'data_tool')] == [False, False]
        assert tasks.status(SCENE, id)['network']['down'] <= 3000


class Site:
    """A web server answering every host name with the same pages; ``seen`` is the Host header of each request."""

    def __init__(self, pages: dict[str, tuple[int, dict[str, str], str]]):
        self.pages, self.seen = pages, []

    async def __call__(self, reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        line, *fields = header.split('\r\n')
        host = next(value.strip() for field in fields for key, value in [field.split(':', 1)] if key.lower() == 'host')
        self.seen.append((host.split(':')[0], line.split(' ')[1]))
        status, headers, body = self.pages[line.split(' ')[1]]
        payload = body.encode()
        head = ''.join(f'{key}: {value}\r\n' for key, value in headers.items())
        writer.write(f'HTTP/1.1 {status} Fixture\r\n{head}Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n'.encode()
                     + payload)
        await writer.drain()
        writer.close()


@pytest.mark.asyncio
async def test_the_local_reader_checks_every_redirect_hop_against_the_allowlist(tmp_path, upstream, environment,
                                                                                monkeypatch):
    async def resolves_to_the_site(host, port, fake_ip_networks, public_dns_url, timeout):
        return ['127.0.0.1']

    # Name resolution is the only seam: every name reaches the local site, so the hop checks alone decide.
    monkeypatch.setattr(http_read, 'public_addresses', resolves_to_the_site)
    plain = {'Content-Type': 'text/plain; charset=utf-8'}
    site = Site({'/start': (302, {'Location': 'http://files.example:{port}/file'}, ''),
                 '/file': (200, plain, '清单内容'),
                 '/out': (302, {'Location': 'http://other.example:{port}/secret'}, ''),
                 '/secret': (200, plain, '不应读到')})
    server = await asyncio.start_server(site, '127.0.0.1', 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        for status, headers, _ in site.pages.values():
            for key, value in headers.items():
                headers[key] = value.replace('{port}', str(port))
        async with data_host(tmp_path, upstream[0], environment, 'allowlist', web_read={'provider': 'local'},
                             allowed_hosts=['page.example', 'files.example']) as (tasks, _):
            id, _, answers = await data_task(tasks, [
                web_read(f'http://page.example:{port}/start'), web_read(f'http://page.example:{port}/out'),
                web_read(f'http://nope.example:{port}/file')])
            followed, escaped, unlisted = answers
            assert '清单内容' in followed['content']
            assert escaped['status'] == 502 and 'other.example 不在出网域名名单中' in escaped['error']
            assert unlisted['status'] == 502 and 'nope.example 不在出网域名名单中' in unlisted['error']
            assert site.seen == [('page.example', '/start'), ('files.example', '/file'), ('page.example', '/out')]
            assert [host for host, _ in egress_hosts(tasks, id)] == [
                'page.example', 'files.example', 'page.example', 'other.example', 'nope.example']
            assert [status for _, status in egress_hosts(tasks, id)][3:] == ['refused', 'refused']


@pytest.mark.asyncio
async def test_recall_chat_is_served_from_the_store(tmp_path, upstream, environment):
    async with data_host(tmp_path, upstream[0], environment, 'off', tools=('knowledge', 'recall_chat')) as (tasks, _):
        _, offered, [answer] = await data_task(tasks, [{'route': '/task/recall-chat', 'body': {'query': '周五'}}])
    assert 'recall_chat' in offered and 'status' not in answer and answer['content']
