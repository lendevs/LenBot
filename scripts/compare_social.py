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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path)
    parser.add_argument('--label')
    parser.add_argument('--report', type=Path)
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
