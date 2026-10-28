"""Break down the wait from the message that wakes a turn to the bot's first message.

    uv run --no-sync python scripts/first_reply_latency.py report state/lenbot.sqlite3 [--hours 24]
    uv run --no-sync python scripts/first_reply_latency.py run --instance DIR [--rounds 3] [--quick low]
        [--parallel] [--slots N]

``report`` reads the turns of an instance database. ``run`` asks a fixed set of questions with the
instance's ``mind`` model in simulated groups, a new group each round, and reports those turns with the
recall and tool times from the turn trace. ``--quick`` sets the effort of the first request of each turn
(``quick_reasoning_effort``); an empty value uses ``reasoning_effort``. The groups share one set of model
request slots, ``max_model_requests`` of the instance or ``--slots``; ``--parallel`` runs every round's group
at the same time, and each turn records how long its requests waited for a slot (``slot_wait``, part of
``before_model`` and ``between``).
Segments, in seconds:

- batch: from the waking message to the turn start (waiting for the speaker to finish, or for an earlier turn)
- before_model: from the turn start to the first model request (recall, expression selection, context, request slot)
- model: the model requests before the first message, retries included
- between: the time between those requests (tools and context)
- send: from the end of the last of those requests to the first message being sent

Turns with a retried request are summarized apart from the others.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import json
from pathlib import Path
import shutil
import sqlite3
from statistics import median
import tempfile
import time

SEGMENTS = ('batch', 'before_model', 'model', 'between', 'send')
HISTORY = [
    (70002, '小满', '这周六还是老地方吗'),
    (70003, '老周', '对，六点开局，晚到的负责点外卖'),
    (70004, '橘子', '我带新到的那盒卡坦岛扩展'),
]
QUESTIONS = [
    ('chitchat', '早呀，今天降温好冷'),
    ('recent', '周六几点开局来着？'),
    ('memory', '读书会最后定在哪儿？'),
    ('reference', '登山报名截止是什么时候？'),
    ('reference-again', '那登山那天几点集合？'),
]
MEMORY = {'events/week.md': '# 本周安排\n\n## 读书会\n读书会最终地点是图书馆二楼，时间为周六下午三点。\n'}
HANDBOOK = (
    '# 秋季登山活动手册\n\n## 报名\n\n报名截止时间是十一月三日晚上八点，在群公告的表格里填写姓名。\n\n'
    '## 集合\n\n十一月八日周六早上八点半在学校东门集合，八点四十五分准时发车。\n\n'
    '## 装备\n\n必带登山鞋、雨衣、头灯和两升饮用水。\n'
)


def breakdown(db: sqlite3.Connection, since: float, turn_ids: set[str] | None = None) -> list[dict]:
    rows = []
    for turn in db.execute('SELECT id,scene,started,wake_received_at,first_expression_at,first_expression_delivery,'
                           'wake_channel FROM turns WHERE first_expression_at IS NOT NULL AND started>=? '
                           'ORDER BY started', (since,)):
        if turn_ids is not None and turn['id'] not in turn_ids:
            continue
        first = turn['first_expression_at']
        calls = db.execute('SELECT role,started,ended,retries,tokens FROM model_calls WHERE turn_id=? AND started<? '
                           'ORDER BY id', (turn['id'], first)).fetchall()
        if not calls or any(call['ended'] is None for call in calls):
            continue
        wake = turn['started'] if turn['wake_received_at'] is None else turn['wake_received_at']
        rows.append({
            'turn_id': turn['id'], 'scene': turn['scene'], 'channel': turn['wake_channel'],
            'delivery': turn['first_expression_delivery'], 'total': first - wake,
            'batch': turn['started'] - wake,
            'before_model': calls[0]['started'] - turn['started'],
            'model': sum(call['ended'] - call['started'] for call in calls),
            'between': sum(later['started'] - earlier['ended'] for earlier, later in zip(calls, calls[1:])),
            'send': first - calls[-1]['ended'],
            'requests': len(calls), 'retries': sum(call['retries'] for call in calls),
            'roles': [call['role'] for call in calls],
            # Per request: seconds, input, cached input and output tokens.
            'calls': [[round(call['ended'] - call['started'], 2),
                       *(None if call['tokens'] is None else
                         [json.loads(call['tokens'])[key] for key in ('input', 'cached', 'output')])]
                      for call in calls],
        })
    return rows


def middle(rows: list[dict], key: str) -> float:
    return round(median(row[key] for row in rows), 2)


def summary(rows: list[dict]) -> dict:
    result = {}
    for name, picked in (('first_try', [row for row in rows if not row['retries']]),
                         ('retried', [row for row in rows if row['retries']])):
        if not picked:
            continue
        counts = sorted({row['requests'] for row in picked})
        result[name] = {
            'turns': len(picked), **{key: middle(picked, key) for key in ('total', *SEGMENTS)},
            'by_requests': {count: {'turns': len(same), 'total': middle(same, 'total')}
                            for count in counts for same in [[row for row in picked if row['requests'] == count]]},
        }
    return result


def rounded(row: dict) -> dict:
    return {key: round(value, 2) if isinstance(value, float) else value for key, value in row.items()}


def traced(row: dict, events: list[tuple[float, dict]], first: float) -> None:
    """Add recall and tool times; a tool still running at the first message is the one sending it."""
    opened: dict[tuple[str, str | None], tuple[float, dict]] = {}
    recall, tools = 0.0, []
    for stamp, event in events:
        if event['type'] != 'turn.step' or event.get('kind') not in {'recall', 'tool'}:
            continue
        key = (event['kind'], event.get('call_id'))
        if event['phase'] == 'start':
            opened[key] = stamp, event
        elif key in opened and stamp <= first:
            began, start = opened.pop(key)
            if event['kind'] == 'recall':
                recall += stamp - began
            else:
                tools.append({'name': event['name'], 'seconds': round(stamp - began, 2),
                              'arguments': start['arguments_summary'][:120]})
    row['recall'] = recall
    row['tools'] = tools


class TimedSlots:
    """Model request slots that record, per scene, when each request got one and how long it waited."""

    def __init__(self, limit: int):
        from len_bot.next.models.slots import ModelSlots

        self.inner = ModelSlots(limit)
        self.limit = limit
        self.admit = None
        self.waits: list[tuple[str | None, float, float]] = []

    @asynccontextmanager
    async def slot(self, *, direct: bool = False, scene: str | None = None):
        asked = time.time()
        async with self.inner.slot(direct=direct, scene=scene):
            granted = time.time()
            self.waits.append((scene, granted, granted - asked))
            yield


def spread(values: list[float]) -> dict:
    ordered = sorted(values)
    return {'median': round(median(ordered), 2), 'p90': round(ordered[int(0.9 * (len(ordered) - 1))], 2),
            'max': round(ordered[-1], 2)} if ordered else {}


def group_event(group: int, ident: int, user: int, name: str, text: str, bot: str, *, at: bool) -> dict:
    return {'post_type': 'message', 'message_type': 'group', 'self_id': int(bot), 'group_id': group,
            'user_id': user, 'message_id': ident, 'time': int(time.time()),
            'sender': {'nickname': name, 'card': name, 'role': 'member'},
            'message': ([{'type': 'at', 'data': {'qq': bot}}] if at else [])
            + [{'type': 'text', 'data': {'text': (' ' if at else '') + text}}]}


async def run(instance: Path, rounds: int, quick: str | None, *, parallel: bool = False,
              limit: int | None = None) -> dict:
    from len_bot.next.chat.attention import SceneRunner
    from len_bot.next.chat.session import Chat
    from len_bot.next.config import load_host_config
    from len_bot.next.memory.embeddings import EmbeddingClient, EmbeddingSettings
    from len_bot.next.memory.jobs import MemoryJobs
    from len_bot.next.memory.local import LocalMemory, LocalMemorySettings
    from len_bot.next.memory.service import LocalMemoryConfig, MemoryService
    from len_bot.next.models.client import ChatModel
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.reference.library import ReferenceLibrary, reference_embedding
    from len_bot.next.storage.store import Store

    host = load_host_config(instance.resolve())
    base = host.scene_config(next(iter(host.scenes)))
    if quick is not None:
        roles = base.models.roles.model_copy(update={'mind': base.models.roles.mind.model_copy(
            update={'quick_reasoning_effort': quick or None})})
        base = base.model_copy(update={'models': base.models.model_copy(update={'roles': roles})})
    bot = host.bot_id.split(':', 1)[1]
    binding = None if host.memory is None else host.memory.local.embedding
    rows, traces, replies = [], {}, {}
    slots = TimedSlots(limit or host.max_model_requests)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/personas/companion', root / 'persona')
        persona = load_persona(root / 'persona')
        settings = LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=root / 'memory', embedding=binding))
        scenes = [f'onebot:group:{80201 + index}' for index in range(rounds)]
        with Store(root / 'state.db') as store, MemoryJobs(root / 'jobs.db') as jobs:
            async with AsyncExitStack() as stack:
                client = None
                if binding is not None:
                    provider = host.models.providers[binding.provider]
                    client = await stack.enter_async_context(EmbeddingClient(EmbeddingSettings(
                        **binding.model_dump(), base_url=provider.base_url, api_key=provider.api_key,
                        proxy=provider.proxy)))
                backend = LocalMemory(settings.local, embedding=client)
                service = MemoryService(settings, backend, jobs=jobs, store=store,
                                        active_personas={scene: persona.id for scene in scenes})
                library = ReferenceLibrary(root, embedding=None if client is None
                                           else reference_embedding(client, store, None))
                mind = await stack.enter_async_context(ChatModel(host.model_settings('mind')))
                vision = (await stack.enter_async_context(ChatModel(host.model_settings('vision')))
                          if host.models.roles.vision is not None else None)

                async def ask(index: int, scene: str) -> None:
                    group = int(scene.rsplit(':', 1)[1])
                    for path, content in MEMORY.items():
                        await backend.write(scene, path, content, '首句延迟拆解的合成样本')
                    directory = library.directory(scene)
                    directory.mkdir(parents=True)
                    (directory / '秋季登山活动手册.md').write_text(HANDBOOK, encoding='utf-8')
                    config = base.model_copy(update={
                        'scene': scene, 'delivery': 'simulated', 'memory': settings, 'worker': None,
                        'learning': None, 'memory_plugin': None, 'recap_plugin': None,
                        'attention': base.attention.model_copy(update={'only_direct': True})})
                    object.__setattr__(config, '_source_root', root)
                    done: asyncio.Queue = asyncio.Queue()
                    chat = Chat(config, persona, store, mind, vision=vision, memory=service, reference=library,
                                slots=slots,
                                on_trace=lambda event: traces.setdefault(event['turn_id'], []).append((time.time(), event)))
                    runner = SceneRunner(chat, done.put_nowait)
                    task = asyncio.create_task(runner.run())
                    ident = (index + 1) * 100
                    for user, name, text in HISTORY:
                        ident += 1
                        runner.receive(group_event(group, ident, user, name, text, bot, at=False))
                    for case, text in QUESTIONS:
                        ident += 1
                        last = store.db.execute('SELECT coalesce(max(seq), 0) FROM messages').fetchone()[0]
                        runner.receive(group_event(group, ident, 70001, '阿砚', text, bot, at=True))
                        result = await asyncio.wait_for(done.get(), 300)
                        said = [json.loads(row[0]) for row in store.db.execute(
                            "SELECT body FROM messages WHERE scene=? AND seq>? AND json_extract(body,'$.is_self') "
                            'ORDER BY seq', (scene, last))]
                        replies[result['turn_id']] = (index + 1, case, ' '.join(
                            segment['data']['text'] for message in said for segment in message['segments']
                            if segment['type'] == 'text'))
                        await asyncio.sleep(1)
                    runner.close_input()
                    await asyncio.gather(task, return_exceptions=True)
                started = time.time()
                if parallel:
                    await asyncio.gather(*(ask(index, scene) for index, scene in enumerate(scenes)))
                else:
                    for index, scene in enumerate(scenes):
                        await ask(index, scene)
                for row in breakdown(store.db, started, set(replies)):
                    began, first = store.db.execute('SELECT started, first_expression_at FROM turns WHERE id=?',
                                                    (row['turn_id'],)).fetchone()
                    traced(row, traces.get(row['turn_id'], []), first)
                    row['slot_wait'] = sum(wait for scene, granted, wait in slots.waits
                                           if scene == row['scene'] and began <= granted <= first)
                    row['round'], row['case'], row['reply'] = replies[row['turn_id']]
                    rows.append(row)
    cases = {case: {'turns': len(same), 'total': middle(same, 'total'), 'requests': [row['requests'] for row in same]}
             for case, _ in QUESTIONS for same in [[row for row in rows if row['case'] == case]] if same}
    mind = base.models.roles.mind
    waits = [wait for _, _, wait in slots.waits]
    return {'model': mind.model, 'effort': mind.reasoning_effort, 'quick_effort': mind.quick_reasoning_effort,
            'groups': rounds, 'parallel': parallel, 'slots': slots.limit,
            'slot_wait': {'requests': len(waits), 'waited': sum(wait > 0.05 for wait in waits), **spread(waits),
                          'turns': spread([row['slot_wait'] for row in rows])},
            'summary': summary(rows), 'cases': cases,
            'turns': [rounded(row) for row in rows], 'unanswered': len(replies) - len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    report = commands.add_parser('report')
    report.add_argument('database', type=Path)
    report.add_argument('--hours', type=float, default=24.0)
    measure = commands.add_parser('run')
    measure.add_argument('--instance', type=Path, required=True)
    measure.add_argument('--rounds', type=int, default=3)
    measure.add_argument('--quick')
    measure.add_argument('--parallel', action='store_true')
    measure.add_argument('--slots', type=int)
    options = parser.parse_args()
    if options.command == 'report':
        db = sqlite3.connect(f'file:{options.database.resolve()}?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        rows = breakdown(db, time.time() - options.hours * 3600)
        result = {'summary': summary(rows), 'turns': [rounded(row) for row in rows]}
    else:
        result = asyncio.run(run(options.instance, options.rounds, options.quick, parallel=options.parallel,
                                 limit=options.slots))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
