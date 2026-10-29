"""Task lifecycle at the task service's public operations, in each task sandbox.

Pi is replaced by ``fixtures/next/tasks/pi_standin.py`` everywhere. Model calls,
task API requests and deliveries take the real pipes, bridge and proxy.

- ``standin``: task directories as in a container, bridge and Pi as plain host
  processes, no isolation; runs on every platform.
- ``bwrap``: the Linux local sandbox as configured, with a task runtime whose
  ``bin/pi`` starts the stand-in; skipped where bwrap cannot create namespaces.

File uploads go through ``OneBot`` to a WebSocket peer that answers with
NapCat-shaped receipts.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from functools import cache
import shutil
import sqlite3
import subprocess
import sys
import uuid

import pytest
import pytest_asyncio
from websockets.asyncio.server import serve

from len_bot.next.config import HostConfig
from len_bot.next.configuration.onebot import OneBotForward
from len_bot.next.platform.file_delivery import SendFileArguments, execute_send_file
from len_bot.next.platform.messages import UploadResult
from len_bot.next.platform.onebot import OneBot
from len_bot.next.storage.store import Store
from len_bot.next.work import service as service_module, worker_bridge
from len_bot.next.work.bwrap import check_local_sandbox
from len_bot.next.work.pi_rpc import PiRpc
from len_bot.next.work.sandbox import DockerSandbox, SandboxHandle
from len_bot.next.work.service import WorkTasks
from len_bot.next.work.store import TaskStore
from len_bot.next.work.worker_egress import EgressTransport
from len_bot.next.work.worker_transport import WorkerTransport

SCENE, OTHER_SCENE = 'onebot:group:80001', 'onebot:group:80002'
BOT, OWNER, ADMIN, WHITELISTED, MEMBER = (f'onebot:{number}' for number in (90001, 70001, 70002, 70003, 70004))
STANDIN = Path(__file__).parent / 'fixtures' / 'next' / 'tasks' / 'pi_standin.py'
VISIBLE_ROOT = '/srv/lenbot/deliveries'
LOGIN = {'status': 'ok', 'retcode': 0, 'data': {'user_id': 90001, 'nickname': '脱敏 Bot'}}


class StandinSandbox(DockerSandbox):
    """Task directories and pipes as in a container, without Docker or isolation."""

    def __init__(self, settings):
        super().__init__(settings)
        self.active: set[str] = set()
        self.reconciled: list[str] = []

    async def ensure(self, scene, task_id, *, skills=(), input_names=(), on_container=None):
        workspace = self.settings.workspace_root / scene / 'tasks' / task_id
        runtime = self.settings.runtime_root / scene / task_id
        for directory in (workspace / 'out', workspace / '.pi-sessions', runtime / 'home' / '.pi' / 'agent',
                          runtime / 'control'):
            directory.mkdir(parents=True, exist_ok=True)
        name = f'standin-{uuid.uuid4().hex}'
        on_container(name)
        self.active.add(name)
        return SandboxHandle(scene, task_id, name, workspace, runtime / 'home', runtime / 'control')

    async def spawn_model_bridge(self, sandbox, *, proxy, stderr_path, task_request=None):
        configuration = sandbox.control / 'model-bridge.json'
        configuration.write_text(json.dumps({'port': 0, 'max_request_bytes': proxy.limits.max_request_bytes}))
        return await WorkerTransport.spawn(
            [sys.executable, '-I', worker_bridge.__file__, str(configuration)], cwd=sandbox.workspace,
            env=os.environ, stderr_path=stderr_path, proxy=proxy,
            startup_timeout_seconds=self.settings.command_timeout_seconds, task_request=task_request)

    async def spawn_egress_bridge(self, sandbox, *, settings, fake_ip_networks, bytes_per_second, before_bytes,
                                  on_connection, on_bytes, stderr_path, public_dns_url=None):
        return await EgressTransport.spawn(
            [sys.executable, str(Path(worker_bridge.__file__).with_name('worker_egress_bridge.py')), '--port', '0',
             '--max-connections', str(settings.max_connections),
             '--header-timeout-seconds', str(settings.header_timeout_seconds)],
            cwd=sandbox.workspace, env=os.environ, stderr_path=stderr_path,
            max_connections=settings.max_connections, connect_timeout_seconds=settings.connect_timeout_seconds,
            fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url, bytes_per_second=bytes_per_second,
            before_bytes=before_bytes, on_connection=on_connection, on_bytes=on_bytes)

    async def spawn_pi(self, sandbox, *, provider, model, stderr_path, proxy_port=None, skills=()):
        proxy = {} if proxy_port is None else {'HTTP_PROXY': f'http://127.0.0.1:{proxy_port}'}
        environment = {name: value for name, value in os.environ.items() if 'proxy' not in name.lower()}
        rpc = await PiRpc.spawn(
            [sys.executable, '-I', '-u', str(STANDIN), '--provider', provider, '--model', model],
            cwd=sandbox.workspace, stderr_path=stderr_path,
            env={**environment, **proxy, 'LENBOT_CONTROL': str(sandbox.control),
                 'PI_CODING_AGENT_DIR': str(sandbox.home / '.pi' / 'agent')})
        await asyncio.wait_for(rpc.command('get_state'), self.settings.command_timeout_seconds)
        return rpc

    async def browser_cli_version(self, sandbox):
        return None

    async def stop(self, sandbox):
        self.active.discard(sandbox.container_id)
        shutil.rmtree(sandbox.control)

    async def stop_recorded(self, scene, task_id, container):
        self.active.discard(container)
        self.reconciled.append(container)
        control = self.settings.runtime_root / scene / task_id / 'control'
        if control.exists():
            shutil.rmtree(control)


@cache
def bwrap_usable() -> bool:
    binary = shutil.which('bwrap')
    return sys.platform == 'linux' and binary is not None and subprocess.run(
        [binary, '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev',
         'true'], capture_output=True).returncode == 0


@pytest.fixture(params=['standin', 'bwrap'])
def environment(request, tmp_path):
    if request.param == 'bwrap' and not bwrap_usable():
        if os.environ.get('LENBOT_REQUIRE_BWRAP'):
            pytest.fail('LENBOT_REQUIRE_BWRAP is set but bwrap cannot create user namespaces')
        pytest.skip('bwrap cannot create user namespaces here')
    return request.param


def task_runtime(root: Path) -> Path:
    """A task runtime laid out like ``build_task_runtime.py``'s, whose ``pi`` is the stand-in."""
    runtime = root / 'task-runtime'
    (runtime / 'node' / 'bin').mkdir(parents=True)
    shutil.copy2(STANDIN, runtime / 'pi_standin.py')
    (runtime / 'lenbot-extension.ts').touch()
    (runtime / 'node' / 'bin' / 'node').touch(mode=0o755)
    python = Path(sys.base_prefix).resolve() / 'bin' / f'python{sys.version_info.major}.{sys.version_info.minor}'
    launcher = runtime / 'node' / 'bin' / 'pi'
    launcher.write_text(f'#!/bin/sh\nexec {python} -I -u /opt/lenbot/pi_standin.py "$@"\n')
    launcher.chmod(0o755)
    return runtime


