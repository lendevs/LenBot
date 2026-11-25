"""Opening wakes, successful expressions and mind tokens by scene-local day."""

from collections import defaultdict
from datetime import datetime
import json
from zoneinfo import ZoneInfo

from ..models.tokens import token_summary


def wake_usage(store, scenes: list[str] | None, since: float, until: float, timezone: str) -> list[dict]:
    if scenes is not None and not scenes:
        return []
    if scenes is None:
        where, params = 'started>=? AND started<?', (since, until)
    else:
        where = f"scene IN ({','.join('?' for _ in scenes)}) AND started>=? AND started<?"
        params = (*scenes, since, until)
    turns = list(store.db.execute(
        f'SELECT id,scene,started,wake_channel,first_expression_at FROM turns WHERE {where}',
        params))
    tokens = defaultdict(list)
    # Drive from the time-bounded turns CTE so SQLite probes model_calls via turn_calls instead of scanning it.
    for turn_id, body in store.db.execute(
        f'WITH recent_turns AS MATERIALIZED (SELECT id,wake_channel FROM turns WHERE {where}) '
        "SELECT c.turn_id,c.tokens FROM recent_turns CROSS JOIN model_calls c ON c.turn_id=recent_turns.id "
        "WHERE c.role='mind'",
        params):
        tokens[turn_id].append(None if body is None else json.loads(body))
    grouped = {}
    zone = ZoneInfo(timezone)
    for turn_id, scene, started, channel, expressed_at in turns:
        day = datetime.fromtimestamp(started, zone).date().isoformat()
        row = grouped.setdefault((scene, day, channel),
                                 {'scene': scene, 'day': day, 'channel': channel, 'wakes': 0, 'spoken': 0, 'tokens': []})
        row['wakes'] += 1
        row['spoken'] += expressed_at is not None
        row['tokens'].extend(tokens[turn_id])
    result = []
    for _, row in sorted(grouped.items()):
        counts = token_summary(row.pop('tokens'))
        result.append({**row, 'speech_rate': row['spoken'] / row['wakes'], **counts})
    return result
