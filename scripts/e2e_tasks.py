"""End-to-end task scenarios for a reviewer's model: search and cross-check, file analysis with a follow-up, a dynamic page.

Each scenario runs in its own temporary instance: a host with simulated sending (no QQ), the real task service,
and the real worker, a worker image under ``--sandbox docker`` or a task runtime (``build_task_runtime.py``) under
``--sandbox bwrap``. The model comes from ``--config``, an instance config whose ``models`` section holds the
connection (``web_search``, ``web_read`` and ``network`` are taken from it when present). ``--scripted`` replaces
the model, search and reader with fixed local ones to exercise the script itself; it judges no quality.

  S1 search and cross-check   egress public; a Markdown report with at least 3 distinct source sites
  S2 file analysis, follow-up  a seeded CSV as scene material; XLSX and PNG, then ``task continue`` with another
                               dimension; the second delivery must differ from the first
  S3 dynamic page             Docker only, egress public; ``lenbot-browser`` on a JavaScript page (--browser-url),
                               the first two pages as CSV, plus an HTML or PDF report

Output directory: ``e2e-report.json`` and ``e2e-report.md``, plus every delivered file under ``<scenario>/<run>/``.
The exit status is non-zero when a task does not finish or an automatic check fails.
"""

import argparse
import asyncio
import csv
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter
from urllib.parse import urlsplit

from len_bot.next.chat.tools import task_data_tools
from len_bot.next.config import load_host_config
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from len_bot.next.work.service import WorkTasks
from len_bot.next.tools.skills import select_skills, worker_catalog
from len_bot.web.auth import hash_password

SCENE = 'onebot:group:80001'
OWNER = 'onebot:70001'
BOT = 'onebot:90001'
ANSWER = '请按你的最佳判断继续，不再提问。'
DEFAULT_QUESTION = 'Python 当前最新的稳定版本是哪个，相比上一个主要版本新增了哪些主要特性？'
DEFAULT_BROWSER_URL = 'https://quotes.toscrape.com/js/'
FOLLOW_UP = '换一个维度重算：改为按产品统计销量总和与平均值，图表改成横向条形图，文件名带上“按产品”，重新交付。'
SOURCES = ('https://docs.example.org/whatsnew', 'https://news.example.net/release', 'https://blog.example.com/tour')


def seeded_sales() -> bytes:
    """A fixed-seed CSV: 200 rows of region, product, units and unit price."""
    random.seed(20261030)
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(['日期', '地区', '产品', '销量', '单价'])
    for index in range(200):
        writer.writerow([f'2026-{index % 12 + 1:02d}-{index % 28 + 1:02d}', random.choice(['华北', '华东', '华南', '西部']),
                         random.choice(['甲', '乙', '丙']), random.randint(1, 60), random.choice([12.5, 18, 25.5, 40])])
    return buffer.getvalue().encode('utf-8')


# ---------------------------------------------------------------- scripted model, search and reader

def chunk(body: dict) -> bytes:
    return b'data: ' + json.dumps(body, ensure_ascii=False).encode() + b'\n\n'


