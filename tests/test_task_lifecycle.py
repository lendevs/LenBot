"""Task lifecycle at the task service's public operations, with a stand-in execution environment.

The stand-in creates the task directories, runs the image's model bridge as a
host process and replaces Pi with ``fixtures/next/tasks/pi_standin.py``. Model
calls, task API requests and deliveries take the same pipes and proxy as in a
task container; only isolation is absent. File uploads go through ``OneBot``
to a WebSocket peer that answers with NapCat-shaped receipts.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
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
from len_bot.next.work import worker_bridge
from len_bot.next.work.pi_rpc import PiRpc
from len_bot.next.work.sandbox import DockerSandbox, SandboxHandle
from len_bot.next.work.service import WorkTasks
from len_bot.next.work.store import TaskStore
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
        self.live: set[str] = set()
        self.reconciled: list[str] = []

    async def ensure(self, scene, task_id, *, skills=(), input_names=(), on_container=None):
        workspace = self.settings.workspace_root / scene / 'tasks' / task_id
        runtime = self.settings.runtime_root / scene / task_id
        for directory in (workspace / 'out', workspace / '.pi-sessions', runtime / 'home' / '.pi' / 'agent',
                          runtime / 'control'):
            directory.mkdir(parents=True, exist_ok=True)
        name = f'standin-{uuid.uuid4().hex}'
        on_container(name)
        self.live.add(name)
        return SandboxHandle(scene, task_id, name, workspace, runtime / 'home', runtime / 'control')

    async def spawn_model_bridge(self, sandbox, *, proxy, stderr_path, task_request=None):
        configuration = sandbox.control / 'model-bridge.json'
        configuration.write_text(json.dumps({'port': 0, 'max_request_bytes': proxy.limits.max_request_bytes}))
        return await WorkerTransport.spawn(
            [sys.executable, '-I', worker_bridge.__file__, str(configuration)], cwd=sandbox.workspace,
            env=os.environ, stderr_path=stderr_path, proxy=proxy,
            startup_timeout_seconds=self.settings.command_timeout_seconds, task_request=task_request)

    async def spawn_pi(self, sandbox, *, provider, model, stderr_path, proxy_port=None, skills=()):
        rpc = await PiRpc.spawn(
            [sys.executable, '-I', '-u', str(STANDIN), '--provider', provider, '--model', model],
            cwd=sandbox.workspace, stderr_path=stderr_path,
            env={**os.environ, 'LENBOT_CONTROL': str(sandbox.control),
                 'PI_CODING_AGENT_DIR': str(sandbox.home / '.pi' / 'agent')})
        await asyncio.wait_for(rpc.command('get_state'), self.settings.command_timeout_seconds)
        return rpc

    async def stop(self, sandbox):
        self.live.discard(sandbox.container_id)
        shutil.rmtree(sandbox.control)

    async def stop_recorded(self, scene, task_id, container):
        self.live.discard(container)
        self.reconciled.append(container)
        control = self.settings.runtime_root / scene / task_id / 'control'
        if control.exists():
            shutil.rmtree(control)


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


def host_config(root: Path, port: int, *, scene_running: int = 2, scene_containers: int = 4) -> HostConfig:
    tasks = {'enabled': True, 'admins': [ADMIN], 'whitelist': [WHITELISTED],
             'max_running': scene_running, 'max_daily_tasks': 20}
    return HostConfig.model_validate({
        'compaction': {'input_tokens': 2000}, 'mode': 'isolated-multi', 'bot_id': BOT, 'timezone': 'UTC',
        'owners': [OWNER], 'database': root / 'host.sqlite3', 'delivery': 'simulated', 'onebot': None,
        'models': {
            'providers': {'fixture': {'api': 'openai-chat', 'base_url': f'http://127.0.0.1:{port}/v1',
                                      'api_key': 'synthetic-upstream-key'}},
            'roles': {'mind': {'provider': 'fixture', 'model': 'synthetic-worker', 'context_window_tokens': 65536}},
        },
        'worker': {
            'docker_binary': Path('/usr/bin/docker'), 'docker_host': 'unix:///var/run/docker.sock',
            'image': 'lenbot-worker:local', 'uid': 1000, 'gid': 1000, 'model_reasoning': False,
            'workspace_root': root / 'workspaces', 'runtime_root': root / 'runtime',
            'delivery_root': root / 'deliveries', 'max_scene_containers': scene_containers,
            'command_timeout_seconds': 10.0, 'egress': {'enabled': False},
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


def reached(tasks: WorkTasks, id: int, *statuses: str):
    async def wait():
        return await until(lambda: (status := tasks.status(SCENE, id))['status'] in statuses and status)
    return wait()


def event_kinds(tasks: WorkTasks, id: int) -> list[str]:
    rows = tasks.store.db.execute('SELECT kind FROM task_events WHERE scene=? AND task_id=? ORDER BY id', (SCENE, id))
    return [row[0] for row in rows]


def prompted(tasks: WorkTasks, id: int) -> bool:
    return 'native' in event_kinds(tasks, id)


async def delegate(tasks: WorkTasks, goal: str, requester: str = WHITELISTED) -> int:
    created = await tasks.delegate(SCENE, requester=requester, goal=goal, deliverable='报告.txt', context='测试场景')
    assert created['status'] == 'queued'
    return created['id']


@pytest.mark.asyncio
async def test_question_answer_delivery_and_platform_receipts(tmp_path, upstream):
    port, received = upstream
    config = host_config(tmp_path, port)
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
        assert tasks.sandbox.live == set()
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
async def test_append_reaches_the_running_session_and_cancel_stops_it(tmp_path, upstream):
    config = host_config(tmp_path, upstream[0])
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
        assert tasks.sandbox.live == set() and cancelled not in tasks.running
        with pytest.raises(ValueError, match='任务已是 cancelled'):
            await tasks.cancel(SCENE, cancelled, requester=ADMIN)


@pytest.mark.asyncio
async def test_waiting_task_frees_its_slot_and_a_failure_does_not_stall_the_queue(tmp_path, upstream):
    config = host_config(tmp_path, upstream[0], scene_running=1)
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
async def test_identities_roles_and_scene_ownership(tmp_path, upstream):
    config = host_config(tmp_path, upstream[0])
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
async def test_restart_keeps_queue_interrupts_active_work_and_continues_the_same_task(tmp_path, upstream):
    config = host_config(tmp_path, upstream[0], scene_containers=1)
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
        assert tasks.sandbox.reconciled == [container]
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
