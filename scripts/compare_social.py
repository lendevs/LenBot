"""Run the fixed social cases with the existing isolated replay evaluator.

    uv run --no-sync python scripts/compare_social.py --instance . --label s71-baseline

Only model credentials/settings are read from the source instance. Each run has its own simulated
configuration, persona snapshot, database and logs under state/experiments/social-<date>/<label>.
Review annotations.json in the timestamped runs directory, then pass that directory to --report.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3

from len_bot.eval.replay import prepare, read_report, run, write_json
from len_bot.next.config import load_host_config


async def jargon_replay(root: Path, host, checkout: Path, *, existing: bool = False) -> dict:
    """Run the upkeep worker on fictional candidates or a read-only copy of existing examples."""
    from len_bot.next.chat.session import Chat
    from len_bot.next.chat.upkeep import SessionUpkeep
    from len_bot.next.config import load_host_config
    from len_bot.next.learning.jargon_store import JargonStore
    from len_bot.next.models.client import ChatModel
    from len_bot.next.persona.profile import load_persona
    from len_bot.next.platform.onebot_messages import parse_message
    from len_bot.next.storage.store import Store
    import time

    source = json.loads((checkout / 'examples/replay/lenbot.config.example.json').read_text())
    mind = host.models.roles.mind
    source.update(persona='persona', attention={'only_direct': True}, learning={
        'extract': False, 'jargon_extract': True, 'batch_size': 100})
    source.pop('evaluation')
    scene = source.pop('scene')
    original = None
    if existing:
        original = sqlite3.connect(host.database.resolve().as_uri() + '?mode=ro', uri=True)
        original.row_factory = sqlite3.Row
        original.execute('BEGIN')
        scenes = [row[0] for row in original.execute('SELECT DISTINCT scene FROM jargon')]
        if len(scenes) != 1:
            original.close()
            raise ValueError(f'旧词条回放需要一个群的词库，当前为 {scenes}')
        scene = scenes[0]
        source['bot_id'] = host.bot_id
    persona_path = source.pop('persona')
    attention = source.pop('attention')
    if existing:
        attention = host.scenes[scene].attention.model_dump(mode='json')
    learning = source.pop('learning')
    source.update(mode='isolated-multi', onebot=None, scenes={scene: {
        'persona': persona_path, 'attention': attention, 'learning': learning}})
    source['models'] = {'providers': {mind.provider: host.models.providers[mind.provider].model_dump(mode='json')},
                        'roles': {'mind': mind.model_dump(mode='json')}}
    path = root / 'lenbot.config.json'
    write_json(path, source)
    path.chmod(0o600)
    fixtures = json.loads((checkout / 'examples/replay/jargon.json').read_text())
    write_json(root / 'cases.json', fixtures)
    try:
        config = load_host_config(root)
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                chat = Chat(config.scene_config(scene), load_persona(config.scenes[scene].persona), store, model)
                upkeep = SessionUpkeep(config, store, model)

                async def fork(scene):
                    return await chat.upkeep_fork()
                upkeep.fork = fork
                records = JargonStore(store)
                proposals = []
                if existing:
                    originals = [dict(row) for row in original.execute('SELECT * FROM jargon WHERE scene=?', (scene,))]
                    # A read transaction supplies a consistent set of words and neighboring originals.
                    messages = {}
                    for item in originals:
                        for seq in json.loads(item['sample_seqs']):
                            for operator, order, limit in [('<=', 'DESC', 4), ('>', 'ASC', 3)]:
                                rows = original.execute(
                                    "SELECT * FROM messages WHERE scene=? AND raw IS NOT NULL AND received_at IS NOT NULL "
                                    "AND json_extract(body,'$.is_self')=0 AND json_extract(body,'$.send_status')='received' "
                                    f"AND seq{operator}? ORDER BY seq {order} LIMIT ?", (scene, seq, limit))
                                for row in rows:
                                    messages[row['seq']] = dict(row)
                    with store.db:
                        for item in messages.values():
                            columns = list(item)
                            store.db.execute(f"INSERT INTO messages({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                             tuple(item.values()))
                        for item in originals:
                            columns = list(item)
                            store.db.execute(f"INSERT INTO jargon({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                             tuple(item.values()))
                        store.db.execute('UPDATE jargon_state SET start_seq=?,after_seq=? WHERE scene=?',
                                         (0, store.max_message_seq(scene), scene))
                    write_json(root / 'before.json', originals)
                else:
                    for index, case in enumerate(fixtures['cases']):
                        samples = []
                        for repeat, text in enumerate(case['messages']):
                            raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90002,
                                   'group_id': 80001, 'user_id': 70001 + repeat % 2,
                                   'message_id': f'jargon-{index}-{repeat}', 'time': time.time() + index * 3600 + repeat * 60,
                                   'sender': {'nickname': f'成员{repeat % 2}', 'role': 'member'},
                                   'message': [{'type': 'text', 'data': {'text': text}}]}
                            samples.append(store.enqueue(parse_message(raw, own_message_ids=set()), raw, time.time()))
                        proposals.append((scene, case['term'], len(samples), json.dumps(samples), time.time()))
                    with store.db:
                        store.db.executemany("INSERT INTO jargon(scene,term,count,sample_seqs,status,updated) "
                                             "VALUES (?,?,?,?,'pending',?)", proposals)
                changed = asyncio.Event()
                upkeep.on_update = changed.set
                upkeep.start()
                try:
                    upkeep.request(scene, 'jargon')
                    async with asyncio.timeout(600):
                        while records.pending(scene):
                            latest = records.latest(scene)
                            if latest is not None and latest['status'] in {'failed', 'interrupted'}:
                                raise RuntimeError(str(latest))
                            await changed.wait()
                            changed.clear()
                finally:
                    await upkeep.close()
            items = records.items(scene, status=None, limit=100, offset=0)['items']
            calls = [dict(row) for row in store.db.execute(
                "SELECT role,request,response,error,tokens FROM model_calls ORDER BY id")]
            kinds = {} if existing else {case['term']: case['kind'] for case in fixtures['cases']}
            token_usage = [json.loads(call['tokens']) for call in calls if call['tokens']]
            return {'items': items, 'calls': calls, 'requests': len(calls),
                    'tokens': {key: sum(usage.get(key) or 0 for usage in token_usage) for key in ('input', 'output', 'cached')},
                    'classifications': {key: sum(item['classification'] == key for item in items)
                                        for key in ('special', 'ordinary', 'uncertain')},
                    'ordinary_rejected': sum(kinds.get(item['term']) == 'ordinary' and item['classification'] == 'ordinary' for item in items),
                    'ordinary_learned': sum(kinds.get(item['term']) == 'ordinary' and item['classification'] == 'special' for item in items),
                    'jargon_rejected': sum(kinds.get(item['term']) == 'jargon' and item['classification'] != 'special' for item in items)}
    finally:
        if original is not None:
            original.close()
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path)
    parser.add_argument('--label')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--jargon', action='store_true')
    parser.add_argument('--jargon-existing', action='store_true', help='Reassess existing jargon in an isolated copy')
    parser.add_argument('--persona', type=Path)
    parser.add_argument('--cases', type=Path, help='A structured case file whose set is social')
    parser.add_argument('--repetitions', type=int, default=3)
    options = parser.parse_args()
    if options.report is not None:
        summary = read_report(options.report)
        write_json(options.report / 'report.json', summary)
        print(json.dumps({'quality': summary['quality'], 'social': summary['social']}, ensure_ascii=False, indent=2))
        return
    if options.instance is None or options.label is None:
        parser.error('--instance and --label are required for a run')
    if Path(options.label).name != options.label or options.label in {'.', '..'}:
        parser.error('--label must be one directory name')
    checkout = Path(__file__).resolve().parents[1]
    host = load_host_config(options.instance.resolve())
    root = checkout / 'state/experiments' / f'social-{datetime.now():%Y%m%d}' / options.label
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(options.persona or checkout / 'examples/personas/companion', root / 'persona')
    if options.jargon or options.jargon_existing:
        result = asyncio.run(jargon_replay(root, host, checkout, existing=options.jargon_existing))
        write_json(root / 'result.json', result)
        print(json.dumps({key: result[key] for key in ('requests', 'ordinary_rejected', 'jargon_rejected')}, ensure_ascii=False))
        return
    if options.persona is None:
        for original, numbered in {'happy.png': '01.png', 'agree.png': '02.png',
                                    'speechless.png': '03.png', 'confused.png': '04.png'}.items():
            (root / 'persona/stickers' / original).rename(root / 'persona/stickers' / numbered)
        shutil.copyfile(checkout / 'examples/replay/social-stickers.yaml', root / 'persona/stickers/index.yaml')
    source = json.loads((checkout / 'examples/replay/lenbot.config.example.json').read_text())
    mind = host.models.roles.mind
    source['models'] = {'providers': {mind.provider: host.models.providers[mind.provider].model_dump(mode='json')},
                        'roles': {'mind': mind.model_dump(mode='json')}}
    source.update(persona='persona', attention={})
    source['evaluation'].update(sets={'social': str(options.cases.resolve() if options.cases is not None
                                                  else checkout / 'examples/replay/social.json')},
                                repetitions=options.repetitions)
    path = root / 'lenbot.config.json'
    write_json(path, source)
    path.chmod(0o600)
    try:
        config, persona, cases, plan = prepare(root, 'social', 'current')
        destination, failed = asyncio.run(run(config, persona, cases, plan))
        write_json(destination / 'report.json', read_report(destination))
        print(json.dumps({'directory': str(destination), 'execution_errors': failed}, ensure_ascii=False))
        if failed:
            raise SystemExit(1)
    finally:
        path.unlink()


if __name__ == '__main__':
    main()
