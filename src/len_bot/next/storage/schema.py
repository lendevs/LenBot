"""Create the current database from domain-owned schemas in one transaction."""

from collections.abc import Iterable
from contextlib import closing
from functools import cache
from pathlib import Path
import sqlite3

# Until the first release candidate a format change comes without an upgrade step.
FORMAT_RESET = '发布前的格式变更不提供升级步骤，请使用新的实例目录重新配置，旧目录可保留作备份。'


SCHEMA = """
CREATE TABLE messages (
    seq INTEGER PRIMARY KEY, scene TEXT NOT NULL,
    platform_id TEXT, body TEXT NOT NULL, raw TEXT,
    received_at REAL, persona_id TEXT, wake_verdict TEXT, expression_entry_seq INTEGER
);
CREATE UNIQUE INDEX platform_messages ON messages(scene, platform_id)
    WHERE platform_id IS NOT NULL;
CREATE INDEX expression_messages ON messages(expression_entry_seq,seq) WHERE expression_entry_seq IS NOT NULL;
CREATE VIRTUAL TABLE message_search USING fts5(
    search_text, tokenize='trigram case_sensitive 1'
);
CREATE TABLE notices (
    id INTEGER PRIMARY KEY, scene TEXT NOT NULL, kind TEXT NOT NULL,
    platform_id TEXT, time REAL NOT NULL, received_at REAL NOT NULL, raw TEXT NOT NULL, body TEXT NOT NULL
);
CREATE INDEX scene_notices ON notices(scene,id);
CREATE INDEX recalled_messages ON notices(scene,platform_id)
    WHERE kind IN ('group_recall','friend_recall');
CREATE TABLE mind_entries (
    seq INTEGER PRIMARY KEY, scene TEXT NOT NULL,
    message TEXT NOT NULL, created REAL NOT NULL
);
CREATE INDEX scene_entries ON mind_entries(scene, seq);
CREATE TABLE mind_sessions (
    scene TEXT PRIMARY KEY,
    compact_through INTEGER NOT NULL DEFAULT 0,
    recap TEXT,
    last_message_seq INTEGER NOT NULL DEFAULT 0,
    attention_state TEXT,
    discovered_tools TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE speech (
    id INTEGER PRIMARY KEY, scene TEXT NOT NULL, time REAL NOT NULL
);
CREATE INDEX scene_speech ON speech(scene, time);
CREATE TABLE turns (
    id TEXT PRIMARY KEY, scene TEXT NOT NULL, started REAL NOT NULL,
    ended REAL, status TEXT NOT NULL, error TEXT,
    wake_received_at REAL, first_expression_at REAL, first_expression_delivery TEXT,
    wake_channel TEXT NOT NULL DEFAULT 'unknown'
);
CREATE TABLE model_calls (
    id INTEGER PRIMARY KEY, turn_id TEXT, role TEXT NOT NULL,
    started REAL NOT NULL, ended REAL, request TEXT NOT NULL,
    response TEXT, usage TEXT, error TEXT, mind_entry_seq INTEGER, tokens TEXT,
    scene TEXT NOT NULL, plugin TEXT, retries INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX turn_calls ON model_calls(turn_id, id);
CREATE TABLE web_documents (
    id INTEGER PRIMARY KEY, scene TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE image_cache (
    scene TEXT NOT NULL, platform_id TEXT NOT NULL,
    image_index INTEGER NOT NULL, jpeg BLOB NOT NULL,
    width INTEGER NOT NULL, height INTEGER NOT NULL,
    animated INTEGER NOT NULL, fetched_at REAL NOT NULL,
    description TEXT, description_model TEXT, described_at REAL,
    PRIMARY KEY(scene, platform_id, image_index)
);
CREATE TABLE media (
    id INTEGER PRIMARY KEY, persona_id TEXT, file TEXT,
    source_message_seq INTEGER, source_image_index INTEGER,
    mime_type TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
    animated INTEGER NOT NULL, data BLOB NOT NULL,
    CHECK ((persona_id IS NOT NULL AND file IS NOT NULL AND
            source_message_seq IS NULL AND source_image_index IS NULL) OR
           (persona_id IS NULL AND file IS NULL AND
            source_message_seq IS NOT NULL AND source_image_index IS NOT NULL)),
    UNIQUE(source_message_seq,source_image_index)
);
CREATE INDEX media_persona_file ON media(persona_id,file,id);
CREATE TABLE message_media (
    message_seq INTEGER NOT NULL, image_index INTEGER NOT NULL,
    media_id INTEGER NOT NULL, description TEXT NOT NULL,
    emotions TEXT NOT NULL, tags TEXT NOT NULL,
    PRIMARY KEY(message_seq,image_index)
);
CREATE INDEX message_media_media ON message_media(media_id,message_seq);
CREATE INDEX message_send_window ON messages(scene,json_extract(body,'$.time'))
    WHERE json_extract(body,'$.is_self')=1;
CREATE INDEX message_retention ON messages(scene,COALESCE(received_at,json_extract(body,'$.time')),seq);
CREATE INDEX model_call_usage ON model_calls(started,scene,role,plugin,ended,tokens,error);
CREATE INDEX message_overview ON messages(scene,
    CASE WHEN raw IS NULL THEN json_extract(body,'$.time') ELSE received_at END,
    json_extract(body,'$.send_status'),raw IS NULL);
CREATE INDEX message_failed_sends ON messages(scene,json_extract(body,'$.time'),json_extract(body,'$.send_status'))
    WHERE raw IS NULL AND json_extract(body,'$.send_status') IN ('failed','unconfirmed');
CREATE INDEX model_call_expiry ON model_calls(ended,id);
CREATE INDEX turns_scene_time ON turns(scene,started);
CREATE INDEX turns_expiry ON turns(ended,id);
"""


