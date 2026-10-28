"""Start a throwaway LenBot instance with made-up groups for the site screenshots and recordings.

A fake OneBot answers account and group queries and replays a few invented group messages; delivery is
simulated. The model is a local script: when the bot is woken it looks through the chat history, then
says two lines, each step after a short delay, so the turn grows on the panel the way a real one does.
Nothing here touches a real QQ account, a real model or a real instance.

    uv run --no-sync python website/scripts/demo_instance.py /tmp/lenbot-demo

While it runs, POST /inject on the control port sends a group message, with "at" to mention the bot:

    curl -H 'Content-Type: application/json' -d '{"group": 80001, "user": 70002, "text": "周六带什么零食好", "at": true}' \
        http://127.0.0.1:18099/inject
"""

import argparse
import asyncio
import itertools
import json
from pathlib import Path
import shutil
import socket
import sys
import time
import urllib.request

from fastapi import FastAPI, Request
import uvicorn
import websockets

ROOT = Path(__file__).resolve().parents[2]
BOT, OWNER = 90001, 70001
GROUPS = {80001: '周末桌游局', 80002: '摄影爱好者', 80003: '读书会'}
MEMBERS = {70001: '阿砚', 70002: '小满', 70003: '老周', 70004: '橘子', 70005: '清和'}
CHATS = [
    (80001, 70002, '这周六还是老地方吗'),
    (80001, 70003, '我带新到的那盒卡坦岛扩展'),
    (80001, 70004, '上次谁把骰子带走了，自首吧'),
    (80001, 70002, '六点开局，晚到的负责点外卖'),
    (80001, 70003, '先说好，我一点辣都不吃，上次那袋辣条我一口没动'),
    (80001, 70004, '零食我要抹茶饼干，别的随意'),
    (80002, 70005, '今天傍晚的火烧云拍到了，可惜手抖'),
    (80002, 70001, '下次带个小三脚架，轻一点的就行'),
    (80002, 70003, '周日去植物园扫街有人吗'),
    (80003, 70004, '这个月读到第三章了，节奏有点慢'),
    (80003, 70005, '第四章开始就好看了，坚持一下'),
]

# Keyword in the newest message: what the bot looks up, its two thoughts and the two lines it says.
SCRIPTS = [
    ('带什么零食', '辣', '小满在问周六带什么零食。大家之前说过口味，先翻一下群里的记录。',
     '老周说过一点辣都不吃，橘子点名要抹茶饼干，那就带不辣的，再加一盒抹茶饼干。',
     ['我带薯片和果干吧，老周不吃辣，辣条就不拿啦', '橘子要的抹茶饼干我也带一盒']),
    ('三脚架', '三脚架', '有人问三脚架怎么选，群里之前讨论过器材，先找找。',
     '清和之前说过要轻一点的，碳纤维的小三脚架就够用。',
     ['扫街的话买个一公斤以内的碳纤维小三脚架就够了', '要拍火烧云再加个快门线，手就不会抖啦']),
]
# Group files of 80001 for the reference tab: (folder, file_id, name, uploader, text or None for a photo).
GROUP_FILES = [
    (None, '/f-rules', '桌游规则速查.md', 70003,
     '# 桌游规则速查\n\n## 卡坦岛\n\n先到 10 分获胜。强盗出现时手牌超过 7 张要弃掉一半。\n\n'
     '## 璀璨宝石\n\n每回合拿 3 枚不同颜色或 2 枚同色宝石，手里最多 10 枚。\n'),
    (None, '/f-venue', '场地预约.txt', 70002, '周六 18:00 到 23:00，东门桌游吧 3 号包间，押金 100 元已交。\n'),
    (None, '/f-photo', '上周合影.jpg', 70004, None),
    ('/d-books', '/f-expansion', '卡坦岛航海家扩展.md', 70003,
     '# 航海家扩展\n\n## 胜利条件\n\n航海家扩展先到 13 分获胜。\n'),
]
FALLBACK = ('', None, '有人叫我，先看看群里刚才在聊什么。', '大概明白了，接一句。',
            ['我在呢～刚才在看你们聊', '有事随时叫我'])


