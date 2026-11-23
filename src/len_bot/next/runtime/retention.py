"""Explicit retention of expired operational records, in bounded SQLite batches."""
from __future__ import annotations
import asyncio
from contextlib import nullcontext
from itertools import islice
import json
import logging
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .logs import log_event
from ..storage.store import encode, Store
from ..work.materials import finish_file_operation
from ..memory.jobs import MemoryJobs
from ..plugins.store import PluginStore


class RetentionSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    request_days: int = Field(default=7, ge=1)
    timeline_days: int = Field(default=90, ge=32)
    message_days: dict[str, int] = Field(default_factory=dict)

    @field_validator('message_days')
    @classmethod
    def scene_days(cls, values):
        if any(re.fullmatch(r'[a-z][a-z0-9_-]*:(group|private):[^:\s/\\]+', scene) is None or days < 1
               for scene, days in values.items()):
            raise ValueError('message_days requires actual scenes and positive days')
        return values


def expire_request(request: dict, now: float) -> dict:
    return {**{key: value for key, value in request.items() if key not in {'messages','tools','texts','request','recall_items'}},
            'snapshot_expired_at': now}


# One cycle a day; after a failed batch the next attempt comes sooner, doubling from RETRY_SECONDS up to the daily period.
PERIOD_SECONDS = 86400
RETRY_SECONDS = 300


LOG = logging.getLogger(__name__)
COUNTS = ('model_snapshots', 'auxiliary_snapshots', 'task_snapshots', 'turns', 'messages', 'notices',
          'memory_snapshots', 'extraction_jobs', 'plugin_calls', 'plugin_events')


def _latest_mind_calls(db) -> set[int]:
    # Seek to the next distinct scene, including archived scenes absent from the live configuration.
    scene = ''
    latest = set()
    while row := db.execute(
        "SELECT scene FROM model_calls INDEXED BY model_call_mind_usage "
        "WHERE plugin IS NULL AND scene>? ORDER BY scene LIMIT 1", (scene,),
    ).fetchone():
        scene = row[0]
        anchor = db.execute(
            "SELECT id FROM model_calls WHERE scene=? AND role='mind' AND plugin IS NULL ORDER BY id DESC LIMIT 1",
            (scene,)).fetchone()
        if anchor is not None:
            latest.add(anchor[0])
    return latest


def _snapshot_ids(db, cutoff, latest):
    # Calls can finish out of ID order. Advance in index order even across a whole page of anchors.
    cursor = (float('-inf'), 0)
    while page := db.execute(
        "WITH eligible AS NOT MATERIALIZED (SELECT c.ended,c.id FROM model_calls c INDEXED BY model_call_unexpired "
        "WHERE c.ended IS NOT NULL AND c.ended<? "
        "AND json_extract(c.request,'$.snapshot_expired_at') IS NULL AND (c.turn_id IS NULL OR EXISTS "
        "(SELECT 1 FROM turns t WHERE t.id=c.turn_id AND t.ended IS NOT NULL))) "
        "SELECT ended,id FROM eligible WHERE ended=? AND id>? UNION ALL "
        "SELECT ended,id FROM eligible WHERE ended>? ORDER BY ended,id LIMIT 100",
        (cutoff, *cursor, cursor[0]),
    ).fetchall():
        cursor = tuple(page[-1])
        yield from (id for _, id in page if id not in latest)


def _expired_plugin_calls(db, timeline):
    cursor = ('', 0)
    while page := db.execute(
        "WITH expired AS NOT MATERIALIZED (SELECT plugin,id FROM model_calls INDEXED BY model_call_plugin "
        "WHERE plugin IS NOT NULL AND ended<?) "
        "SELECT plugin,id FROM expired WHERE plugin=? AND id>? UNION ALL "
        "SELECT plugin,id FROM expired WHERE plugin>? ORDER BY plugin,id LIMIT 100",
        (timeline, *cursor, cursor[0]),
    ).fetchall():
        cursor = tuple(page[-1])
        yield from (id for _, id in page)


def _delivered_events(db, timeline):
    cursor = 0
    while page := db.execute(
        "SELECT id FROM plugin_events WHERE id>? AND delivered_at IS NOT NULL AND created<? ORDER BY id LIMIT 100",
        (cursor, timeline),
    ).fetchall():
        cursor = page[-1][0]
        yield from (row[0] for row in page)


