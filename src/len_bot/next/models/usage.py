"""Model usage: one row per call whose service reported tokens, kept after request bodies are pruned.

The purpose is the request role (``mind``, ``recap``, ``vision``, ``upkeep``, ``learner`` ...) or
``plugin:<name>``, ``asr``, ``expression_embedding``, ``sticker``, ``memory_summary``,
``memory_embedding``, ``reference_embedding`` and ``worker``.
"""
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..storage.sqlite import connect


SCHEMA = """
CREATE TABLE usage (
    id INTEGER PRIMARY KEY, time REAL NOT NULL, scene TEXT NOT NULL, purpose TEXT NOT NULL,
    provider TEXT NOT NULL, model TEXT NOT NULL,
    input INTEGER NOT NULL, output INTEGER NOT NULL, cached INTEGER
);
CREATE INDEX usage_time ON usage(time,scene);
"""
# Speech-to-text and embeddings are listed but do not count toward the daily token limit.
UNBUDGETED = frozenset({"asr", "expression_embedding", "memory_embedding", "reference_embedding"})


def record_usage(db, *, time: float, scene: str, purpose: str, provider: str, model: str,
                 tokens: dict | None) -> None:
    """Add one call inside the caller's transaction; a call without reported tokens adds nothing."""
    if tokens is None:
        return
    db.execute("INSERT INTO usage(time,scene,purpose,provider,model,input,output,cached) VALUES (?,?,?,?,?,?,?,?)",
               (time, scene, purpose, provider, model, tokens["input"], tokens["output"], tokens["cached"]))


def usage_rows(db, scenes: list[str] | None, since: float, until: float) -> list[dict]:
    condition = "" if scenes is None else f" AND scene IN ({','.join('?' for _ in scenes)})"
    return [dict(zip(("time", "scene", "purpose", "provider", "model", "input", "output", "cached"), row))
            for row in db.execute("SELECT time,scene,purpose,provider,model,input,output,cached FROM usage "
                                  "WHERE time>=? AND time<?" + condition, (since, until, *(scenes or ())))]


def instance_usage(db, scenes: list[str] | None, since: float, until: float, *,
                   trials_root: Path | None = None) -> list[dict]:
    """The instance's rows plus those of retained chat tests, which share its daily limit."""
    rows = usage_rows(db, scenes, since, until)
    if trials_root is not None:
        for path in sorted(trials_root.glob("*/state.db")):
            with closing(connect(path, readonly=True)) as trial:
                rows.extend(usage_rows(trial, scenes, since, until))
    return rows


def totals(rows: list[dict]) -> dict:
    return {"calls": len(rows), "input": sum(row["input"] for row in rows),
            "output": sum(row["output"] for row in rows),
            "cached": sum(row["cached"] for row in rows if row["cached"] is not None)}


def budgeted_tokens(rows: list[dict]) -> int:
    return sum(row["input"] + row["output"] for row in rows if row["purpose"] not in UNBUDGETED)


def summarize(rows: list[dict], timezone: str) -> dict:
    """Totals, then the same totals by model, by local day and model, and by scene and purpose."""
    zone = ZoneInfo(timezone)
    models, days, groups = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        models[row["provider"], row["model"]].append(row)
        days[datetime.fromtimestamp(row["time"], zone).date().isoformat(), row["provider"], row["model"]].append(row)
        groups[row["scene"], row["purpose"]].append(row)
    return {**totals(rows),
            "models": [{"provider": provider, "model": model, **totals(items)}
                       for (provider, model), items in sorted(models.items())],
            "days": [{"day": day, "provider": provider, "model": model, **totals(items)}
                     for (day, provider, model), items in sorted(days.items())],
            "groups": [{"scene": scene, "purpose": purpose, **totals(items)}
                       for (scene, purpose), items in sorted(groups.items())]}
