"""Compact stopped SQLite databases after expiring old request snapshots, using VACUUM INTO."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

from ..instance_lock import instance_lock
from ..runtime.logs import run_maintenance
from ..runtime.retention import expire_request
from ..storage.codec import encode
from ..storage.files import sync_directory
from ..storage.sqlite import BUSY_TIMEOUT_SECONDS, checkpoint
from .snapshot import HEADROOM

BUSINESS_ID = 0x4C424E31
MEMORY_JOBS_ID = 0x4C424E32


def _tables(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _expire_business_snapshots(db: sqlite3.Connection, cutoff: float, now: float) -> dict[str, int]:
    """Expire request/response blobs in a stopped business database of any published format (1..current)."""
    tables = _tables(db)
    counts = {'model_snapshots': 0, 'auxiliary_snapshots': 0, 'task_snapshots': 0}
    if 'model_calls' in tables:
        latest = {row[0] for row in db.execute(
            "SELECT MAX(id) FROM model_calls WHERE role='mind' AND plugin IS NULL GROUP BY scene"
        ) if row[0] is not None}
        cursor = 0
        while rows := db.execute(
            "SELECT c.id,c.request FROM model_calls c LEFT JOIN turns t ON t.id=c.turn_id "
            "WHERE c.id>? AND c.ended IS NOT NULL AND c.ended<? "
            "AND (c.turn_id IS NULL OR t.ended IS NOT NULL) "
            "AND json_extract(c.request,'$.snapshot_expired_at') IS NULL ORDER BY c.id LIMIT 200",
            (cursor, cutoff),
        ).fetchall():
            cursor = rows[-1][0]
            updates = [(encode(expire_request(json.loads(raw), now)), call_id)
                       for call_id, raw in rows if call_id not in latest]
            if updates:
                with db:
                    db.executemany('UPDATE model_calls SET request=?,response=NULL WHERE id=?', updates)
                counts['model_snapshots'] += len(updates)
    for table in ('audio_calls', 'expression_embedding_calls', 'learning_batches',
                  'jargon_calls', 'sticker_calls', 'reply_effect_calls'):
        if table not in tables:
            continue
        status = (" AND status='complete'"
                  if table in {'learning_batches', 'jargon_calls', 'sticker_calls', 'reply_effect_calls'} else '')
        response = '' if table == 'expression_embedding_calls' else ',response=NULL'
        cursor = 0
        while rows := db.execute(
            f"SELECT id,request FROM {table} WHERE id>? AND ended<? AND request IS NOT NULL "
            "AND json_extract(request,'$.snapshot_expired_at') IS NULL" + status + " ORDER BY id LIMIT 200",
            (cursor, cutoff),
        ).fetchall():
            cursor = rows[-1][0]
            with db:
                db.executemany(f'UPDATE {table} SET request=?{response} WHERE id=?',
                               [(encode(expire_request(json.loads(raw), now)), row_id) for row_id, raw in rows])
            counts['auxiliary_snapshots'] += len(rows)
    if {'task_events', 'tasks'} <= tables:
        cursor = 0
        while rows := db.execute(
            "SELECT e.id,e.body FROM task_events e JOIN tasks t ON t.id=e.task_id "
            "WHERE e.id>? AND e.kind='model_call' AND t.status IN ('done','failed','cancelled') "
            "AND json_extract(e.body,'$.ended')<? AND json_extract(e.body,'$.request.snapshot_expired_at') IS NULL "
            "ORDER BY e.id LIMIT 200", (cursor, cutoff),
        ).fetchall():
            cursor = rows[-1][0]
            updates = []
            for row_id, raw in rows:
                body = json.loads(raw)
                body['request'] = expire_request(body['request'], now)
                body['response']['error_body'] = None
                updates.append((encode(body), row_id))
            with db:
                db.executemany('UPDATE task_events SET body=? WHERE id=?', updates)
            counts['task_snapshots'] += len(updates)
    return counts


def _expire_memory_snapshots(db: sqlite3.Connection, cutoff: float, now: float) -> dict[str, int]:
    tables = _tables(db)
    counts = {'memory_snapshots': 0, 'extraction_jobs': 0}
    for table in ('memory_summary_runs', 'memory_embedding_calls'):
        if table not in tables:
            continue
        status = " AND status='complete'" if table == 'memory_summary_runs' else ''
        response = '' if table == 'memory_embedding_calls' else ',response=NULL'
        cursor = 0
        while rows := db.execute(
            f"SELECT id,request FROM {table} WHERE id>? AND ended<? "
            "AND json_extract(request,'$.snapshot_expired_at') IS NULL" + status + " ORDER BY id LIMIT 200",
            (cursor, cutoff),
        ).fetchall():
            cursor = rows[-1][0]
            with db:
                db.executemany(f'UPDATE {table} SET request=?{response} WHERE id=?',
                               [(encode(expire_request(json.loads(raw), now)), row_id) for row_id, raw in rows])
            counts['memory_snapshots'] += len(rows)
    if 'memory_jobs' in tables:
        cursor = 0
        while rows := db.execute(
            "SELECT j.id,j.details FROM memory_jobs j WHERE j.id>? AND j.status='complete' AND j.ended<? "
            "AND (EXISTS(SELECT 1 FROM json_each(j.details,'$.calls') c "
            "WHERE json_extract(c.value,'$.request.snapshot_expired_at') IS NULL) "
            "OR EXISTS(SELECT 1 FROM json_each(j.details,'$.tools') t "
            "WHERE json_extract(t.value,'$.arguments.snapshot_expired_at') IS NULL)) ORDER BY j.id LIMIT 200",
            (cursor, cutoff),
        ).fetchall():
            cursor = rows[-1][0]
            updates = []
            for row_id, raw in rows:
                details = json.loads(raw)
                for call in details.get('calls', []):
                    call['request'] = expire_request(call['request'], now)
                    call['response'] = None
                for tool in details.get('tools', []):
                    tool['arguments'] = {'snapshot_expired_at': now}
                    tool['result'] = None
                updates.append((encode(details), row_id))
            with db:
                db.executemany('UPDATE memory_jobs SET details=? WHERE id=?', updates)
            counts['extraction_jobs'] += len(updates)
    return counts


def compact_sqlite_file(path: Path, *, request_days: int | None = None, now: float | None = None,
                        scratch_dir: Path | None = None, dry_run: bool = False) -> dict:
    """Expire old snapshots (when ``request_days`` is set) and rewrite ``path`` via ``VACUUM INTO``."""
    if not path.is_file() or path.is_symlink():
        return {'path': str(path), 'present': False}
    before_bytes = path.stat().st_size
    wal = path.with_name(path.name + '-wal')
    shm = path.with_name(path.name + '-shm')
    if not dry_run and wal.is_file():
        checkpoint(path)
    now_ts = time.time() if now is None else now
    expired: dict[str, int] = {}
    uri = path.resolve().as_uri() + ('?mode=ro' if dry_run else '?mode=rw')
    with closing(sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS)) as db:
        application = db.execute('PRAGMA application_id').fetchone()[0]
        if request_days is not None and not dry_run:
            cutoff = now_ts - request_days * 86400
            if application == BUSINESS_ID:
                expired = _expire_business_snapshots(db, cutoff, now_ts)
            elif application == MEMORY_JOBS_ID:
                expired = _expire_memory_snapshots(db, cutoff, now_ts)
        page_size = db.execute('PRAGMA page_size').fetchone()[0]
        page_count = db.execute('PRAGMA page_count').fetchone()[0]
        freelist_count = db.execute('PRAGMA freelist_count').fetchone()[0]
        live_bytes = max(0, page_count - freelist_count) * page_size
        target_parent = path.parent if scratch_dir is None else scratch_dir.resolve()
        needed = live_bytes + HEADROOM
        if dry_run:
            probe = target_parent
            while not probe.exists() and probe.parent != probe:
                probe = probe.parent
            free = shutil.disk_usage(probe).free
            return {'path': str(path), 'present': True, 'dry_run': True, 'before_bytes': before_bytes,
                    'estimated_after_bytes': live_bytes, 'reclaimable_bytes': max(0, before_bytes - live_bytes),
                    'needed_scratch_bytes': needed, 'free_bytes': free}
        target_parent.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(target_parent).free
        if free < needed:
            raise OSError(f'压缩 {path} 预计需要约 {needed / 2**30:.2f} GiB 临时空间，'
                          f'{target_parent} 所在磁盘只剩 {free / 2**30:.2f} GiB')
        if wal.is_file():
            busy, frames, moved = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if busy or frames != moved:
                raise sqlite3.OperationalError(f'{path} 的 WAL 未能完整写回（busy={busy}）')
        temp_path = target_parent / f'.{path.name}.compact-{os.getpid()}'
        temp_path.unlink(missing_ok=True)
        try:
            escaped = str(temp_path).replace("'", "''")
            db.execute(f"VACUUM INTO '{escaped}'")
            with closing(sqlite3.connect(temp_path.resolve().as_uri() + '?mode=ro', uri=True)) as check_db:
                verdict = [row[0] for row in check_db.execute('PRAGMA quick_check')]
                if verdict != ['ok']:
                    raise sqlite3.DatabaseError(f'Compacted database failed quick_check: {verdict}')
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    shutil.copystat(path, temp_path)
    if os.name == 'posix' and os.geteuid() == 0:
        info = path.stat()
        os.chown(temp_path, info.st_uid, info.st_gid)
    for sidecar in (wal, shm):
        sidecar.unlink(missing_ok=True)
    if temp_path.parent == path.parent:
        os.replace(temp_path, path)
    else:
        staging = path.with_name(f'.{path.name}.replacing-{os.getpid()}')
        try:
            shutil.copy2(temp_path, staging)
            os.replace(staging, path)
        finally:
            staging.unlink(missing_ok=True)
            temp_path.unlink(missing_ok=True)
    sync_directory(path.parent)
    after_bytes = path.stat().st_size
    return {'path': str(path), 'present': True, 'before_bytes': before_bytes, 'after_bytes': after_bytes,
            'reclaimed_bytes': before_bytes - after_bytes, 'expired': expired}


def _configured_databases(root: Path) -> tuple[list[Path], int | None]:
    raw = json.loads((root / 'lenbot.config.json').read_text(encoding='utf-8'))
    db_value = raw.get('database', 'data/state.sqlite3')
    business = Path(db_value) if Path(db_value).is_absolute() else root / db_value
    memory = business.with_name(business.name + '.memory.sqlite3')
    retention = raw.get('retention')
    days = int(retention.get('request_days', 7)) if isinstance(retention, dict) else None
    return [business, memory], days


def compact_instance(root: Path, *, request_days: int | None = None, scratch_dir: Path | None = None,
                     dry_run: bool = False, now: float | None = None) -> dict:
    """Compact the stopped instance's business and memory-job databases under the instance lock."""
    from .upgrade import _trial_roots

    with ExitStack() as locks:
        locks.enter_context(instance_lock(root))
        trials = _trial_roots(root)
        for directory in trials:
            locks.enter_context(instance_lock(directory))
        results = []
        for directory in (root, *trials):
            paths, configured_days = _configured_databases(directory)
            effective_days = configured_days if request_days is None else request_days
            for db_path in paths:
                results.append(compact_sqlite_file(
                    db_path, request_days=effective_days if effective_days is not None and effective_days > 0 else None,
                    now=now, scratch_dir=scratch_dir, dry_run=dry_run,
                ))
        reclaimed = sum(item.get('reclaimed_bytes', item.get('reclaimable_bytes', 0)) for item in results)
        return {'status': 'ok', 'dry_run': dry_run, 'databases': results, 'reclaimed_bytes': reclaimed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-days', type=int, default=None,
                        help='Expire snapshots older than N days before VACUUM INTO (0 skips snapshot expiry)')
    parser.add_argument('--scratch-dir', type=Path, default=None,
                        help='Optional directory on another filesystem with enough free space for VACUUM INTO')
    parser.add_argument('--dry-run', action='store_true',
                        help='Estimate reclaimable bytes without modifying any database')
    args = parser.parse_args()
    if args.request_days is not None and args.request_days < 0:
        parser.error('--request-days must be >= 0')
    result = compact_instance(Path.cwd(), request_days=args.request_days,
                              scratch_dir=args.scratch_dir, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    run_maintenance(main, 'compact')