class Retention:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = asyncio.Lock()
        self.last_result = None
        self.error = None
        self.retry = None
        self.changed = asyncio.Event()

    def wake(self) -> None:
        """Run a batch now under the saved settings; turning retention on starts the daily cycle."""
        self.error = None
        self.retry = None
        self.changed.set()

    def batch(self, *, preview: bool = False, drain: bool = False) -> dict:
        path = self.runtime.config.database.with_name(self.runtime.config.database.name + '.memory.sqlite3')
        with Store(self.runtime.config.database, now=self.runtime.store.now, readonly=preview) as store, (
            MemoryJobs(path, readonly=preview) if path.exists() else nullcontext(None)
        ) as jobs:
            return self._batch(store, jobs, preview=preview, drain=drain)

    async def batch_async(self, *, preview: bool = False, drain: bool = False) -> dict:
        return await finish_file_operation(self.batch, preview=preview, drain=drain)

    def _batch(self, store, memory_jobs, *, preview: bool, drain: bool = False) -> dict:
        config = self.runtime.config
        settings = config.retention
        if settings is None:
            raise ValueError('当前运行配置未启用保留策略')
        db, now = store.db, store.now()
        cutoff, timeline = now - settings.request_days * 86400, now - settings.timeline_days * 86400
        latest = _latest_mind_calls(db)
        snapshots = _snapshot_ids(db, cutoff, latest)
        plugin_calls = _expired_plugin_calls(db, timeline)
        events = _delivered_events(db, timeline)
        totals = dict.fromkeys(COUNTS, 0)
        while True:
            result = self._apply_batch(store, memory_jobs, settings, now, cutoff, timeline, latest,
                                       list(islice(snapshots, 100)), list(islice(plugin_calls, 100)),
                                       list(islice(events, 100)), preview=preview)
            if preview:
                return result
            for key in COUNTS:
                totals[key] += result[key]
            if not drain or not any(result[key] for key in COUNTS) or self.runtime.stopped.is_set():
                break
        self.last_result = {**result, **totals}
        if any(totals.values()):
            log_event(LOG, 'retention_finished', **totals)
        return self.last_result

    def _apply_batch(self, store, memory_jobs, settings, now, cutoff, timeline, latest,
                     snapshots, old_plugin_calls, old_events, *, preview):
        db = store.db
        auxiliary = {}
        for table in ('audio_calls','expression_embedding_calls','learning_batches','jargon_calls',
                      'sticker_calls','reply_effect_calls'):
            status = " AND status='complete'" if table in {'learning_batches','jargon_calls','sticker_calls','reply_effect_calls'} else ''
            auxiliary[table] = db.execute(
                f"SELECT id,request FROM {table} WHERE ended<? AND request IS NOT NULL "
                "AND json_extract(request,'$.snapshot_expired_at') IS NULL" + status + " ORDER BY ended LIMIT 100",
                (cutoff,)).fetchall()
        task_calls = db.execute(
            "SELECT e.id,e.body FROM task_events e JOIN tasks t ON t.id=e.task_id "
            "WHERE e.kind='model_call' AND t.status IN ('done','failed','cancelled') "
            "AND json_extract(e.body,'$.ended')<? AND json_extract(e.body,'$.request.snapshot_expired_at') IS NULL "
            "ORDER BY e.id LIMIT 100", (cutoff,)).fetchall()
        old_turns = db.execute(
            "SELECT id FROM turns WHERE ended<? AND id NOT IN "
            "(SELECT turn_id FROM model_calls WHERE turn_id IS NOT NULL AND id IN "
            "(SELECT value FROM json_each(?) UNION ALL SELECT MAX(id) FROM model_calls)) "
            "AND NOT EXISTS(SELECT 1 FROM reply_effects r WHERE r.turn_id=turns.id) "
            "AND NOT EXISTS(SELECT 1 FROM proactive_wakes p WHERE p.turn_id=turns.id) "
            "AND NOT EXISTS(SELECT 1 FROM expression_embedding_calls e WHERE e.turn_id=turns.id) "
            "ORDER BY ended LIMIT 100", (timeline, encode(sorted(latest)))).fetchall()
        selected_messages = []
        selected_notices = []
        for scene, days in settings.message_days.items():
            threshold = now - days * 86400
            session = db.execute('SELECT last_message_seq,compact_through FROM mind_sessions WHERE scene=?',(scene,)).fetchone()
            if session is None:
                continue
            through = session[0]
            # Preserve unprocessed input of active learning/ingest pipelines.
            for table in ('learning_state','jargon_state'):
                cursor = db.execute(f'SELECT after_seq FROM {table} WHERE scene=?',(scene,)).fetchone()
                if cursor is not None:
                    through = min(through, cursor[0])
            scenes = self.runtime.config.scenes
            plugin = scenes[scene].memory_plugin if scene in scenes else None
            if plugin is not None:
                # Only the scene's current memory holds originals back; the native cursor is not in use.
                progress = PluginStore(store).memory_progress(scene, plugin)
                if progress is not None:
                    through = min(through, progress)
            elif memory_jobs is not None:
                jobs = memory_jobs.db
                cursor = jobs.execute('SELECT after_seq FROM memory_cursors WHERE scene=?',(scene,)).fetchone()
                if cursor is not None:
                    through = min(through, cursor[0])
                pending = jobs.execute("SELECT MIN(first_seq) FROM memory_jobs WHERE scene=? AND status!='complete'",(scene,)).fetchone()[0]
                if pending is not None:
                    through = min(through, pending - 1)
            active = db.execute('SELECT MIN(created) FROM mind_entries WHERE scene=? AND seq>?',
                                (scene, session['compact_through'])).fetchone()[0]
            if active is not None:
                if session['compact_through'] == 0:
                    continue
                threshold = min(threshold, active)
            selected_messages.extend(db.execute(
                "SELECT m.seq,m.scene,m.platform_id FROM messages m WHERE m.scene=? AND m.seq<=? "
                "AND COALESCE(m.received_at,json_extract(m.body,'$.time'))<? "
                "AND m.seq<(SELECT MAX(seq) FROM messages WHERE scene=?) "
                "AND NOT EXISTS(SELECT 1 FROM expressions e,json_each(e.sources) s WHERE e.scene=m.scene AND s.value=m.seq) "
                "AND NOT EXISTS(SELECT 1 FROM jargon j,json_each(j.sample_seqs) s WHERE j.scene=m.scene AND s.value=m.seq) "
                "AND NOT EXISTS(SELECT 1 FROM sticker_candidates c WHERE c.source_message_seq=m.seq) "
                "AND NOT EXISTS(SELECT 1 FROM sticker_calls c WHERE c.source_message_seq=m.seq) "
                "AND NOT EXISTS(SELECT 1 FROM reply_effects r,json_each(r.message_seqs) s WHERE r.scene=m.scene AND s.value=m.seq) "
                "AND NOT EXISTS(SELECT 1 FROM reply_effects r,json_each(r.observed_seqs) s WHERE r.scene=m.scene AND s.value=m.seq) "
                "AND NOT EXISTS(SELECT 1 FROM media original JOIN message_media link ON link.media_id=original.id "
                "WHERE original.source_message_seq=m.seq AND link.message_seq!=m.seq) "
                "AND NOT EXISTS(SELECT 1 FROM audio_cache a WHERE a.scene=m.scene AND a.platform_id=m.platform_id "
                "AND (a.status IN ('queued','running') OR (a.transcript IS NOT NULL AND a.announced_at IS NULL))) "
                "ORDER BY m.seq LIMIT 100",
                (scene,through,threshold,scene)).fetchall())
            selected_notices.extend(db.execute(
                "SELECT id FROM notices WHERE scene=? AND received_at<? AND id<(SELECT MAX(id) FROM notices) "
                "AND (platform_id IS NULL OR NOT EXISTS(SELECT 1 FROM messages m WHERE m.scene=notices.scene "
                "AND m.platform_id=notices.platform_id)) ORDER BY id LIMIT 100", (scene,threshold)).fetchall())
        memory_calls, extraction_jobs = {}, []
        if memory_jobs is not None:
            for table in ('memory_summary_runs', 'memory_embedding_calls'):
                status = " AND status='complete'" if table == 'memory_summary_runs' else ''
                memory_calls[table] = memory_jobs.db.execute(
                    f"SELECT id,request FROM {table} WHERE ended<? "
                    "AND json_extract(request,'$.snapshot_expired_at') IS NULL" + status + " ORDER BY ended LIMIT 100",
                    (cutoff,)).fetchall()
            extraction_jobs = memory_jobs.db.execute(
                "SELECT j.id,j.details FROM memory_jobs j WHERE j.status='complete' AND j.ended<? "
                "AND (EXISTS(SELECT 1 FROM json_each(j.details,'$.calls') c "
                "WHERE json_extract(c.value,'$.request.snapshot_expired_at') IS NULL) "
                "OR EXISTS(SELECT 1 FROM json_each(j.details,'$.tools') t "
                "WHERE json_extract(t.value,'$.arguments.snapshot_expired_at') IS NULL)) ORDER BY j.id LIMIT 100",
                (cutoff,)).fetchall()
        result = {'preview': preview, 'at': now, 'model_snapshots': len(snapshots),
                  'auxiliary_snapshots': sum(map(len,auxiliary.values())), 'task_snapshots':len(task_calls),
                  'turns':len(old_turns), 'plugin_calls':len(old_plugin_calls), 'plugin_events': len(old_events),
                  'messages':len(selected_messages), 'notices':len(selected_notices),
                  'protected_latest_mind_requests':len(latest),
                  'memory_snapshots':sum(map(len,memory_calls.values())), 'extraction_jobs':len(extraction_jobs),
                  'scope':'保留活跃上下文、未处理输入、显式素材来源和仍被引用的轮次。'}
        if preview:
            return result
        with db:
            for id, raw in db.execute("SELECT id,request FROM model_calls WHERE id IN (SELECT value FROM json_each(?))",
                                      (encode(snapshots),)).fetchall():
                db.execute('UPDATE model_calls SET request=?,response=NULL WHERE id=?',
                           (encode(expire_request(json.loads(raw),now)),id))
            for table, calls in auxiliary.items():
                for id, raw in calls:
                    response = '' if table == 'expression_embedding_calls' else ',response=NULL'
                    db.execute(f'UPDATE {table} SET request=?{response} WHERE id=?',
                               (encode(expire_request(json.loads(raw),now)),id))
            for id, raw in task_calls:
                body=json.loads(raw);body['request']=expire_request(body['request'],now)
                body['response']['error_body']=None
                db.execute('UPDATE task_events SET body=? WHERE id=?',(encode(body),id))
            for (id,) in old_turns:
                db.execute('DELETE FROM model_calls WHERE turn_id=?',(id,))
                db.execute('DELETE FROM turns WHERE id=?',(id,))
            for id in old_plugin_calls:
                db.execute('DELETE FROM model_calls WHERE id=?', (id,))
            for id in old_events:
                db.execute('DELETE FROM plugin_events WHERE id=?', (id,))
            for seq, scene, platform_id in selected_messages:
                db.execute('DELETE FROM image_cache WHERE scene=? AND platform_id=?',(scene,platform_id))
                db.execute('DELETE FROM audio_cache WHERE scene=? AND platform_id=?',(scene,platform_id))
                db.execute('DELETE FROM message_media WHERE message_seq=?',(seq,))
                # Only unreferenced originals go away. Shared/adopted images retain their source message.
                db.execute('DELETE FROM media WHERE source_message_seq=? AND id NOT IN (SELECT media_id FROM message_media) '
                           'AND id NOT IN (SELECT media_id FROM sticker_candidates WHERE media_id IS NOT NULL)',(seq,))
                db.execute('DELETE FROM message_search WHERE rowid=?',(seq,))
                db.execute('DELETE FROM messages WHERE seq=?',(seq,))
            for (id,) in selected_notices:
                db.execute('DELETE FROM notices WHERE id=?',(id,))
        if memory_jobs is not None:
            with memory_jobs.db:
                for table, calls in memory_calls.items():
                    for id, raw in calls:
                        response = '' if table == 'memory_embedding_calls' else ',response=NULL'
                        memory_jobs.db.execute(f'UPDATE {table} SET request=?{response} WHERE id=?',
                                               (encode(expire_request(json.loads(raw),now)),id))
                for id, raw in extraction_jobs:
                    details=json.loads(raw)
                    for call in details['calls']:
                        call['request']=expire_request(call['request'],now)
                        call['response']=None
                    for tool in details.get('tools', []):
                        tool['arguments'] = {'snapshot_expired_at': now}
                        tool['result'] = None
                    memory_jobs.db.execute('UPDATE memory_jobs SET details=? WHERE id=?',(encode(details),id))
        return result

    async def run(self):
        while not self.runtime.stopped.is_set():
            self.changed.clear()
            if self.runtime.config.retention is not None:
                try:
                    async with self.lock:
                        await self.batch_async(drain=True)
                        self.runtime.notify()
                    self.error = self.retry = None
                except Exception as error:
                    self.error=f'{type(error).__name__}: {error}'
                    self.retry = RETRY_SECONDS if self.retry is None else min(self.retry * 2, PERIOD_SECONDS)
                    self.runtime._emit({'type':'retention','status':'failed','error':self.error})
            stopping = asyncio.ensure_future(self.runtime.stopped.wait())
            changed = asyncio.ensure_future(self.changed.wait())
            try:
                await asyncio.wait({stopping, changed}, timeout=PERIOD_SECONDS if self.retry is None else self.retry, return_when=asyncio.FIRST_COMPLETED)
            finally:
                stopping.cancel()
                changed.cancel()
