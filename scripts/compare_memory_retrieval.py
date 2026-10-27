"""Compare local recall on a small synthetic corpus.

    uv run --no-sync python scripts/compare_memory_retrieval.py [--instance DIR] [--answer]

Run the same script with each checkout on PYTHONPATH. JSON includes the recalled text, evidence
coverage, character count and latency. ``--instance`` reads that instance's ``lenbot.config.json`` and
adds the same cases with vectors through ``memory.local.embedding``; ``--answer`` also asks each case in
its own simulated group with the instance's ``mind`` model and records the reply, the wait for the first
reply and the tokens used. Vectors and answers are paid requests.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from len_bot.next.memory.jobs import MemoryJobs
from len_bot.next.memory.embeddings import EmbeddingClient, EmbeddingSettings
from len_bot.next.memory.local import LocalMemory, LocalMemorySettings
from len_bot.next.memory.service import LocalMemoryConfig, MemoryService, recall_cues
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store


SCENE = 'onebot:group:80001'
DOCUMENTS = {
    'events/week.md': (
        '# 本周安排\n\n## 读书会\n'
        + '读书会先读完上一章，再交流各自标记的段落。' * 18
        + '\n读书会最终地点是图书馆二楼，时间为周六下午三点。\n\n'
        '## 出游\n出游集合点是南门，周日上午九点出发。\n'
    ),
    'people/accounts.md': (
        '# 同名群友\n\n## 小林 onebot:70001\n'
        '小林 onebot:70001 的饮料偏好是无糖豆浆。\n\n'
        '## 小林 onebot:70002\n小林 onebot:70002 的饮料偏好是热红茶。\n'
    ),
    'events/report.md': (
        '# 报告\n\n## 当前约定\n'
        + '报告原定周五提交。大家讨论了排版、附录和数据来源。' * 14
        + '\n报告最新更正为周六中午提交，覆盖之前的周五约定。\n'
    ),
    'topics/strasse.md': '# Straße\n\nStraße 的集合地址是东侧咖啡店。\n',
    'events/trip.md': (
        '# 秋游\n\n## 安排\n'
        + '秋游路线先走山脚步道，中途在茶亭休息，大家轮流分享路上拍的照片。' * 80
        + '\n秋游集合时间最新改为周日早上七点半，原来的八点作废。\n'
    ),
    'events/potluck.md': '# 聚餐\n\n聚餐由阿杰订位，秋游结束后在山脚的农家菜馆。\n',
    'events/booklist.md': '# 十一月书单\n\n十一月书单定了《小王子》和《夜航西飞》，小林负责借书。\n',
}
# The recap of an earlier conversation: what the bot promised, which the recent chat no longer names.
RECAP = '## 话题脉络\n- 读书会选书\n\n## 我答应的事\n- 周五前把十一月书单发到群里（小林问的）\n\n## 没回答的问题\n'
CASES = [
    ('long-section', ['读书会最终地点和时间是什么？'], ['图书馆二楼', '周六下午三点']),
    ('latest-correction', ['报告最新什么时候交？'], ['最新更正为周六中午提交']),
    ('same-name-first', ['onebot:70001 的饮料偏好'], ['无糖豆浆']),
    ('same-name-second', ['onebot:70002 的饮料偏好'], ['热红茶']),
    ('follow-up', ['读书会的安排', '接着说地点和时间'], ['图书馆二楼']),
    ('case-fold', ['STRASSE 集合地址'], ['东侧咖啡店']),
    ('no-evidence', ['火星飞船什么时候起飞？'], []),
    ('correction-past-budget', ['秋游集合时间最新是几点？'], ['周日早上七点半']),
    ('second-source', ['秋游集合时间最新是几点', '聚餐由谁订位'], ['周日早上七点半', '阿杰订位']),
    ('forgotten', ['南门出游集合'], []),
    ('promise-cue', ['那个弄好了没', '周五了哦'], ['《小王子》和《夜航西飞》'], RECAP),
    ('paraphrase', ['看书那个小组最后定在哪儿碰头？'], ['图书馆二楼']),
]
# What a correct reply says; None means the corpus has no answer and the reply should say it does not know.
ANSWERS = {
    'long-section': [r'图书馆(二|2)楼', r'(三|3)点'],
    'latest-correction': [r'周六中午'],
    'same-name-first': [r'无糖豆浆'],
    'same-name-second': [r'热红茶'],
    'follow-up': [r'图书馆(二|2)楼'],
    'case-fold': [r'东侧咖啡店'],
    'no-evidence': None,
    'correction-past-budget': [r'(七|7)点半|7[:：]30'],
    'second-source': [r'(七|7)点半|7[:：]30', r'阿杰'],
    'forgotten': None,
    'promise-cue': [r'小王子', r'夜航西飞'],
    'paraphrase': [r'图书馆(二|2)楼'],
}
UNKNOWN = r'不知道|不清楚|不记得|没(有)?(印象|记录|听说|看到|找到|查到)|没说过|不太确定'


def config(root: Path, binding=None) -> LocalMemoryConfig:
    return LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=root / 'memory', embedding=binding),
                             recall_limit=5, recall_budget_chars=1500)


async def corpus(backend: LocalMemory, scene: str) -> None:
    for path, content in DOCUMENTS.items():
        await backend.write(scene, path, content, '人工可核对的合成对照样本')


def chat(texts: list[str]):
    return [parse_message({
        'post_type': 'message', 'message_type': 'group', 'group_id': 80001,
        'user_id': 90001, 'self_id': 80000, 'message_id': index, 'time': 1791060000,
        'sender': {'nickname': '提问者', 'role': 'member'},
        'message': [{'type': 'text', 'data': {'text': text}}]}, own_message_ids=set())
        for index, text in enumerate(texts, 1)]


async def compare(client: EmbeddingClient | None = None, binding=None) -> list[dict]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        settings = config(root, binding)
        backend = LocalMemory(settings.local, embedding=client)
        await corpus(backend, SCENE)
        await backend.write('onebot:group:80002', 'secret.md', '本群独有暗号海蓝石，读书会。', '隔离样本')
        await backend.write(SCENE, 'bot/other/profile.md', '其他角色独有暗号紫云石，读书会。', '角色隔离样本')
        rows = []
        with Store(root / 'chat.db') as store, MemoryJobs(root / 'jobs.db') as jobs:
            service = MemoryService(settings, backend, jobs=jobs, store=store, active_personas={SCENE: 'current'})
            for name, texts, expected, *recap in CASES:
                if name == 'forgotten':
                    await backend.forget(SCENE, 'events/week.md')
                if name == 'promise-cue':
                    await backend.write(SCENE, 'events/week.md', DOCUMENTS['events/week.md'], '恢复样本')
                started = time.perf_counter()
                result = await service.recall(SCENE, chat(texts), recall_cues(recap[0] if recap else None))
                elapsed = (time.perf_counter() - started) * 1000
                content = '\n'.join(item['content'] for item in result['items'])
                rows.append({'case': name, 'query': texts, 'expected_evidence': expected,
                             'covered': [part for part in expected if part in content],
                             'chars': result['content_chars'], 'elapsed_ms': round(elapsed, 3),
                             'excluded_scope_leaked': any(word in content for word in ['海蓝石', '紫云石']),
                             'items': result['items']})
        return rows


def group_event(group: int, ident: int, text: str, bot: str, *, at: bool) -> dict:
    return {'post_type': 'message', 'message_type': 'group', 'self_id': int(bot), 'group_id': group,
            'user_id': 70001, 'message_id': ident, 'time': int(time.time()),
            'sender': {'nickname': '群友阿青', 'card': '阿青', 'role': 'member'},
            'message': ([{'type': 'at', 'data': {'qq': bot}}] if at else [])
            + [{'type': 'text', 'data': {'text': (' ' if at else '') + text}}]}


async def answers(host, client: EmbeddingClient | None, binding) -> list[dict]:
    """Each case in its own group holding the corpus, so earlier replies do not answer later cases."""
    from len_bot.next.chat.attention import SceneRunner
    from len_bot.next.chat.session import Chat
    from len_bot.next.models.client import ChatModel
    from len_bot.next.persona.profile import load_persona

    rows = []
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        package = root / 'persona'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/personas/companion', package)
        persona = load_persona(package)
        settings = config(root, binding)
        base = host.scene_config(next(iter(host.scenes)))
        bot = host.bot_id.split(':', 1)[1]
        backend = LocalMemory(settings.local, embedding=client)
        with Store(root / 'state.db') as store, MemoryJobs(root / 'jobs.db') as jobs:
            groups = {name: 80101 + index for index, (name, *_) in enumerate(CASES)}
            service = MemoryService(settings, backend, jobs=jobs, store=store,
                                    active_personas={f'onebot:group:{group}': persona.id for group in groups.values()})
            async with AsyncExitStack() as stack:
                mind = await stack.enter_async_context(ChatModel(host.model_settings('mind')))
                vision = (await stack.enter_async_context(ChatModel(host.model_settings('vision')))
                          if host.models.roles.vision is not None else None)
                done: asyncio.Queue = asyncio.Queue()
                for ident, (name, texts, _, *recap) in enumerate(CASES, 1001):
                    group = groups[name]
                    scene = f'onebot:group:{group}'
                    await corpus(backend, scene)
                    if name == 'forgotten':
                        await backend.forget(scene, 'events/week.md')
                    if recap:
                        with store.db:
                            store.db.execute('INSERT INTO mind_sessions(scene,recap) VALUES(?,?) ON CONFLICT(scene) '
                                             'DO UPDATE SET recap=excluded.recap', (scene, recap[0]))
                    scene_config = base.model_copy(update={
                        'scene': scene, 'delivery': 'simulated', 'memory': settings, 'worker': None,
                        'learning': None, 'memory_plugin': None, 'recap_plugin': None})
                    object.__setattr__(scene_config, '_source_root', root)
                    runner = SceneRunner(Chat(scene_config, persona, store, mind, vision=vision, memory=service),
                                         lambda result: done.put_nowait(result))
                    task = asyncio.create_task(runner.run())
                    before = store.db.execute('SELECT coalesce(sum(input), 0), coalesce(sum(output), 0), count(*) '
                                              "FROM usage WHERE purpose='mind'").fetchone()
                    last = store.db.execute('SELECT coalesce(max(seq), 0) FROM messages').fetchone()[0]
                    started = time.time()
                    for position, text in enumerate(texts):
                        runner.receive(group_event(group, ident * 10 + position, text, bot,
                                                   at=position == len(texts) - 1))
                    await asyncio.wait_for(done.get(), 300)
                    runner.close_input()
                    await asyncio.gather(task, return_exceptions=True)
                    said = [json.loads(row[0]) for row in store.db.execute(
                        "SELECT body FROM messages WHERE scene=? AND seq>? AND json_extract(body, '$.is_self') ORDER BY seq",
                        (scene, last))]
                    reply = ' '.join(segment['data']['text'] for message in said for segment in message['segments']
                                     if segment['type'] == 'text')
                    wait = store.db.execute('SELECT first_expression_at - wake_received_at FROM turns'
                                            ' WHERE scene=? AND started>=? ORDER BY started LIMIT 1',
                                            (scene, started)).fetchone()
                    after = store.db.execute('SELECT coalesce(sum(input), 0), coalesce(sum(output), 0), count(*) '
                                             "FROM usage WHERE purpose='mind'").fetchone()
                    expected = ANSWERS[name]
                    rows.append({'case': name, 'reply': reply,
                                 'correct': (re.search(UNKNOWN, reply) is not None if expected is None
                                             else all(re.search(pattern, reply) for pattern in expected)),
                                 'first_reply_seconds': None if wait is None or wait[0] is None else round(wait[0], 1),
                                 'requests': after[2] - before[2],
                                 'input_tokens': after[0] - before[0], 'output_tokens': after[1] - before[1]})
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance', type=Path)
    parser.add_argument('--answer', action='store_true')
    options = parser.parse_args()
    result = {'budget_chars': 1500, 'text': await compare()}
    if options.instance is not None:
        from len_bot.next.config import load_host_config

        host = load_host_config(options.instance.resolve())
        binding = None if host.memory is None else host.memory.local.embedding
        async with AsyncExitStack() as stack:
            client = None
            if binding is not None:
                provider = host.models.providers[binding.provider]
                client = await stack.enter_async_context(EmbeddingClient(EmbeddingSettings(
                    **binding.model_dump(), base_url=provider.base_url, api_key=provider.api_key, proxy=provider.proxy)))
                result['hybrid'] = await compare(client, binding)
            if options.answer:
                result['answer'] = await answers(host, client, binding)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