S2_FIRST = r'''mkdir -p out && python3 - <<'PY' 2>&1
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
frame = pd.read_csv('/inputs/sales.csv')
table = frame.groupby('地区')['销量'].agg(['sum', 'mean']).reset_index()
table.to_excel('out/按地区统计.xlsx', index=False)
plt.figure()
plt.bar(table['地区'], table['sum'])
plt.title('各地区销量')
plt.savefig('out/按地区图表.png')
print(table.to_dict('records'))
PY'''
S2_SECOND = r'''python3 - <<'PY' 2>&1
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
frame = pd.read_csv('/inputs/sales.csv')
table = frame.groupby('产品')['销量'].agg(['sum', 'mean']).reset_index()
table.to_excel('out/按产品统计.xlsx', index=False)
plt.figure()
plt.barh(table['产品'], table['sum'])
plt.title('各产品销量')
plt.savefig('out/按产品图表.png')
print(table.to_dict('records'))
PY'''
S3_BROWSE = '''set -e
mkdir -p out
lenbot-browser open {url}
lenbot-browser snapshot > out/page1.json
lenbot-browser pdf --filename=out/browser/page1.pdf
lenbot-browser close'''
S3_WRITE = r'''python3 - <<'PY' 2>&1
import csv, html, re
text = open('out/page1.json', encoding='utf-8').read()
quotes = re.findall(r'[“"]([^”"\n]{8,200})[”"]', text)
with open('out/quotes.csv', 'w', newline='', encoding='utf-8') as handle:
    writer = csv.writer(handle)
    writer.writerow(['页', '语录'])
    writer.writerows([1, quote] for quote in quotes)
open('out/report.html', 'w', encoding='utf-8').write(
    '<meta charset="utf-8"><h1>语录</h1><ul>' + ''.join(f'<li>{html.escape(q)}</li>' for q in quotes) + '</ul>')
print(len(quotes))
PY'''


def scripted_steps(label: str, phase: int, browser_url: str) -> list[tuple[str, dict]]:
    if label == 'S1':
        report = '\n'.join(['# 报告', *(f'- 结论 {index + 1}：见 {url}（资料日期 {date.today()}）'
                                      for index, url in enumerate(SOURCES))])
        return [('web_search', {'query': '示例问题'}), *(('web_read', {'url': url}) for url in SOURCES),
                ('bash', {'command': f"mkdir -p out && cat > out/report.md <<'MD'\n{report}\nMD"}),
                ('deliver_file', {'path': 'out/report.md', 'name': 'report.md', 'note': 'S1'})]
    if label == 'S2':
        return ([('bash', {'command': S2_FIRST}),
                 ('deliver_file', {'path': 'out/按地区统计.xlsx', 'name': '按地区统计.xlsx', 'note': ''}),
                 ('deliver_file', {'path': 'out/按地区图表.png', 'name': '按地区图表.png', 'note': ''})] if phase == 0 else
                [('bash', {'command': S2_SECOND}),
                 ('deliver_file', {'path': 'out/按产品统计.xlsx', 'name': '按产品统计.xlsx', 'note': ''}),
                 ('deliver_file', {'path': 'out/按产品图表.png', 'name': '按产品图表.png', 'note': ''})])
    return [('bash', {'command': S3_BROWSE.format(url=browser_url)}), ('bash', {'command': S3_WRITE}),
            ('deliver_file', {'path': 'out/quotes.csv', 'name': 'quotes.csv', 'note': ''}),
            ('deliver_file', {'path': 'out/report.html', 'name': 'report.html', 'note': ''})]


def scripted_reply(request: dict, browser_url: str) -> bytes:
    """The next step of the scenario named in the conversation, by how many tool results follow the last request."""
    messages = request['messages']
    text = lambda message: message['content'] if isinstance(message['content'], str) else json.dumps(message['content'], ensure_ascii=False)
    label = next(name for name in ('S1', 'S2', 'S3') if f'场景 {name}' in ' '.join(text(m) for m in messages if m['role'] == 'user'))
    turn = max((index for index, message in enumerate(messages) if message['role'] == 'user' and '换一个维度' in text(message)),
               default=None)
    results = [m for m in messages[(turn or 0):] if m['role'] == 'tool']
    steps = scripted_steps(label, 0 if turn is None else 1, browser_url)
    tools = {tool['function']['name']: tool['function'] for tool in request.get('tools', [])}
    usage = {'choices': [], 'usage': {'prompt_tokens': 50, 'completion_tokens': 5}}
    if len(results) < len(steps):
        name, arguments = steps[len(results)]
        if name not in tools:
            raise ValueError(f'the worker offers no tool {name}; it offers {sorted(tools)}')
        missing = set(arguments) - set(tools[name]['parameters']['properties'])
        if missing:
            raise ValueError(f'tool {name} lacks parameters {sorted(missing)}: {tools[name]}')
        call = {'index': 0, 'id': f'call_{turn or 0}_{len(results)}', 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}
        body = [chunk({'choices': [{'index': 0, 'delta': {'role': 'assistant', 'tool_calls': [call]}, 'finish_reason': None}]}),
                chunk({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})]
    else:
        body = [chunk({'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': '完成'}, 'finish_reason': 'stop'}]})]
    return b''.join(body) + chunk(usage) + b'data: [DONE]\n\n'


