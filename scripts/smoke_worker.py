"""Run one task through a real worker image: Pi, the model bridge, a question and a delivery.

The model is a loopback Chat Completions endpoint that answers from a fixed
script: run a shell command, ask the requester, deliver the file, then finish.
Everything else is the task service, Docker sandbox and Pi as deployed.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from len_bot.next.config import HostConfig
from len_bot.next.storage.store import Store
from len_bot.next.work.service import WorkTasks
from len_bot.next.work.store import TaskStore

SCENE = 'onebot:group:80001'
REQUESTER = 'onebot:70001'
REPORT = 'worker smoke report'


def chunk(body: dict) -> bytes:
    return b'data: ' + json.dumps(body, ensure_ascii=False).encode() + b'\n\n'


def scripted_reply(request: dict, answers: list[str]) -> bytes:
    """One streamed step chosen by how many tool results the conversation already has."""
    tools = {tool['function']['name']: tool['function'] for tool in request.get('tools', [])}
    results = [message for message in request['messages'] if message['role'] == 'tool']
    steps = [
        ('bash', {'command': f"mkdir -p out && printf '%s\\n' '{REPORT}' \"uid=$(id -u)\" > out/report.txt"}),
        ('ask_requester', {'question': '报告用什么标题？'}),
        ('deliver_file', {'path': 'out/report.txt', 'name': '报告.txt', 'note': 'worker 冒烟'}),
    ]
    usage = {'choices': [], 'usage': {'prompt_tokens': 50, 'completion_tokens': 5}}
    if len(results) == 2:
        answers.append(results[-1]['content'] if isinstance(results[-1]['content'], str)
                       else json.dumps(results[-1]['content'], ensure_ascii=False))
    if len(results) < len(steps):
        name, arguments = steps[len(results)]
        missing = set(arguments) - set(tools[name]['parameters']['properties'])
        if missing:
            raise ValueError(f'Pi tool {name} lacks parameters {sorted(missing)}: {tools[name]}')
        call = {'index': 0, 'id': f'call_{len(results) + 1}', 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}
        body = [chunk({'choices': [{'index': 0, 'delta': {'role': 'assistant', 'tool_calls': [call]},
                                    'finish_reason': None}]}),
                chunk({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})]
    else:
        body = [chunk({'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': '完成'},
                                    'finish_reason': 'stop'}]})]
    return b''.join(body) + chunk(usage) + b'data: [DONE]\n\n'


async def serve_model(requests: list[dict], answers: list[str]):
    async def respond(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = {name.lower(): value for name, _, value in
                  (line.partition(': ') for line in header.split('\r\n')[1:]) if value}
        request = json.loads(await reader.readexactly(int(fields['content-length'])))
        requests.append(request)
        try:
            stream, status = scripted_reply(request, answers), b'200 OK'
        except Exception as error:
            stream, status = json.dumps({'error': {'message': str(error)}}).encode(), b'400 Bad Request'
        writer.write(b'HTTP/1.1 ' + status + b'\r\nContent-Type: text/event-stream\r\n'
                     + f'Content-Length: {len(stream)}\r\nConnection: close\r\n\r\n'.encode() + stream)
        await writer.drain()
        writer.close()
    return await asyncio.start_server(respond, '127.0.0.1', 0)


def docker_host() -> str:
    configured = os.environ.get('DOCKER_HOST', '')
    if configured.startswith('unix:///'):
        return configured
    desktop = Path.home() / '.docker/run/docker.sock'
    return f'unix://{desktop}' if desktop.exists() else 'unix:///var/run/docker.sock'


def task_containers(docker: str, host: str) -> set[str]:
    output = subprocess.run([docker, '--host', host, 'ps', '-aq', '--no-trunc', '--filter', 'name=lenbot-next-'],
                            check=True, capture_output=True, text=True).stdout
    return set(output.split())


async def until(condition, seconds: float):
    async with asyncio.timeout(seconds):
        while not (result := condition()):
            await asyncio.sleep(.1)
    return result


async def smoke(image: str, docker: str, host: str, root: Path) -> dict:
    requests: list[dict] = []
    answers: list[str] = []
    server = await serve_model(requests, answers)
    port = server.sockets[0].getsockname()[1]
    config = HostConfig.model_validate({
        'compaction': {'input_tokens': 2000}, 'mode': 'isolated-multi', 'bot_id': 'onebot:90001', 'timezone': 'UTC',
        'owners': [REQUESTER], 'database': root / 'host.sqlite3', 'delivery': 'simulated', 'onebot': None,
        'models': {
            'providers': {'smoke': {'api': 'openai-chat', 'base_url': f'http://127.0.0.1:{port}/v1',
                                    'api_key': 'synthetic-upstream-key'}},
            'roles': {'mind': {'provider': 'smoke', 'model': 'scripted-worker', 'context_window_tokens': 65536}},
        },
        'worker': {
            'docker_binary': Path(docker), 'docker_host': host, 'image': image,
            'uid': os.getuid(), 'gid': os.getgid(), 'model_reasoning': False,
            'workspace_root': root / 'workspaces', 'runtime_root': root / 'runtime',
            'delivery_root': root / 'deliveries', 'egress': {'enabled': False},
        },
        'scenes': {SCENE: {'persona': root / 'unused-role', 'tasks': {'enabled': True}}},
    })
    before = task_containers(docker, host)
    async with server:
        with Store(config.database) as store:
            tasks = WorkTasks(config, store, None, lambda scene: None, skills={SCENE: ()}, memory=None,
                              data_tools={SCENE: []}, skill_permissions={SCENE: []}, tool_permissions={SCENE: []})
            await tasks.recover()
            await tasks.start()
            try:
                created = await tasks.delegate(SCENE, requester=REQUESTER, goal='写一份冒烟报告',
                                               deliverable='报告.txt', context='worker 镜像冒烟')
                id = created['id']
                status = lambda: tasks.status(SCENE, id)
                waiting = await until(lambda: status()['status'] in {'waiting_input', 'done', 'failed'} and status(), 180)
                if waiting['status'] != 'waiting_input':
                    raise RuntimeError(f'task did not ask its question: {json.dumps(waiting, ensure_ascii=False)}')
                question = waiting['question']
                await tasks.answer(SCENE, id, requester=REQUESTER, text='冒烟标题', confirmed=None,
                                   question_id=question['id'])
                done = await until(lambda: status()['status'] in {'done', 'failed', 'cancelled'} and status(), 180)
                files = TaskStore(store).list_files(SCENE, id)
            finally:
                await tasks.close()
    after = task_containers(docker, host)
    if done['status'] != 'done':
        raise RuntimeError(f'task ended {done["status"]}: {done["error"]}')
    [file] = files
    report = Path(file.path).read_text(encoding='utf-8')
    checks = {
        'question': (question['method'], question['title']) == ('input', '报告用什么标题？'),
        'answer_reached_model': any('冒烟标题' in answer for answer in answers),
        'delivery': report.startswith(REPORT) and f'uid={os.getuid()}' in report,
        'model_calls': done['model_calls'] == 4 and len(requests) == 4,
        'containers_removed': after <= before and done['container'] is None,
    }
    if not all(checks.values()):
        raise RuntimeError(f'worker smoke checks failed: {checks}; status={json.dumps(done, ensure_ascii=False)}')
    inspect = json.loads(subprocess.run([docker, '--host', host, 'image', 'inspect', image],
                                        check=True, capture_output=True, text=True).stdout)[0]
    version = subprocess.run([docker, '--host', host, 'run', '--rm', '--network', 'none', '--entrypoint', 'pi',
                              image, '--version'], check=True, capture_output=True, text=True).stdout.strip()
    return {'image': image, 'image_id': inspect['Id'], 'architecture': inspect['Architecture'],
            'pi': version, 'host': f'{platform.system()} {platform.machine()}',
            'summary': done['summary'], 'checks': checks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='lenbot-worker:local')
    parser.add_argument('--docker', default=shutil.which('docker'))
    parser.add_argument('--docker-host', default=docker_host())
    arguments = parser.parse_args()
    if arguments.docker is None:
        sys.exit('docker CLI not found; pass --docker')
    with tempfile.TemporaryDirectory(prefix='lenbot-worker-smoke-') as directory:
        result = asyncio.run(smoke(arguments.image, arguments.docker, arguments.docker_host,
                                   Path(directory).resolve()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
