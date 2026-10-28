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

from len_bot.eval.replay import prepare, read_report, run, write_json
from len_bot.next.config import load_host_config


async def jargon_replay(root: Path, host, checkout: Path) -> dict:
    """Exercise the existing real upkeep worker on fixed fictional candidates."""
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
    persona_path = source.pop('persona')
    attention = source.pop('attention')
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
                for index, case in enumerate(fixtures['cases']):
                    for repeat, text in enumerate(case['messages']):
                        raw = {'post_type': 'message', 'message_type': 'group', 'self_id': 90002,
                               'group_id': 80001, 'user_id': 70001 + repeat % 2,
                               'message_id': f'jargon-{index}-{repeat}', 'time': time.time(),
                               'sender': {'nickname': f'成员{repeat % 2}', 'role': 'member'},
                               'message': [{'type': 'text', 'data': {'text': text}}]}
                        seq = store.enqueue(parse_message(raw, own_message_ids=set()), raw, time.time())
                        if repeat == 0:
                            proposals.append((case['term'], seq))
                call = records.begin_discovery(scene, 0, store.max_message_seq(scene), {})
                records.complete_discovery(call, proposals, exclude_uids=[])
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
            kinds = {case['term']: case['kind'] for case in fixtures['cases']}
            return {'items': items, 'calls': calls, 'requests': len(calls),
                    'ordinary_rejected': sum(kinds[item['term']] == 'ordinary' and item['status'] == 'rejected' for item in items),
                    'jargon_rejected': sum(kinds[item['term']] == 'jargon' and item['status'] == 'rejected' for item in items)}
    finally:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path)
    parser.add_argument('--label')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--jargon', action='store_true')
    parser.add_argument('--persona', type=Path)
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
    if options.jargon:
        result = asyncio.run(jargon_replay(root, host, checkout))
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
    source['evaluation'].update(sets={'social': str(checkout / 'examples/replay/social.json')},
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