async def serve(handler):
    """One request per connection: ``handler(path, body)`` returns (status, content type, bytes)."""
    async def respond(reader, writer):
        header = (await reader.readuntil(b'\r\n\r\n')).decode()
        line, *fields = header.split('\r\n')
        fields = {key.lower(): value.strip() for field in fields if ':' in field for key, value in [field.split(':', 1)]}
        raw = await reader.readexactly(int(fields.get('content-length', 0)))
        try:
            status, kind, content = handler(line.split(' ')[1], json.loads(raw) if raw else None)
        except Exception as error:
            print(f'scripted endpoint {line}: {type(error).__name__}: {error}', file=sys.stderr)
            status, kind, content = 400, 'application/json', json.dumps({'error': {'message': str(error)}}).encode()
        writer.write(f'HTTP/1.1 {status} Fixture\r\nContent-Type: {kind}\r\nContent-Length: {len(content)}\r\n'
                     'Connection: close\r\n\r\n'.encode() + content)
        await writer.drain()
        writer.close()
    return await asyncio.start_server(respond, '127.0.0.1', 0)


def web_service(path: str, body: dict) -> tuple[int, str, bytes]:
    """Tavily-shaped search and extraction; the sources are fixed, the page text names the address asked for."""
    if path.endswith('/search'):
        answer = {'query': body['query'], 'results': [{'title': f'来源{index + 1}', 'url': url, 'content': '摘要', 'score': .9}
                                                      for index, url in enumerate(SOURCES)]}
    else:
        url = body['urls'][0]
        answer = {'results': [{'url': url, 'raw_content': f'# {urlsplit(url).hostname}\n页面正文，资料日期 {date.today()}。'}],
                  'failed_results': []}
    return 200, 'application/json', json.dumps(answer, ensure_ascii=False).encode()


# ---------------------------------------------------------------- the instance

def write_instance(root: Path, models: dict, web: dict, network: dict | None, sandbox: dict, mode: str) -> None:
    persona = root / 'persona'
    persona.mkdir(parents=True)
    tools = ['tool_search', 'knowledge', *(name for name in ('web_read', 'web_search') if name in web)]
    (persona / 'persona.yaml').write_text(
        'id: e2e-persona\nname: 验收角色\nbrief: 端到端验收。\nbehavior: 不主动表达。\nself_reference: [我]\n'
        f'aliases: []\ntools: [{", ".join(tools)}]\nskills: all\nstyles: []\n', encoding='utf-8')
    (persona / 'voice.md').write_text('简短。', encoding='utf-8')
    (persona / 'boundaries.md').write_text('仅限隔离验收。', encoding='utf-8')
    (persona / 'examples.yaml').write_text('[]\n', encoding='utf-8')
    source = {
        'compaction': {'input_tokens': 2000}, 'mode': 'isolated-multi', 'bot_id': BOT, 'timezone': 'UTC', 'owners': [OWNER],
        'onebot': None, 'database': 'host.sqlite3', 'delivery': 'simulated', 'logging': {'directory': 'logs'},
        'panel': {'host': '127.0.0.1', 'port': 0, 'username': 'e2e',
                  'password_hash': hash_password('e2e-password', salt='e2e-salt')},
        'models': models, **web, **({} if network is None else {'network': network}),
        'worker': {**sandbox, 'model_reasoning': False, 'workspace_root': str(root / 'workspaces'),
                   'runtime_root': str(root / 'runtime'), 'delivery_root': str(root / 'deliveries'),
                   'egress': {'mode': mode}},
        'scenes': {SCENE: {'persona': 'persona', 'tasks': {'enabled': True}}},
    }
    (root / 'lenbot.config.json').write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')


def sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def opens(path: Path) -> str | None:
    """None when the file is well-formed for its kind, else why not; checks need no third-party reader."""
    try:
        data = path.read_bytes()
        match path.suffix.lower():
            case '.xlsx':
                with zipfile.ZipFile(path) as archive:
                    if 'xl/workbook.xml' not in archive.namelist():
                        return '缺少 xl/workbook.xml'
                    if archive.read('xl/worksheets/sheet1.xml').count(b'<row ') < 2:
                        return '工作表没有数据行'
            case '.pdf':
                if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:] or b'/Page' not in data:
                    return 'PDF 结构不完整'
            case '.png':
                width, height = struct.unpack('>II', data[16:24])
                if not data.startswith(b'\x89PNG\r\n\x1a\n') or width < 16 or height < 16:
                    return 'PNG 头部或尺寸无效'
            case '.csv':
                if len(list(csv.reader(data.decode('utf-8').splitlines()))) < 2:
                    return 'CSV 没有数据行'
            case _:
                if not data.decode('utf-8').strip():
                    return '文件为空'
    except Exception as error:
        return f'{type(error).__name__}: {error}'
    return None


async def until(condition, seconds: float):
    async with asyncio.timeout(seconds):
        while not (result := condition()):
            await asyncio.sleep(.2)
    return result


async def finish(tasks: WorkTasks, id: int, seconds: float, questions: list[str]) -> dict:
    """Answer what the task asks, until it ends."""
    deadline = time.monotonic() + seconds
    while True:
        state = await until(lambda: tasks.status(SCENE, id)['status'] in {'waiting_input', 'done', 'failed', 'cancelled'}
                            and tasks.status(SCENE, id), max(deadline - time.monotonic(), 1))
        if state['status'] != 'waiting_input':
            return state
        question = state['question']
        questions.append(question['title'])
        if question['method'] == 'confirm':
            await tasks.answer(SCENE, id, requester=OWNER, text=None, confirmed=True, question_id=question['id'])
        else:
            text = question['options'][0] if question['method'] == 'select' else ANSWER
            await tasks.answer(SCENE, id, requester=OWNER, text=text, confirmed=None, question_id=question['id'])
        await until(lambda: tasks.status(SCENE, id)['status'] != 'waiting_input'
                    or tasks.status(SCENE, id)['question']['id'] != question['id'], 60)


def event_summary(store: Store, id: int) -> dict:
    rows = store.db.execute('SELECT kind, body FROM task_events WHERE scene=? AND task_id=? ORDER BY id', (SCENE, id)).fetchall()
    data = Counter(json.loads(body)['name'] for kind, body in rows if kind == 'data_tool')
    return {'kinds': dict(Counter(kind for kind, _ in rows)), 'data_tools': dict(data)}


def record(tasks: WorkTasks, store: Store, id: int, state: dict, started: float, questions: list[str],
           directory: Path, known: set[int]) -> dict:
    """What one run delivered (copied to ``directory``) and what it cost."""
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for file in tasks.records.list_files(SCENE, id):
        if file.id in known:
            continue
        known.add(file.id)
        copy = directory / f'{file.id}-{Path(file.name).name}'
        shutil.copyfile(file.path, copy)
        files.append({'name': file.name, 'size': file.size, 'sha256': sha256(str(copy)), 'path': str(copy),
                      'opens': opens(copy)})
    return {'status': state['status'], 'error': state['error'], 'summary': (state['summary'] or '')[:600],
            'files': files, 'model_calls': state['model_calls'], 'tokens': state['tokens'],
            'seconds': round(time.monotonic() - started, 1), 'questions': questions,
            'events': event_summary(store, id)}