@pytest_asyncio.fixture
async def upstream():
    """A Chat Completions endpoint that streams one short answer per request."""
    received = []
    event = {'choices': [{'index': 0, 'delta': {'content': '收到'}, 'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 30, 'completion_tokens': 2}}
    stream = ('data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n').encode()

    async def respond(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = dict(line.split(': ', 1) for line in header.split('\r\n')[1:] if ': ' in line)
        received.append(json.loads(await reader.readexactly(int(fields['Content-Length']))))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                     + f'Content-Length: {len(stream)}\r\nConnection: close\r\n\r\n'.encode() + stream)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(respond, '127.0.0.1', 0)
    async with server:
        yield server.sockets[0].getsockname()[1], received


def host_config(root: Path, port: int, environment: str, *, scene_running: int = 2,
                scene_containers: int = 4, egress: dict | None = None, network: dict | None = None,
                worker: dict | None = None) -> HostConfig:
    tasks = {'enabled': True, 'admins': [ADMIN], 'whitelist': [WHITELISTED],
             'max_running': scene_running, 'max_daily_tasks': 20}
    sandbox = ({'sandbox': 'bwrap', 'bwrap_binary': Path(shutil.which('bwrap')), 'task_runtime': task_runtime(root)}
               if environment == 'bwrap' else
               {'docker_binary': root / 'docker', 'docker_host': 'unix:///var/run/docker.sock',
                'image': 'lenbot-worker:local', 'uid': 1000, 'gid': 1000})
    return HostConfig.model_validate({
        'compaction': {'input_tokens': 2000}, 'mode': 'isolated-multi', 'bot_id': BOT, 'timezone': 'UTC',
        'owners': [OWNER], 'database': root / 'host.sqlite3', 'delivery': 'simulated', 'onebot': None,
        **({} if network is None else {'network': network}),
        'models': {
            'providers': {'fixture': {'api': 'openai-chat', 'base_url': f'http://127.0.0.1:{port}/v1',
                                      'api_key': 'synthetic-upstream-key'}},
            'roles': {'mind': {'provider': 'fixture', 'model': 'synthetic-worker', 'context_window_tokens': 65536}},
        },
        'worker': {
            **sandbox, 'model_reasoning': False,
            'workspace_root': root / 'workspaces', 'runtime_root': root / 'runtime',
            'delivery_root': root / 'deliveries', 'max_scene_containers': scene_containers,
            'command_timeout_seconds': 10.0, 'egress': egress or {'mode': 'off'}, **(worker or {}),
        },
        'scenes': {SCENE: {'persona': root / 'unused-role', 'tasks': tasks},
                   OTHER_SCENE: {'persona': root / 'unused-role', 'tasks': tasks}},
    })


@asynccontextmanager
async def task_host(config: HostConfig, database: Path):
    with Store(database) as store:
        scenes = list(config.scenes)
        tasks = WorkTasks(config, store, None, lambda scene: None, skills={scene: () for scene in scenes},
                          memory=None, data_tools={scene: [] for scene in scenes},
                          skill_permissions={scene: [] for scene in scenes},
                          tool_permissions={scene: [] for scene in scenes})
        if config.worker.sandbox == 'docker':
            tasks.sandbox = tasks.files.sandbox = StandinSandbox(tasks.sandbox.settings)
        await tasks.recover()
        await tasks.start()
        try:
            yield tasks
        finally:
            await tasks.close()


async def until(condition, seconds: float = 15):
    async with asyncio.timeout(seconds):
        while not (result := condition()):
            await asyncio.sleep(.02)
    return result


def reached(tasks: WorkTasks, id: int, *statuses: str, seconds: float = 15):
    async def wait():
        return await until(lambda: (status := tasks.status(SCENE, id))['status'] in statuses and status, seconds)
    return wait()


def event_kinds(tasks: WorkTasks, id: int) -> list[str]:
    rows = tasks.store.db.execute('SELECT kind FROM task_events WHERE scene=? AND task_id=? ORDER BY id', (SCENE, id))
    return [row[0] for row in rows]


def open_sandboxes(tasks: WorkTasks) -> set[str]:
    """Sandboxes still open; the bwrap sandbox keeps one session per running task."""
    sandbox = tasks.sandbox
    return sandbox.active if isinstance(sandbox, StandinSandbox) else set(sandbox._sessions)


def prompted(tasks: WorkTasks, id: int) -> bool:
    return 'native' in event_kinds(tasks, id)


async def delegate(tasks: WorkTasks, goal: str, requester: str = WHITELISTED) -> int:
    created = await tasks.delegate(SCENE, requester=requester, goal=goal, deliverable='报告.txt', context='测试场景')
    assert created['status'] == 'queued'
    return created['id']


@pytest.mark.asyncio
async def test_question_answer_delivery_and_platform_receipts(tmp_path, upstream, environment):
    port, received = upstream
    config = host_config(tmp_path, port, environment)
    async with task_host(config, config.database) as tasks:
        id = await delegate(tasks, '整理报告 [进度][提问][交付]')
        waiting = await reached(tasks, id, 'waiting_input')
        question = waiting['question']
        assert (question['method'], question['title']) == ('input', '要哪种格式？')
        with pytest.raises(ValueError, match='问题已经变化'):
            await tasks.answer(SCENE, id, requester=WHITELISTED, text='表格', confirmed=None, question_id='stale')
        with pytest.raises(ValueError, match='text'):
            await tasks.answer(SCENE, id, requester=WHITELISTED, text=None, confirmed=True,
                               question_id=question['id'])
        answered = await tasks.answer(SCENE, id, requester=WHITELISTED, text='表格', confirmed=None,
                                      question_id=question['id'])
        assert answered['status'] == 'answer_received'
        done = await reached(tasks, id, 'done', 'failed')
        assert done['status'] == 'done', done['error']
        assert '回答：表格' in done['summary'] and done['container'] is None and done['question'] is None
        assert done['model_calls'] == 1 and done['tokens']['input'] == 30
        [file] = done['files']
        assert (file['name'], file['note'], file['exists'], file['upload']) == ('报告.txt', '测试交付', True, None)
        assert f"交付编号：{file['id']}" in done['summary']
        kinds = event_kinds(tasks, id)
        for kind in ('progress', 'question', 'answer', 'file', 'finished'):
            assert kind in kinds
        assert kinds[-1] == 'finished'
        assert open_sandboxes(tasks) == set()
        [request] = received
        assert request['model'] == 'synthetic-worker' and '整理报告' in request['messages'][0]['content']

        records = TaskStore(tasks.store)
        [registered] = records.list_files(SCENE, id)
        assert '回答：表格' in Path(registered.path).read_text(encoding='utf-8')
        arguments = SendFileArguments(task_id=id, file_id=file['id'])

        async def send(upload):
            return json.loads(await execute_send_file(records, SCENE, arguments, local_root=config.worker.delivery_root,
                                                      visible_root=VISIBLE_ROOT, upload=upload, on_update=lambda: None))

        async def simulated(scene, path, name):
            return UploadResult('simulated', None, None, None)

        assert (await send(simulated))['status'] == 'simulated'
        assert tasks.status(SCENE, id)['files'][0]['upload']['status'] == 'simulated'

        uploads = []
        receipts = [{'status': 'ok', 'retcode': 0, 'data': {'file_id': '/synthetic-file-id'}},
                    {'status': 'failed', 'retcode': 1200, 'data': None, 'wording': '群文件空间不足'}]

        async def peer(websocket):
            async for frame in websocket:
                request = json.loads(frame)
                if request['action'] == 'get_login_info':
                    await websocket.send(json.dumps({**LOGIN, 'echo': request['echo']}))
                    continue
                uploads.append(request)
                if receipts:
                    await websocket.send(json.dumps({**receipts.pop(0), 'echo': request['echo']}))

        async with serve(peer, '127.0.0.1', 0) as server:
            settings = OneBotForward(mode='forward_ws', request_timeout_seconds=.5,
                                     ws_url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}')
            async with OneBot(settings, bot_id=BOT, on_event=lambda event: None, on_error=lambda error: None) as bot:
                await bot.wait_connected(3)
                uploaded = await send(bot.upload_file)
                assert (uploaded['status'], uploaded['platform_file_id']) == ('uploaded', '/synthetic-file-id')
                failed = await send(bot.upload_file)
                assert (failed['status'], failed['error']) == ('failed', '群文件空间不足')
                unknown = await send(bot.upload_file)
                assert unknown['status'] == 'unconfirmed' and unknown['platform_file_id'] is None
        assert [upload['action'] for upload in uploads] == ['upload_group_file'] * 3
        platform_path = uploads[0]['params']['file']
        assert platform_path == f'{VISIBLE_ROOT}/{SCENE}/{id}/{Path(registered.path).name}'
        assert uploads[0]['params'] == {'group_id': 80001, 'file': platform_path, 'name': '报告.txt'}
        latest = tasks.status(SCENE, id)['files'][0]['upload']
        assert latest['status'] == 'unconfirmed' and latest['ended'] is not None
        assert event_kinds(tasks, id).count('file_upload') == 4


@pytest.mark.asyncio
async def test_append_reaches_the_running_session_and_cancel_stops_it(tmp_path, upstream, environment):
    config = host_config(tmp_path, upstream[0], environment)
    async with task_host(config, config.database) as tasks:
        steered = await delegate(tasks, '等追加 [等待]')
        await until(lambda: prompted(tasks, steered))
        with pytest.raises(PermissionError, match='只能管理自己的任务'):
            await tasks.append(SCENE, steered, requester=MEMBER, text='改成英文')
        assert (await tasks.append(SCENE, steered, requester=WHITELISTED, text='加一页摘要'))['status'] == 'steering_queued'
        done = await reached(tasks, steered, 'done', 'failed')
        assert done['status'] == 'done' and '追加：加一页摘要' in done['summary']
        with pytest.raises(ValueError, match='已结束任务用 continue'):
            await tasks.append(SCENE, steered, requester=WHITELISTED, text='再加一页')

        cancelled = await delegate(tasks, '一直等 [等待]')
        await until(lambda: prompted(tasks, cancelled))
        with pytest.raises(PermissionError):
            await tasks.cancel(SCENE, cancelled, requester=MEMBER)
        result = await tasks.cancel(SCENE, cancelled, requester=ADMIN)
        assert (result['status'], result['error'], result['container']) == ('cancelled', '任务被明确取消', None)
        assert open_sandboxes(tasks) == set() and cancelled not in tasks.running
        with pytest.raises(ValueError, match='任务已是 cancelled'):
            await tasks.cancel(SCENE, cancelled, requester=ADMIN)


@pytest.mark.asyncio
async def test_waiting_task_frees_its_slot_and_a_failure_does_not_stall_the_queue(tmp_path, upstream, environment):
    config = host_config(tmp_path, upstream[0], environment, scene_running=1)
    async with task_host(config, config.database) as tasks:
        asking = await delegate(tasks, '先问一句 [提问]')
        question = (await reached(tasks, asking, 'waiting_input'))['question']
        assert (await reached(tasks, await delegate(tasks, '等待期间完成 [交付]'), 'done', 'failed'))['status'] == 'done'

        failing = await delegate(tasks, '会失败 [失败]')
        following = await delegate(tasks, '排在失败之后')
        assert tasks.status(SCENE, following)['status'] in {'queued', 'running'}
        failed = await reached(tasks, failing, 'done', 'failed')
        assert failed['status'] == 'failed' and 'Pi 未正常完成' in failed['error']
        assert 'finished' in event_kinds(tasks, failing)
        assert (await reached(tasks, following, 'done', 'failed'))['status'] == 'done'

        cancelled = await delegate(tasks, '排队中取消')
        blocker = await delegate(tasks, '占住执行槽 [等待]')
        await tasks.cancel(SCENE, cancelled, requester=WHITELISTED)
        assert tasks.status(SCENE, cancelled)['status'] == 'cancelled'
        await tasks.answer(SCENE, asking, requester=WHITELISTED, text='继续', confirmed=None, question_id=question['id'])
        await until(lambda: prompted(tasks, blocker))
        await tasks.append(SCENE, blocker, requester=WHITELISTED, text='可以结束了')
        assert (await reached(tasks, asking, 'done', 'failed'))['summary'].count('回答：继续') == 1
        assert (await reached(tasks, blocker, 'done', 'failed'))['status'] == 'done'


@pytest.mark.asyncio
async def test_identities_roles_and_scene_ownership(tmp_path, upstream, environment):
    config = host_config(tmp_path, upstream[0], environment)
    async with task_host(config, config.database) as tasks:
        with pytest.raises(PermissionError, match='Bot 账号'):
            await tasks.delegate(SCENE, requester=BOT, goal='冒充', deliverable='无', context='无')
        with pytest.raises(PermissionError, match='委托任务权限'):
            await tasks.delegate(SCENE, requester=MEMBER, goal='越权', deliverable='无', context='无')

        id = await delegate(tasks, '需要确认 [确认]')
        question = (await reached(tasks, id, 'waiting_input'))['question']
        assert (question['method'], question['message']) == ('confirm', '覆盖 out/report.txt')
        with pytest.raises(ValueError, match='Scene onebot:group:80002 has no task'):
            tasks.status(OTHER_SCENE, id)
        with pytest.raises(ValueError, match='has no task'):
            await tasks.cancel(OTHER_SCENE, id, requester=ADMIN)
        assert tasks.list(OTHER_SCENE)['items'] == []
        with pytest.raises(PermissionError, match='只能管理自己的任务'):
            await tasks.answer(SCENE, id, requester=MEMBER, text=None, confirmed=True, question_id=question['id'])
        with pytest.raises(PermissionError, match='Bot'):
            await tasks.answer(SCENE, id, requester=BOT, text=None, confirmed=True, question_id=question['id'])
        with pytest.raises(ValueError, match='confirmed'):
            await tasks.answer(SCENE, id, requester=ADMIN, text='好', confirmed=None, question_id=question['id'])
        await tasks.answer(SCENE, id, requester=ADMIN, text=None, confirmed=True, question_id=question['id'])
        done = await reached(tasks, id, 'done', 'failed')
        assert done['status'] == 'done' and '确认：True' in done['summary']

        owned = await delegate(tasks, '群主发起', requester=OWNER)
        assert (await reached(tasks, owned, 'done', 'failed'))['requester'] == OWNER
        with pytest.raises(PermissionError, match='只能管理自己的任务'):
            await tasks.resume(SCENE, owned, requester=WHITELISTED, text='接着做')


@pytest.mark.asyncio
async def test_restart_keeps_queue_interrupts_active_work_and_continues_the_same_task(tmp_path, upstream, environment):
    config = host_config(tmp_path, upstream[0], environment, scene_containers=1)
    crashed = tmp_path / 'crashed.sqlite3'
    async with task_host(config, config.database) as tasks:
        active = await delegate(tasks, '问完再交付 [提问]')
        await reached(tasks, active, 'waiting_input')
        queued = await delegate(tasks, '排队等容器')
        await asyncio.sleep(.2)
        assert tasks.status(SCENE, queued)['status'] == 'queued'
        container = tasks.status(SCENE, active)['container']
        assert container is not None
        # Committed rows at this moment are what a killed host leaves behind.
        with sqlite3.connect(config.database) as source, sqlite3.connect(crashed) as target:
            source.backup(target)
    with Store(config.database) as store:
        stopped = TaskStore(store).get(SCENE, active)
        assert (stopped.status, stopped.error, stopped.container) == ('failed', '宿主停止，中断活动任务', None)
        assert TaskStore(store).get(SCENE, queued).status == 'queued'

    async with task_host(config, crashed) as tasks:
        assert getattr(tasks.sandbox, 'reconciled', [container]) == [container]
        assert not (config.worker.runtime_root / SCENE / str(active) / 'control').exists()
        interrupted = tasks.status(SCENE, active)
        assert interrupted['status'] == 'failed' and '须显式继续' in interrupted['error']
        assert (await reached(tasks, queued, 'done', 'failed'))['status'] == 'done'

        resumed = await tasks.resume(SCENE, active, requester=WHITELISTED, text='继续并交付 [交付]')
        assert (resumed['id'], resumed['status']) == (active, 'queued')
        question = (await reached(tasks, active, 'waiting_input'))['question']
        await tasks.answer(SCENE, active, requester=WHITELISTED, text='文本', confirmed=None, question_id=question['id'])
        done = await reached(tasks, active, 'done', 'failed')
        assert done['status'] == 'done', done['error']
        assert '第2次执行' in done['summary'] and len(done['files']) == 1
        session = config.worker.workspace_root / SCENE / 'tasks' / str(active) / 'session.jsonl'
        prompts = [json.loads(line)['prompt'] for line in session.read_text(encoding='utf-8').splitlines()]
        assert len(prompts) == 2 and '继续并交付' in prompts[1] and '继续并交付' not in prompts[0]


@pytest.mark.asyncio
async def test_local_sandbox_denies_paths_and_networks_outside_the_task(tmp_path, upstream, environment):
    if environment != 'bwrap':
        pytest.skip('only an isolating sandbox can deny these')
    port, received = upstream
    config = host_config(tmp_path, port, environment)
    neighbour = config.worker.workspace_root / OTHER_SCENE / 'tasks' / '1' / 'out' / 'secret.txt'
    neighbour.parent.mkdir(parents=True)
    neighbour.write_text('其他群的产物')
    (tmp_path / 'lenbot.config.json').write_text('{"models": "synthetic-secret"}')
    host_files = [tmp_path / 'lenbot.config.json', config.database, neighbour, Path.home() / '.bashrc']
    targets = {'writes': ['/usr/lenbot-probe', '/etc/lenbot-probe', '/opt/lenbot/probe', '/run/lenbot/probe',
                          '/inputs-probe', str(tmp_path / 'outside.txt')],
               'reads': [str(path) for path in host_files],
               'connections': [['1.1.1.1', 53], ['10.0.0.1', 80], ['127.0.0.1', port]]}
    async with task_host(config, config.database) as tasks:
        id = (await tasks.delegate(SCENE, requester=WHITELISTED, goal='越界探测 [探测]', deliverable='无',
                                   context='探测：' + json.dumps(targets, ensure_ascii=False)))['id']
        done = await reached(tasks, id, 'done', 'failed')
    assert done['status'] == 'done', done['error']
    results = json.loads(done['summary'].split('探测结果：', 1)[1].splitlines()[0])
    assert len(results) == 13
    denied = {'written', 'read', 'connected'}.isdisjoint
    assert denied(results.values()), results
    assert not (tmp_path / 'outside.txt').exists() and len(received) == 1


@pytest.mark.asyncio
async def test_local_sandbox_check_names_each_step_and_the_first_failure(tmp_path, environment):
    if environment != 'bwrap':
        pytest.skip('needs a working bwrap')
    binary = Path(shutil.which('bwrap'))
    runtime = task_runtime(tmp_path)
    steps = await check_local_sandbox(binary, runtime)
    assert [(step['step'], step['ok']) for step in steps] == [
        ('bwrap', True), ('namespaces', True), ('task_runtime', True), ('sandbox', True), ('pi', True)]
    assert steps[-1]['detail'] == '0.87.1'
    (runtime / 'lenbot-extension.ts').unlink()
    steps = await check_local_sandbox(binary, runtime)
    assert steps[-1] == {'step': 'task_runtime', 'ok': False, 'detail': f'{runtime} 缺少 lenbot-extension.ts'}


def egress_events(tasks: WorkTasks, id: int) -> list[dict]:
    rows = tasks.store.db.execute("SELECT body FROM task_events WHERE scene=? AND task_id=? AND kind='egress_connection' "
                                  'ORDER BY id', (SCENE, id))
    return [json.loads(row[0]) for row in rows]


async def network_task(tasks: WorkTasks, requests: list[dict], seconds: float = 15) -> tuple[dict, list[str]]:
    id = (await tasks.delegate(SCENE, requester=WHITELISTED, goal='联网 [联网]', deliverable='无',
                               context='联网：' + json.dumps(requests)))['id']
    done = await reached(tasks, id, 'done', 'failed', seconds=seconds)
    assert done['status'] == 'done', done['error']
    return done, json.loads(done['summary'].split('联网结果：', 1)[1].splitlines()[0])


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['off', 'allowlist', 'public'])
async def test_network_mode_refuses_hosts_before_dialing_and_records_why(tmp_path, upstream, environment, mode):
    port, received = upstream
    egress = {'mode': mode, 'allowed_hosts': ['example.com', '*.example.org']}
    config = host_config(tmp_path, port, environment, egress=egress)
    requests = [{'url': 'http://not-listed.invalid/'}, {'url': 'http://example.com.evil.invalid/'},
                {'url': 'http://192.0.2.1/'}, {'url': 'http://10.0.0.1/'}]
    async with task_host(config, config.database) as tasks:
        done, results = await network_task(tasks, requests)
        events = egress_events(tasks, done['id'])
    assert len(received) == 1
    if mode == 'off':
        assert results == ['no proxy'] * 4 and events == []
        return
    errors = [event['error'] for event in events]
    assert all(result.startswith('HTTP 502') for result in results), results
    if mode == 'allowlist':
        assert [event['status'] for event in events] == ['refused'] * 4
        assert errors == ['not-listed.invalid 不在出网域名名单中', 'example.com.evil.invalid 不在出网域名名单中',
                          '按域名放行时不能直接连接 IP 地址 192.0.2.1', '按域名放行时不能直接连接 IP 地址 10.0.0.1']
        assert all(error in result for error, result in zip(errors, results))
    else:
        # Public mode looks the names up and checks every address; none of these four is public, so none is dialed.
        assert len(events) == 4 and all(error for error in errors)
        assert '10.0.0.1' in errors[3] and events[2]['status'] != 'refused'


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get('LENBOT_NETWORK_TESTS'), reason='reaches example.com; set LENBOT_NETWORK_TESTS')
async def test_allowed_host_connects_and_the_upload_limit_stops_a_large_body(tmp_path, upstream, environment):
    """LENBOT_NETWORK_TESTS is 1, or this machine's network settings as JSON when a fake-ip proxy answers DNS."""
    value = os.environ['LENBOT_NETWORK_TESTS']
    egress = {'mode': 'allowlist', 'allowed_hosts': ['example.com'], 'max_task_upload_bytes': 8192}
    config = host_config(tmp_path, upstream[0], environment, egress=egress,
                         network=None if value == '1' else json.loads(value))
    async with task_host(config, config.database) as tasks:
        done, results = await network_task(tasks, [
            {'url': 'https://example.com/'}, {'url': 'https://example.com/', 'method': 'POST', 'bytes': 20000}],
            seconds=60)
        events = egress_events(tasks, done['id'])
    assert results[0] == '200' and results[1] != '200', results
    assert [event['host'] for event in events] == ['example.com', 'example.com']
    # The origin may reset the connection after its response; the bytes show the exchange happened.
    assert events[0]['ip'] is not None and events[0]['down'] > 0
    assert '上传字节将超过上限 8192' in events[1]['error'] and events[1]['up'] <= 8192


@pytest.mark.asyncio
async def test_task_over_its_directory_limit_is_stopped_with_the_reason(tmp_path, upstream, environment):
    config = host_config(tmp_path, upstream[0], environment,
                         worker={'max_workspace_bytes': 1024 * 1024, 'storage_check_seconds': .1})
    async with task_host(config, config.database) as tasks:
        id = (await tasks.delegate(SCENE, requester=WHITELISTED, goal='写满 [写入][等待]', deliverable='无',
                                   context='写入：[600000, 600000]'))['id']
        failed = await reached(tasks, id, 'done', 'failed', 'cancelled')
        kinds = event_kinds(tasks, id)
    assert failed['status'] == 'failed' and '超过单任务上限 1048576' in failed['error']
    assert failed['error'].startswith('任务目录占用 ') and 'storage_limit' in kinds


@pytest.mark.asyncio
async def test_low_disk_holds_new_tasks_and_stops_running_ones(tmp_path, upstream, environment, monkeypatch):
    gib = 1024 ** 3
    free = {'bytes': 10 * gib}
    monkeypatch.setattr(service_module, 'disk_free', lambda settings: free['bytes'])
    config = host_config(tmp_path, upstream[0], environment, scene_running=1, worker={'storage_check_seconds': .1})
    async with task_host(config, config.database) as tasks:
        first = await delegate(tasks, '先运行 [等待]')
        await until(lambda: prompted(tasks, first))
        held = await delegate(tasks, '排队等空间 [等待]')
        free['bytes'] = 3 * gib
        with pytest.raises(ValueError, match='暂不接新任务'):
            await tasks.delegate(SCENE, requester=WHITELISTED, goal='空间不足', deliverable='无', context='无')
        await tasks.append(SCENE, first, requester=WHITELISTED, text='结束')
        assert (await reached(tasks, first, 'done', 'failed'))['status'] == 'done'
        await asyncio.sleep(.5)
        assert tasks.status(SCENE, held)['status'] == 'queued'
        free['bytes'] = 10 * gib
        await until(lambda: prompted(tasks, held))
        free['bytes'] = gib
        stopped = await reached(tasks, held, 'done', 'failed')
        kinds = event_kinds(tasks, held)
    assert stopped['status'] == 'failed' and '停止运行中的任务' in stopped['error'] and 'storage_limit' in kinds


@pytest.mark.asyncio
async def test_expired_workspace_is_removed_and_its_delivery_kept(tmp_path, upstream, environment):
    config = host_config(tmp_path, upstream[0], environment,
                         worker={'workspace_retention_days': 1 / 86400, 'storage_check_seconds': .1})
    async with task_host(config, config.database) as tasks:
        id = await delegate(tasks, '交付后到期 [交付]')
        done = await reached(tasks, id, 'done', 'failed')
        workspace = config.worker.workspace_root / SCENE / 'tasks' / str(id)
        await until(lambda: 'workspace_discard_result' in event_kinds(tasks, id), 10)
        [file] = TaskStore(tasks.store).list_files(SCENE, id)
        with pytest.raises(ValueError, match='工作环境已释放'):
            await tasks.resume(SCENE, id, requester=WHITELISTED, text='继续')
    assert done['status'] == 'done' and not workspace.exists()
    assert not (config.worker.runtime_root / SCENE / str(id)).exists() and Path(file.path).is_file()
