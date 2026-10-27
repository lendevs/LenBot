"""Typed scene timelines and step-oriented views of retained turn records."""

import asyncio
import base64
import json
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...models.tokens import token_summary
from ...platform.messages import Sender, render_body
from ...storage.codec import decode_message
from ...storage.store import Store


class Verdict(BaseModel):
    woke: bool
    channel: Literal['direct', 'named', 'attention', 'focus', 'ambient', 'explore'] | None
    reason: str
    score: float | None
    threshold: float | None


class Image(BaseModel):
    index: int
    url: str | None
    summary: str | None


class Reply(BaseModel):
    platform_message_id: str
    sender: Sender
    text: str


class TimelineMessage(BaseModel):
    type: Literal['message'] = 'message'
    at: float
    message_seq: int
    platform_message_id: str | None
    sender: Sender
    time: float
    text: str
    images: list[Image]
    reply_to: str | None
    reply: Reply | None
    is_self: bool
    status: str
    recalled: bool
    verdict: Verdict | None


class Tokens(BaseModel):
    input: int
    output: int
    cached: int
    known_calls: int
    unknown_calls: int


class TimelineTurn(BaseModel):
    type: Literal['turn'] = 'turn'
    at: float
    turn_id: str
    status: str
    channel: str
    started: float
    ended: float | None
    steps: int
    expressions: int
    tokens: Tokens
    tools: list[str]
    error: str | None
    # Seconds from the message that woke the turn (or the turn's start) to its first expression.
    first_expression_wait: float | None


class TimelineNotice(BaseModel):
    """A platform notice: someone joined, left, recalled a message, changed a group card, and so on."""
    type: Literal['notice'] = 'notice'
    at: float
    id: int
    kind: str
    sub_type: str | None
    time: float
    user_id: str | None
    user_name: str | None
    operator_id: str | None
    operator_name: str | None
    duration: int | None
    platform_message_id: str | None
    raw: dict


class TimelinePage(BaseModel):
    scene: str
    items: list[Annotated[TimelineMessage | TimelineTurn | TimelineNotice, Field(discriminator='type')]]
    next_before: str | None


class ToolDetail(BaseModel):
    call_id: str
    name: str
    arguments: dict
    result: str | None
    status: Literal['pending', 'complete', 'error', 'interrupted']
    messages: list[TimelineMessage]


class CallTokens(BaseModel):
    input: int
    output: int
    cached: int | None


class ModelStep(BaseModel):
    id: int
    role: str
    started: float
    ended: float | None
    error: str | None
    tokens: CallTokens | None
    snapshot_expired_at: float | None


class Step(BaseModel):
    step: int
    models: list[ModelStep]
    text: str
    thoughts: list[str]
    tools: list[ToolDetail]


class RecallSection(BaseModel):
    start_char: int
    end_char: int
    headings: list[list[str]]
    source_version: str


class RecallItem(BaseModel):
    scope: str
    path: str
    content: str
    kind: str
    truncated: bool
    sections: list[RecallSection] = []