def hosts(text: str) -> set[str]:
    return {urlsplit(url).hostname.removeprefix('www.') for url in re.findall(r'https?://[^\s)\]>"\'<]+', text)}


def check_s1(runs: list[dict]) -> dict:
    reports = [Path(file['path']) for file in runs[0]['files'] if file['name'].lower().endswith('.md')]
    found = hosts(reports[0].read_text(encoding='utf-8')) if reports else set()
    return {'报告 Markdown 已交付': bool(reports), '不同来源站点至少 3 个': len(found) >= 3,
            '来源站点': sorted(found)}


def check_s2(runs: list[dict]) -> dict:
    first, second = runs[0]['files'], runs[1]['files'] if len(runs) > 1 else []
    kinds = lambda files: {Path(file['name']).suffix.lower() for file in files}
    return {'第一次交付 XLSX 和 PNG': {'.xlsx', '.png'} <= kinds(first),
            '第二次交付存在': bool(second),
            '第二次交付与第一次内容不同': bool(second) and {f['sha256'] for f in second}.isdisjoint({f['sha256'] for f in first})}


def check_s3(runs: list[dict]) -> dict:
    files = runs[0]['files']
    sheets = [Path(file['path']) for file in files if file['name'].lower().endswith('.csv')]
    rows = len(list(csv.reader(sheets[0].read_text(encoding='utf-8').splitlines()))) - 1 if sheets else 0
    return {'CSV 已交付且有数据行': rows > 0, 'HTML 或 PDF 报告已交付': any(
        file['name'].lower().endswith(('.html', '.pdf')) for file in files), 'CSV 数据行数': rows}


CHECKS = {'S1': check_s1, 'S2': check_s2, 'S3': check_s3}


async def scenario(label: str, arguments, models: dict, web: dict, network: dict | None, sandbox: dict, root: Path,
                   output: Path, browser_url: str) -> dict:
    mode = 'off' if label == 'S2' else 'public'
    instance = root / label
    write_instance(instance, models, web, network, sandbox, mode)
    config = load_host_config(instance)
    persona = load_persona(config.scenes[SCENE].persona)
    questions: list[str] = []
    runs: list[dict] = []
    known: set[int] = set()
    failure = None
    try:
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as mind:
                tasks = WorkTasks(config, store, None, lambda scene: None, skills={SCENE: select_skills(worker_catalog(config.worker, SCENE), persona.skills)},
                                  memory=None, data_tools={SCENE: task_data_tools(config.scene_config(SCENE), persona,
                                                                                  platform=False, memory=None)},
                                  skill_permissions={SCENE: persona.skills}, tool_permissions={SCENE: persona.tools})
                NetworkRuntime(config, [(config.scene_config(SCENE), persona)], store, mind, tasks=tasks)
                await tasks.recover()
                await tasks.start()
                try:
                    materials = []
                    if label == 'S2':
                        await tasks.upload_resource(SCENE, io.BytesIO(seeded_sales()), requester=OWNER, name='sales.csv')
                        materials = ['sales.csv']
                    goal, deliverable = {
                        'S1': (f'场景 S1：针对问题「{arguments.question}」做公开资料调研，写成 Markdown 报告 report.md。'
                               '每条结论标注来源链接和资料日期，至少引用 3 个不同来源站点。', 'report.md'),
                        'S2': ('场景 S2：分析本群资料 sales.csv：按地区统计销量总和与平均值，画柱状图，'
                               '交付 XLSX 统计表和 PNG 图表。', 'XLSX 统计表、PNG 图表'),
                        'S3': (f'场景 S3：用 lenbot-browser 打开需要 JavaScript 渲染的页面 {browser_url}，抓取前两页内容整理成 '
                               'CSV，并生成 HTML 或 PDF 报告，交付 CSV 和报告。', 'CSV、HTML 或 PDF 报告')}[label]
                    started = time.monotonic()
                    id = (await tasks.delegate(SCENE, requester=OWNER, goal=goal, deliverable=deliverable,
                                               context='端到端验收', materials=materials))['id']
                    state = await finish(tasks, id, arguments.timeout, questions)
                    runs.append(record(tasks, store, id, state, started, questions, output / label / 'run1', known))
                    if label == 'S2' and state['status'] == 'done':
                        started, questions = time.monotonic(), []
                        await tasks.resume(SCENE, id, requester=OWNER, text=FOLLOW_UP)
                        state = await finish(tasks, id, arguments.timeout, questions)
                        runs.append(record(tasks, store, id, state, started, questions, output / label / 'run2', known))
                finally:
                    await tasks.close()
    except Exception as error:
        failure = f'{type(error).__name__}: {error}'
    done = bool(runs) and all(run['status'] == 'done' for run in runs) and (label != 'S2' or len(runs) == 2)
    checks = CHECKS[label](runs) if runs and done else {}
    unopened = {file['name']: file['opens'] for run in runs for file in run['files'] if file['opens']}
    ok = failure is None and done and all(value for key, value in checks.items() if isinstance(value, bool)) and not unopened
    return {'scenario': label, 'egress': mode, 'ok': ok, 'failure': failure, 'runs': runs, 'checks': checks,
            'unopened_files': unopened}