def business_script() -> str:
    """Every statement that creates the business database, without its format markers."""
    from ..media.audio_store import SCHEMA as AUDIO
    from ..learning.jargon_store import SCHEMA as JARGON
    from ..learning.store import SCHEMA as LEARNING
    from ..plugins.store import SCHEMA as PLUGINS
    from ..chat.proactive import SCHEMA as PROACTIVE
    from ..learning.reply_effect_store import SCHEMA as REPLY_EFFECTS
    from ..chat.schedule_store import SCHEMA as SCHEDULES
    from ..learning.sticker_store import SCHEMA as STICKERS
    from ..work.store import SCHEMA as TASKS
    from ..models.usage import SCHEMA as USAGE

    domains = (SCHEMA, SCHEDULES, TASKS, AUDIO, LEARNING, JARGON, STICKERS,
               REPLY_EFFECTS, PROACTIVE, PLUGINS, USAGE)
    return "\n".join(domains)


def create_database(db: sqlite3.Connection, version: int) -> None:
    db.executescript(f"BEGIN; PRAGMA application_id = 1279413809; PRAGMA user_version = {version};\n"
                     + business_script() + "\nCOMMIT;")


@cache
def expected_tables() -> frozenset[str]:
    """Names of the tables a database of the current format holds."""
    return frozenset(script_columns(business_script()))


Column = tuple[str, str, int, str | None]


def stored_state(path: Path) -> tuple[int, int, frozenset[str]] | None:
    """``application_id``, ``user_version`` and table names of an existing non-empty file.

    The file is opened read-only, so a file about to be refused stays exactly as it was; a missing
    or empty file has no state.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        tables = frozenset(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        return db.execute('PRAGMA application_id').fetchone()[0], db.execute('PRAGMA user_version').fetchone()[0], tables


def table_columns(db: sqlite3.Connection, tables: Iterable[str]) -> dict[str, frozenset[Column]]:
    """Per table the set of (name, type, not null, default); the order of columns is not part of it."""
    return {table: frozenset((row[1], row[2], row[3], row[4]) for row in db.execute(f'PRAGMA table_info("{table}")'))
            for table in tables}


@cache
def script_columns(script: str) -> dict[str, frozenset[Column]]:
    """The columns of every table a schema script creates."""
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(script)
        return table_columns(db, [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")])


def _describe(column: Column) -> str:
    name, kind, not_null, default = column
    return ' '.join(part for part in (name, kind, 'NOT NULL' if not_null else '',
                                      '' if default is None else f'DEFAULT {default}') if part)


def column_differences(db: sqlite3.Connection, script: str) -> list[str]:
    """Tables of the current schema that are missing or whose column sets differ, with the columns."""
    expected = script_columns(script)
    actual = table_columns(db, [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                                if row[0] in expected])
    problems = []
    for table in sorted(expected):
        if table not in actual:
            problems.append(f'{table}（缺少这张表）')
            continue
        if actual[table] == expected[table]:
            continue
        want = {column[0]: column for column in expected[table]}
        have = {column[0]: column for column in actual[table]}
        details = []
        if missing := sorted(want.keys() - have.keys()):
            details.append('缺少列 ' + '、'.join(missing))
        if extra := sorted(have.keys() - want.keys()):
            details.append('多出列 ' + '、'.join(extra))
        details.extend(f'列 {name} 为 {_describe(have[name])}，应为 {_describe(want[name])}'
                       for name in sorted(want.keys() & have.keys()) if want[name] != have[name])
        problems.append(f'{table}（{"；".join(details)}）')
    return problems


def require_columns(db: sqlite3.Connection, script: str, *, path: Path, label: str, version: int) -> None:
    """Refuse a database whose tables differ from the current schema in their column sets."""
    if problems := column_differences(db, script):
        raise ValueError(f'{path} 的{label}表结构与格式 {version} 不一致：{"；".join(problems)}。{FORMAT_RESET}')
