"""Explicit offline upgrades from the public business format baseline."""

from contextlib import ExitStack
from pathlib import Path
import sqlite3
import sys
import time
import json

from ..config import load_instance_config
from ..instance_lock import instance_lock
from ..storage.store import FORMAT_VERSION
from .migrations import Format, upgrade
from .token_backfill import rename_and_backfill, upgrade_task_events
from ..runtime.logs import run_maintenance
from .wake_history import request_wake


APPLICATION_ID = 0x4C424E31


def _tokens_instead_of_prices(db: sqlite3.Connection) -> None:
    """Format 1 to 2: call records keep reported tokens instead of money estimates."""
    for table, kind in (('model_calls', None), ('audio_calls', 'asr'), ('learning_batches', 'chat'),
                        ('expression_embedding_calls', 'embedding'), ('jargon_calls', 'chat'),
                        ('sticker_calls', 'chat'), ('reply_effect_calls', 'chat')):
        rename_and_backfill(db, table, kind)
    upgrade_task_events(db)


def _qualified_schedule_targets(db: sqlite3.Connection) -> None:
    """Format 2 to 3: remind an account in the schedule's actual platform."""
    db.execute("UPDATE schedules SET target=substr(scene,1,instr(scene,':'))||target "
               "WHERE target!='self' AND instr(target,':')=0")


def _speech_records(db: sqlite3.Connection, *, now: float | None = None) -> None:
    """Format 3 to 4: hourly speech limits count expressions, not platform message parts.

    The last hour is seeded from the own group messages the old format counted (one row per
    delivered part, as before), so an upgrade does not hand out a second allowance for that hour.
    """
    db.execute("CREATE TABLE IF NOT EXISTS speech (id INTEGER PRIMARY KEY, scene TEXT NOT NULL, time REAL NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS scene_speech ON speech(scene, time)")
    since = (time.time() if now is None else now) - 3600
    db.execute(
        "INSERT INTO speech(scene,time) SELECT scene,json_extract(body,'$.time') FROM messages "
        "WHERE raw IS NULL AND json_extract(body,'$.is_self')=1 AND scene LIKE '%:group:%' "
        "AND json_extract(body,'$.time')>? "
        "AND json_extract(body,'$.send_status') IN ('sent','unconfirmed','simulated') "
        "AND NOT EXISTS (SELECT 1 FROM speech) ORDER BY json_extract(body,'$.time')", (since,))


def _turn_wake_channels(db: sqlite3.Connection) -> None:
    """Format 4 to 5: persist the opening wake; backfill retained historical mind requests."""
    db.execute("ALTER TABLE turns ADD COLUMN wake_channel TEXT NOT NULL DEFAULT 'unknown'")
    rows = db.execute(
        "SELECT t.id,c.request FROM turns t JOIN model_calls c ON c.id="
        "(SELECT MIN(id) FROM model_calls WHERE turn_id=t.id AND role='mind')").fetchall()
    for turn_id, request in rows:
        channel, _ = request_wake(json.loads(request))
        db.execute('UPDATE turns SET wake_channel=? WHERE id=?', (channel, turn_id))
    db.execute("UPDATE turns SET wake_channel='proactive' WHERE id IN (SELECT turn_id FROM proactive_wakes)")


def _overview_indexes(db: sqlite3.Connection) -> None:
    """Format 5 to 6: statistics read small indexes instead of model request bodies."""
    db.execute('DROP INDEX model_call_usage')
    db.execute('CREATE INDEX model_call_usage ON model_calls(started,scene,role,plugin,ended,tokens,error)')
    db.execute("CREATE INDEX message_overview ON messages(scene, "
               "CASE WHEN raw IS NULL THEN json_extract(body,'$.time') ELSE received_at END, "
               "json_extract(body,'$.send_status'),raw IS NULL)")
    db.execute("CREATE INDEX message_failed_sends ON messages(scene,json_extract(body,'$.time'),json_extract(body,'$.send_status')) "
               "WHERE raw IS NULL AND json_extract(body,'$.send_status') IN ('failed','unconfirmed')")


BUSINESS = Format('业务数据库', APPLICATION_ID, FORMAT_VERSION, 1, {
    1: _tokens_instead_of_prices,
    2: _qualified_schedule_targets,
    3: _speech_records,
    4: _turn_wake_channels,
    5: _overview_indexes,
})


def migrate(path: Path, *, backup: bool = True) -> Path | None:
    copy = upgrade(path, BUSINESS, backup=backup)
    print(f'{path}: business format {FORMAT_VERSION}' + ('' if copy is None else f'; input-format copy: {copy}'))
    return copy


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit('Business migration takes no arguments; use the instance root configuration')
    root = Path.cwd()
    with ExitStack() as locks:
        locks.enter_context(instance_lock(root))
        trials = sorted((root / '.runtime' / 'chat-tests').glob('*/state.db'))
        for path in trials:
            if path.is_symlink():
                raise ValueError(f'Trial database must not be a symbolic link: {path}')
            locks.enter_context(instance_lock(path.parent))
        for path in (load_instance_config(root).database, *trials):
            migrate(path)


if __name__ == '__main__':
    run_maintenance(main, 'migrate')