def markdown(report: dict) -> str:
    lines = [f'# 任务端到端验收 {report["finished"]}', '',
             f'- 运行方式：{report["sandbox"]}，模型：{report["model"]}', '']
    for result in report['scenarios']:
        lines += [f'## {result["scenario"]}　{"通过自动检查" if result["ok"] else "未通过"}（出网 {result["egress"]}）', '']
        if result['failure']:
            lines += [f'- 脚本异常：{result["failure"]}']
        for number, run in enumerate(result['runs'], 1):
            usage = run['tokens']
            lines += [f'- 第 {number} 次：状态 {run["status"]}，耗时 {run["seconds"]} 秒，模型调用 {run["model_calls"]} 次，'
                      f'token {json.dumps(usage, ensure_ascii=False)}，提问 {len(run["questions"])} 次',
                      '  - 交付：' + ('、'.join(f'{f["name"]}（{f["size"]} 字节）' for f in run['files']) or '无'),
                      f'  - 事件（含此前各次）：{json.dumps(run["events"], ensure_ascii=False)}']
            if run['error']:
                lines.append(f'  - 失败原因：{run["error"]}')
        for key, value in result['checks'].items():
            lines.append(f'- 检查 {key}：{"通过" if value is True else "未通过" if value is False else value}')
        for name, reason in result['unopened_files'].items():
            lines.append(f'- 无法打开 {name}：{reason}')
        lines.append('')
    return '\n'.join(lines)