class TurnInfo(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str
    scene: str
    started: float
    ended: float | None
    status: str
    error: str | None
    wake_channel: str


class TurnDetail(BaseModel):
    turn: TurnInfo
    calls: list[dict]
    recall: list[RecallItem] | None
    steps: list[Step]


class Cursor(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    at: float = Field(allow_inf_nan=False)
    kind: Literal['message', 'notice', 'turn']
    key: str

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()


def message_record(store: Store, row) -> dict:
    message = decode_message(row['body'])
    cached = {item['image_index'] for item in store.message_media(message.scene, row['seq'])}
    images = []
    for segment in message.segments:
        if segment.type == 'image':
            index = len(images) + 1
            images.append({'index': index, 'summary': segment.data.get('summary'),
                           'url': (f'/api/host/scenes/{quote(message.scene, safe="")}/messages/{row["seq"]}/images/{index}'
                                   if index in cached else segment.data.get('url'))})
    replied = None if message.reply_to is None else store.find_message(message.scene, message.reply_to)
    return {'type': 'message', 'at': row['received_at'] if row['received_at'] is not None else message.time,
            'message_seq': row['seq'], 'platform_message_id': message.platform_message_id,
            'sender': message.sender, 'time': message.time, 'text': render_body(message.segments), 'images': images,
            'reply_to': message.reply_to,
            'reply': None if replied is None else {'platform_message_id': message.reply_to,
                                                  'sender': replied.sender, 'text': render_body(replied.segments)},
            'is_self': message.is_self, 'status': message.send_status, 'recalled': message.recalled,
            'verdict': None if row['wake_verdict'] is None else json.loads(row['wake_verdict'])}


def known_name(store: Store, scene: str, uid: str | None) -> str | None:
    """The group card or nickname this account last spoke with here."""
    if uid is None:
        return None
    row = store.db.execute(
        "SELECT COALESCE(NULLIF(json_extract(body,'$.sender.card'),''),json_extract(body,'$.sender.nickname')) "
        "FROM messages WHERE scene=? AND json_extract(body,'$.sender.uid')=? ORDER BY seq DESC LIMIT 1",
        (scene, uid)).fetchone()
    return None if row is None else row[0]


def notice_record(store: Store, row) -> dict:
    body = json.loads(row['body'])
    return {'type': 'notice', 'at': row['received_at'], 'id': row['id'], 'kind': row['kind'],
            'sub_type': body['sub_type'], 'time': row['time'],
            'user_id': body['user_id'], 'user_name': known_name(store, row['scene'], body['user_id']),
            'operator_id': body['operator_id'], 'operator_name': known_name(store, row['scene'], body['operator_id']),
            'duration': body['duration'], 'platform_message_id': row['platform_id'], 'raw': json.loads(row['raw'])}


def tool_results(store: Store, scene: str, entry: int | None) -> dict:
    if entry is None:
        return {}
    rows = store.db.execute(
        "SELECT seq,json_extract(message,'$.tool_call_id') AS call_id,json_extract(message,'$.content') AS content "
        "FROM mind_entries WHERE scene=? AND seq>? AND seq<COALESCE((SELECT MIN(seq) FROM mind_entries "
        "WHERE scene=? AND seq>? AND json_extract(message,'$.role')='assistant'),9223372036854775807) "
        "AND json_extract(message,'$.role')='tool' ORDER BY seq", (scene, entry, scene, entry)).fetchall()
    return {result['call_id']: dict(result) for result in rows}


def turn_record(store: Store, row) -> dict:
    calls = store.db.execute(
        "SELECT role,tokens,mind_entry_seq,json_extract(response,'$.message.tool_calls') AS tools "
        "FROM model_calls WHERE turn_id=? ORDER BY id",
        (row['id'],)).fetchall()
    tools = [tool['function']['name'] for call in calls for tool in ([] if call['tools'] is None else json.loads(call['tools']))]
    expressions = 0
    for call in calls:
        results = tool_results(store, row['scene'], call['mind_entry_seq'])
        for tool in [] if call['tools'] is None else json.loads(call['tools']):
            name = tool['function']['name']
            result = results.get(tool['id'])
            if (name in {'say', 'react', 'message_reaction'} and result is not None
                    and not result['content'].startswith((name + ' 失败：', name + ' 中断：'))):
                expressions += 1
    return {'type': 'turn', 'at': row['started'], 'turn_id': row['id'], 'status': row['status'],
            'channel': row['wake_channel'], 'started': row['started'], 'ended': row['ended'], 'error': row['error'],
            'steps': sum(call['role'] == 'mind' for call in calls),
            'expressions': expressions,
            'tokens': token_summary([None if call['tokens'] is None else json.loads(call['tokens']) for call in calls]),
            'tools': list(dict.fromkeys(tools)),
            'first_expression_wait': None if row['first_expression_at'] is None else
                row['first_expression_at'] - (row['started'] if row['wake_received_at'] is None else row['wake_received_at'])}


# At the same moment messages come first, then notices, then turns.
TIMELINE_SOURCES = (('message', 'messages', "COALESCE(received_at,json_extract(body,'$.time'))", 'seq'),
                    ('notice', 'notices', 'received_at', 'id'),
                    ('turn', 'turns', 'started', 'id'))
RANK = {kind: rank for rank, (kind, *_) in enumerate(TIMELINE_SOURCES)}
RECORDS = {'message': message_record, 'notice': notice_record, 'turn': turn_record}


def read_timeline(store: Store, scene: str, before: Cursor | None, limit: int) -> dict:
    rows = []
    for kind, table, clock, key in TIMELINE_SOURCES:
        condition, values = '', [scene]
        if before is not None:
            if kind == before.kind:
                condition = f' AND ({clock},{key})<(?,?)'
                values += [before.at, before.key if kind == 'turn' else int(before.key)]
            else:
                condition = f' AND {clock}' + ('<=?' if RANK[kind] < RANK[before.kind] else '<?')
                values += [before.at]
        found = store.db.execute(f'SELECT *,{clock} AS at FROM {table} WHERE scene=?{condition} '
                                 f'ORDER BY {clock} DESC,{key} DESC LIMIT ?', (*values, limit + 1)).fetchall()
        rows.extend((row['at'], RANK[kind], row[key], kind, row) for row in found)
    rows.sort(key=lambda item: item[:3], reverse=True)
    selected = rows[:limit]
    cursor = None
    if len(rows) > limit:
        at, _, key, kind, _ = selected[-1]
        cursor = Cursor(at=at, kind=kind, key=str(key)).encode()
    return {'scene': scene, 'next_before': cursor, 'items': [
        RECORDS[kind](store, row) for _, _, _, kind, row in reversed(selected)]}


def thoughts(call: dict) -> list[str]:
    response = call['response']
    if response is None or call['error'] is not None:
        return []
    message = response['message']
    parts = [message['reasoning_content']] if message.get('reasoning_content') else []
    raw = response.get('raw')
    if raw is None:
        return parts
    api = call['request']['settings']['api']
    if api == 'openai-responses':
        parts += [summary['text'] for item in raw['output'] if item['type'] == 'reasoning'
                  for summary in item.get('summary', []) if summary['type'] == 'summary_text']
    elif api == 'anthropic':
        parts += [item['thinking'] for item in raw['content'] if item['type'] == 'thinking']
    elif api == 'gemini':
        parts += [part['text'] for candidate in raw['candidates'] for part in candidate['content']['parts'] if part.get('thought')]
    return parts


def read_turn(store: Store, scene: str, turn_id: str) -> dict | None:
    detail = store.turn_detail(scene, turn_id)
    if detail is None:
        return None
    steps, recalled, seen, pending = [], [], set(), []
    recall_recorded = False
    for call in detail['calls']:
        recall_items = call['request'].get('recall_items')
        if recall_items is not None:
            recall_recorded = True
            for item in recall_items:
                identity = (item['scope'], item['path'], item['content'])
                if identity not in seen:
                    recalled.append(item)
                    seen.add(identity)
        model = {key: call[key] for key in ('id', 'role', 'started', 'ended', 'error', 'tokens', 'snapshot_expired_at')}
        if call['role'] != 'mind':
            if call['role'] == 'recap' or not steps:
                pending.append(model)
            else:
                steps[-1]['models'].append(model)
            continue
        response = call['response']
        step = {'step': len(steps) + 1, 'models': [*pending, model],
                'text': '' if response is None or call['error'] else response['message']['content'] or '',
                'thoughts': thoughts(call), 'tools': []}
        pending = []
        entry = store.db.execute('SELECT mind_entry_seq FROM model_calls WHERE id=?', (call['id'],)).fetchone()[0]
        results = tool_results(store, scene, entry)
        for tool in call['native_tool_calls']:
            function = tool['function']
            recorded = results.get(tool['id'])
            result = None if recorded is None else recorded['content']
            parts = []
            if recorded is not None:
                rows = store.db.execute(
                    'SELECT * FROM messages WHERE scene=? AND expression_entry_seq=? ORDER BY seq',
                    (scene, recorded['seq'])).fetchall()
                parts = [message_record(store, row) for row in rows]
            failed = (result is not None and result.startswith(function['name'] + ' 失败：')
                      or any(part['status'] in {'failed', 'unconfirmed'} for part in parts))
            interrupted = result is not None and result.startswith(function['name'] + ' 中断：')
            step['tools'].append({'call_id': tool['id'], 'name': function['name'],
                                  'arguments': json.loads(function['arguments']), 'result': result,
                                  'status': ('interrupted' if interrupted else 'error' if failed else
                                             'pending' if result is None else 'complete'), 'messages': parts})
        steps.append(step)
    if pending:
        steps.append({'step': len(steps) + 1, 'models': pending, 'text': '', 'thoughts': [], 'tools': []})
    return {**detail, 'recall': recalled if recall_recorded else None, 'steps': steps}


def register_host_timeline(app, *, runtime, user) -> None:
    def configured(scene):
        if scene not in runtime.chats:
            raise HTTPException(404, '当前宿主未配置此场景')

    @app.get('/api/host/scenes/{scene}/timeline', response_model=TimelinePage)
    async def timeline(scene: str, before: str | None = Query(None, max_length=256), limit: int = Query(50, ge=1, le=200),
                       _: str = Depends(user)):
        configured(scene)
        try:
            cursor = None if before is None else Cursor.model_validate_json(base64.urlsafe_b64decode(before))
            if cursor is not None and cursor.kind != 'turn':
                int(cursor.key)
        except ValueError as error:
            raise HTTPException(400, '时间线游标无效') from error
        def read():
            with Store(runtime.config.database, readonly=True) as records:
                return read_timeline(records, scene, cursor, limit)
        return await asyncio.to_thread(read)

    @app.get('/api/host/scenes/{scene}/turns/{turn_id}', response_model=TurnDetail)
    async def turn(scene: str, turn_id: str, _: str = Depends(user)):
        configured(scene)
        def read():
            with Store(runtime.config.database, readonly=True) as records:
                return read_turn(records, scene, turn_id)
        result = await asyncio.to_thread(read)
        if result is None:
            raise HTTPException(404, '当前场景不存在此回合')
        return result