def scripted_model(delay: float) -> FastAPI:
    """An OpenAI-compatible endpoint that answers the bot's turns with a fixed three-step script."""
    app = FastAPI()

    @app.post('/v1/chat/completions')
    async def complete(request: Request):
        body = await request.json()
        await asyncio.sleep(delay)
        names = {tool['function']['name'] for tool in body.get('tools', [])}
        if 'say' not in names:
            # Memory filing, compaction and titles: plain text is enough.
            return {'choices': [{'message': {'role': 'assistant', 'content': '整理好了'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 900, 'completion_tokens': 30}}
        messages = list(body['messages'])
        # The host state comes last as a user message; the chat that woke the bot is the user message before the steps.
        if messages[-1]['role'] == 'user' and messages[-2]['role'] != 'system':
            messages.pop()
        last = max(index for index, message in enumerate(messages) if message['role'] == 'user')
        text = json.dumps(messages[last].get('content'), ensure_ascii=False)
        steps = sum(message['role'] == 'tool' for message in messages[last:])
        # The newest message decides; the replayed chat comes before it.
        keyword, query, before, after, lines = max(SCRIPTS + [FALLBACK], key=lambda item: text.rfind(item[0]) if item[0] else 0)
        recall = 'recall_chat' in names
        if steps == 0 and recall:
            name, thought, arguments = 'recall_chat', before, {'action': 'search', 'query': query} if query else {'action': 'recent'}
        else:
            line = min(steps - recall, 1)
            name, thought, arguments = 'say', after if line == 0 else '再补一句就收尾。', {
                'content': lines[line], 'end_turn': line == 1}
        call = {'id': f'call_{time.time_ns()}', 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}
        return {'choices': [{'message': {'role': 'assistant', 'content': None, 'reasoning_content': thought,
                                         'tool_calls': [call]}, 'finish_reason': 'tool_calls'}],
                'usage': {'prompt_tokens': 4200 + 300 * steps, 'completion_tokens': 80,
                          'prompt_tokens_details': {'cached_tokens': 3600}}}

    return app


def message_event(group: int, user: int, text: str, message_id: int, *, at: bool = False) -> str:
    segments = ([{'type': 'at', 'data': {'qq': str(BOT)}}] if at else []) + [{'type': 'text', 'data': {'text': text}}]
    return json.dumps({
        'post_type': 'message', 'message_type': 'group', 'sub_type': 'normal', 'time': int(time.time()),
        'self_id': BOT, 'group_id': group, 'user_id': user, 'message_id': message_id,
        'message': segments, 'raw_message': text, 'font': 0,
        'sender': {'user_id': user, 'nickname': MEMBERS.get(user, '群友'), 'card': '', 'role': 'member'}})


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


COUNTER = itertools.count(1000)


def group_files(folder: str | None) -> dict:
    files = [{'group_id': 80001, 'file_id': file_id, 'file_name': name, 'busid': 102,
              'file_size': len(text.encode()) if text else 812_000, 'upload_time': int(time.time()) - 86400 * index,
              'uploader': user, 'uploader_name': MEMBERS[user]}
             for index, (inside, file_id, name, user, text) in enumerate(GROUP_FILES) if inside == folder]
    folders = [] if folder else [{'group_id': 80001, 'folder_id': '/d-books', 'folder_name': '规则书',
                                  'total_file_count': 1}]
    return {'files': files, 'folders': folders}


async def onebot(port: int, ready: asyncio.Event, connections: set | None = None, files_url: str = '') -> None:
    """Answer the queries LenBot makes and push the invented messages once it is connected."""
    counter = COUNTER
    connections = set() if connections is None else connections

    def answer(action: str, params: dict):
        if action == 'get_login_info':
            return {'user_id': BOT, 'nickname': '小然'}
        if action in ('get_group_info', 'get_group_detail_info'):
            return {'group_id': params['group_id'], 'group_name': GROUPS.get(params['group_id'], '群'), 'member_count': 42}
        if action == 'get_group_list':
            return [{'group_id': group, 'group_name': name, 'member_count': 42} for group, name in GROUPS.items()]
        if action in ('get_group_member_info', 'get_stranger_info'):
            user = params['user_id']
            return {'user_id': user, 'nickname': MEMBERS.get(user, '群友'), 'card': '', 'role': 'member'}
        if action.startswith('send_'):
            return {'message_id': next(counter)}
        if action in ('get_group_root_files', 'get_group_files_by_folder'):
            return group_files(params.get('folder_id') if params['group_id'] == 80001 else '/none')
        if action == 'get_group_file_url':
            return {'url': files_url + params['file_id']}
        return {}

    async def handle(connection):
        async def replay():
            await asyncio.sleep(3)
            for group, user, text in CHATS:
                await connection.send(message_event(group, user, text, next(counter)))
                await asyncio.sleep(0.4)
            ready.set()
        task = asyncio.create_task(replay())
        connections.add(connection)
        try:
            async for raw in connection:
                request = json.loads(raw)
                await connection.send(json.dumps({'status': 'ok', 'retcode': 0, 'echo': request.get('echo'),
                                                  'data': answer(request['action'], request.get('params') or {})}))
        finally:
            connections.discard(connection)
            task.cancel()

    async with websockets.serve(handle, '127.0.0.1', port):
        await asyncio.Future()


def post(url: str, body: dict, headers: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', **headers})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('root', type=Path, help='New directory for the throwaway instance')
    parser.add_argument('--panel-port', type=int, default=18088)
    parser.add_argument('--control-port', type=int, default=18099, help='Scripted model and /inject')
    parser.add_argument('--model-delay', type=float, default=1.5, help='Seconds each scripted model step takes')
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True)
    onebot_port = free_port()
    ready = asyncio.Event()
    connections: set = set()
    server = asyncio.create_task(onebot(onebot_port, ready, connections,
                                        f'http://127.0.0.1:{args.control_port}/files'))
    control = scripted_model(args.model_delay)

    @control.get('/files/{file_id}')
    async def group_file(file_id: str):
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(next(text for _, known, _, _, text in GROUP_FILES if known == '/' + file_id))

    @control.post('/inject')
    async def inject(body: dict):
        event = message_event(body.get('group', 80001), body.get('user', 70002), body['text'], next(COUNTER),
                              at=body.get('at', False))
        for connection in list(connections):
            await connection.send(event)
        return {'sent': len(connections)}

    controller = uvicorn.Server(uvicorn.Config(control, host='127.0.0.1', port=args.control_port, log_level='warning'))
    controlling = asyncio.create_task(controller.serve())
    command = [sys.executable, '-c', 'from len_bot import main; main()']
    process = None
    draining = None
    waiting = None
    ready_task = None
    async def drain(child):
        while line := await child.stdout.readline():
            print(line.decode('utf-8', 'replace'), end='', flush=True)
    try:
        process = await asyncio.create_subprocess_exec(*command, cwd=root, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.STDOUT)
        async with asyncio.timeout(60):
            while True:
                line = (await process.stdout.readline()).decode('utf-8', 'replace')
                if '#token=' in line:
                    break
                if not line:
                    raise RuntimeError(f'len-bot exited before setup with {await process.wait()}')
        draining = asyncio.create_task(drain(process))
        setup = line[line.index('http://'):].split()[0]
        base, token = setup.split('/#token=')
        await asyncio.to_thread(post, base + '/api/setup', {
            'bot_id': f'onebot:{BOT}', 'owners': [f'onebot:{OWNER}'], 'timezone': 'Asia/Shanghai', 'delivery': 'simulated',
            'onebot': {'mode': 'forward_ws', 'ws_url': f'ws://127.0.0.1:{onebot_port}', 'access_token': 'demo'},
            'provider': {'api': 'openai-chat', 'base_url': f'http://127.0.0.1:{args.control_port}/v1', 'api_key': 'demo'},
            'mind': {'provider': 'primary', 'model': 'demo-chat', 'context_window_tokens': 128000},
            'compaction': {'input_tokens': 96000}, 'scene': 'onebot:group:80001', 'persona_id': 'companion',
            'persona_name': '小然', 'brief': '演示角色', 'voice_text': '简短', 'boundaries': '',
            'panel_port': args.panel_port, 'username': 'demo', 'password': 'demo-password'}, {'X-Setup-Token': token})
        process.terminate()
        async with asyncio.timeout(60):
            await process.wait()
            await draining
        draining = None
        shutil.rmtree(root / 'personas/companion')
        shutil.copytree(ROOT / 'examples/personas/companion', root / 'personas/companion')
        config = json.loads((root / 'lenbot.config.json').read_text())
        first = config['scenes']['onebot:group:80001']
        for group in GROUPS:
            config['scenes'][f'onebot:group:{group}'] = {**first, 'attention': {**first.get('attention', {}), 'only_direct': True}}
        (root / 'lenbot.config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
        process = await asyncio.create_subprocess_exec(*command, cwd=root)
        waiting = asyncio.create_task(process.wait())
        ready_task = asyncio.create_task(ready.wait())
        async with asyncio.timeout(60):
            done, _ = await asyncio.wait((waiting, ready_task), return_when=asyncio.FIRST_COMPLETED)
            if waiting in done:
                raise RuntimeError(f'len-bot exited before becoming ready: {waiting.result()}')
        print(f'演示面板：http://127.0.0.1:{args.panel_port}  用户 demo / demo-password；'
              f'发消息：POST http://127.0.0.1:{args.control_port}/inject；Ctrl-C 结束', flush=True)
        await waiting
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                async with asyncio.timeout(60):
                    await process.wait()
            except TimeoutError:
                process.kill()
                await process.wait()
        controller.should_exit = True
        for task in (draining, waiting, ready_task, server):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in (draining, waiting, ready_task, server, controlling) if task is not None),
                             return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