async def run(arguments, root: Path, sandbox: dict) -> dict:
    servers = []
    if arguments.scripted:
        model = await serve(lambda path, body: (200, 'text/event-stream', scripted_reply(body, arguments.browser_url)))
        web = await serve(web_service)
        servers = [model, web]
        port, web_port = (server.sockets[0].getsockname()[1] for server in servers)
        models = {'providers': {'scripted': {'api': 'openai-chat', 'base_url': f'http://127.0.0.1:{port}/v1',
                                             'api_key': 'synthetic-unused'},
                                'web': {'api': 'tavily', 'base_url': f'http://127.0.0.1:{web_port}', 'api_key': 'synthetic-unused'}},
                  'roles': {'mind': {'provider': 'scripted', 'model': 'scripted-worker', 'context_window_tokens': 65536}}}
        web_config = {'web_search': {'provider': 'tavily', 'connection': 'web'},
                      'web_read': {'provider': 'tavily', 'connection': 'web'}}
        network, label = None, 'scripted'
    else:
        source = json.loads(arguments.config.read_text(encoding='utf-8'))
        models = source['models']
        web_config = {key: source[key] for key in ('web_search', 'web_read') if key in source}
        network = source.get('network')
        label = models['roles']['mind']['model']
    try:
        results = [await scenario(name, arguments, models, web_config, network, sandbox, root, arguments.output,
                                   arguments.browser_url)
                   for name in arguments.scenarios]
    finally:
        for server in servers:
            server.close()
    return {'finished': time.strftime('%Y-%m-%d %H:%M:%S %z'), 'sandbox': arguments.sandbox, 'model': label,
            'scenarios': results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, help="the reviewer's instance config; its models section is the model connection")
    parser.add_argument('--scripted', action='store_true', help='fixed local model, search and reader; judges no quality')
    parser.add_argument('--sandbox', choices=['docker', 'bwrap'], default='bwrap')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenarios', default='S1,S2', help='comma separated: S1, S2, S3 (S3 needs docker)')
    parser.add_argument('--image', default='lenbot-worker:local')
    parser.add_argument('--docker', default=shutil.which('docker'))
    parser.add_argument('--docker-host', default=os.environ.get('DOCKER_HOST') or 'unix:///var/run/docker.sock')
    parser.add_argument('--bwrap', default=shutil.which('bwrap'))
    parser.add_argument('--task-runtime', type=Path, help='directory built by build_task_runtime.py')
    parser.add_argument('--question', default=DEFAULT_QUESTION, help='the S1 question')
    parser.add_argument('--browser-url', default=DEFAULT_BROWSER_URL, help='the S3 page')
    parser.add_argument('--timeout', type=float, default=900, help='seconds a task may take per run')
    arguments = parser.parse_args()
    arguments.scenarios = [name.strip().upper() for name in arguments.scenarios.split(',') if name.strip()]
    if not arguments.scenarios or not set(arguments.scenarios) <= {'S1', 'S2', 'S3'}:
        sys.exit('--scenarios takes S1, S2 and S3')
    if (arguments.config is None) == (not arguments.scripted):
        sys.exit('pass exactly one of --config and --scripted')
    if 'S3' in arguments.scenarios and arguments.sandbox != 'docker':
        sys.exit('S3 needs the worker image: use --sandbox docker')
    if arguments.sandbox == 'docker':
        if arguments.docker is None:
            sys.exit('docker CLI not found; pass --docker')
        subprocess.run([arguments.docker, '--host', arguments.docker_host, 'image', 'inspect', arguments.image],
                       check=True, capture_output=True)
        sandbox = {'docker_binary': arguments.docker, 'docker_host': arguments.docker_host, 'image': arguments.image,
                   'uid': os.getuid(), 'gid': os.getgid()}
    else:
        if arguments.bwrap is None or arguments.task_runtime is None:
            sys.exit('bwrap mode needs the bwrap binary and --task-runtime')
        sandbox = {'sandbox': 'bwrap', 'bwrap_binary': arguments.bwrap, 'task_runtime': str(arguments.task_runtime.resolve())}
    arguments.output = arguments.output.resolve()
    arguments.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lenbot-e2e-') as directory:
        report = asyncio.run(run(arguments, Path(directory).resolve(), sandbox))
    for result in report['scenarios']:
        for run_record in result['runs']:
            for file in run_record['files']:
                file['path'] = str(Path(file['path']).relative_to(arguments.output))
    (arguments.output / 'e2e-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (arguments.output / 'e2e-report.md').write_text(markdown(report), encoding='utf-8')
    print(markdown(report))
    sys.exit(0 if all(result['ok'] for result in report['scenarios']) else 1)


if __name__ == '__main__':
    main()
