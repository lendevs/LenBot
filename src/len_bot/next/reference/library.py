"""The reference index: a role's knowledge files and each scene's files, searched by full text.

The index holds only what its sources give again, so when its schema differs from this version's the
tables are dropped and built anew from the sources. Each lookup first brings the owners it reads up to
date. Owners are ``persona:<id>``, visible in the scenes that use the role, and ``scene:<scene>``,
visible only in that scene. Without an instance directory the index lives in memory for one lookup
and holds only the role's knowledge.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack, closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Iterator, Literal, Protocol, TypeVar

from ..persona.knowledge import PersonaDocument
from ..storage.sqlite import connect
from .sources import MAX_FILE_BYTES, Extracted, chunks, extract, kind_of, scan, scene_directory

Scope = Literal["all", "persona", "chat"]
T = TypeVar("T")

SCHEMA = (
    """CREATE TABLE reference_sources (
        id INTEGER PRIMARY KEY,
        owner TEXT NOT NULL,
        path TEXT NOT NULL,
        kind TEXT NOT NULL,
        version TEXT NOT NULL,
        size INTEGER NOT NULL,
        modified_ns INTEGER NOT NULL,
        text TEXT NOT NULL,
        pages INTEGER,
        tags TEXT NOT NULL,
        error TEXT,
        indexed_at REAL NOT NULL,
        UNIQUE(owner, path)
    )""",
    """CREATE TABLE reference_chunks (
        id INTEGER PRIMARY KEY,
        source INTEGER NOT NULL REFERENCES reference_sources(id),
        heading TEXT NOT NULL,
        page INTEGER,
        start_char INTEGER NOT NULL,
        end_char INTEGER NOT NULL,
        folded TEXT NOT NULL
    )""",
    "CREATE INDEX reference_chunks_source ON reference_chunks(source)",
    """CREATE VIRTUAL TABLE reference_fts USING fts5(
        folded, content='reference_chunks', content_rowid='id', tokenize='trigram case_sensitive 1'
    )""",
    """CREATE TRIGGER reference_chunks_added AFTER INSERT ON reference_chunks BEGIN
        INSERT INTO reference_fts(rowid, folded) VALUES (new.id, new.folded);
    END""",
    """CREATE TRIGGER reference_chunks_removed AFTER DELETE ON reference_chunks BEGIN
        INSERT INTO reference_fts(reference_fts, rowid, folded) VALUES ('delete', old.id, old.folded);
    END""",
)
MAX_TERMS = 8


class KnowledgeOwner(Protocol):
    """The role whose knowledge files are read: its id and its loaded ``knowledge/`` snapshot."""
    id: str

    @property
    def knowledge(self) -> Mapping[str, PersonaDocument]: ...


@dataclass(frozen=True, slots=True)
class ReferenceFile:
    owner: str
    path: str
    kind: str
    chars: int
    pages: int | None
    tags: tuple[str, ...]
    error: str | None


@dataclass(frozen=True, slots=True)
class ReferenceHit:
    owner: str
    path: str
    heading: tuple[str, ...]
    page: int | None
    start_char: int
    text: str
    matched: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReferencePage:
    owner: str
    path: str
    kind: str
    offset: int
    total_chars: int
    next_offset: int | None
    text: str


@dataclass(frozen=True, slots=True)
class _Change:
    path: str
    version: str
    size: int
    modified_ns: int
    extracted: Extracted | None = None
    error: str | None = None
    # The same content under a new file time: only the recorded size and time change.
    touch: bool = False


def _create(db: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        db.execute(statement)
    db.execute("INSERT INTO reference_fts(reference_fts, rank) VALUES('secure-delete', 1)")


def _schema(db: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    return sorted(tuple(row) for row in db.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))


with closing(sqlite3.connect(":memory:")) as _expected:
    _create(_expected)
    EXPECTED_SCHEMA = _schema(_expected)


def search_terms(query: str) -> tuple[str, ...]:
    """Whitespace-separated keywords, case-folded, at most ``MAX_TERMS``."""
    terms = tuple(dict.fromkeys(query.casefold().split()))[:MAX_TERMS]
    if not terms:
        raise ValueError("query must contain a keyword")
    return terms


def _version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReferenceLibrary:
    def __init__(self, root: Path | None):
        self.root = root
        self.index = None if root is None else root / "state" / "reference" / "index.sqlite3"
        self._ready = False
        self._prepare_lock = threading.Lock()
        self._locks: dict[str, asyncio.Lock] = {}

    def directory(self, scene: str) -> Path | None:
        return scene_directory(self.root, scene)

    @staticmethod
    def owners(scene: str, persona_id: str, scope: Scope) -> list[str]:
        owners = []
        if scope in {"all", "persona"}:
            owners.append(f"persona:{persona_id}")
        if scope in {"all", "chat"}:
            owners.append(f"scene:{scene}")
        return owners

    def _prepare(self) -> None:
        with self._prepare_lock:
            if self._ready:
                return
            self.index.parent.mkdir(parents=True, exist_ok=True)
            if self.index.is_symlink():
                raise ValueError(f"reference index must not be a symlink: {self.index}")
            with closing(connect(self.index)) as db:
                # Tables of an earlier schema are dropped without their row constraints.
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute("BEGIN IMMEDIATE")
                current = _schema(db)
                if current != EXPECTED_SCHEMA:
                    # Dropping the full-text table also drops its own tables; triggers and indexes go with theirs.
                    for kind, name, _ in current:
                        if kind == "table":
                            db.execute(f'DROP TABLE IF EXISTS "{name}"')
                    _create(db)
                db.commit()
            self._ready = True

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        if self.index is None:
            db = sqlite3.connect(":memory:")
            _create(db)
        else:
            self._prepare()
            db = connect(self.index)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _known(self, owners: list[str]) -> dict[str, dict[str, tuple[int, int, str]]]:
        known: dict[str, dict[str, tuple[int, int, str]]] = {owner: {} for owner in owners}
        if self.index is None:
            return known
        with self._db() as db:
            for owner in owners:
                for row in db.execute("SELECT path, size, modified_ns, version FROM reference_sources WHERE owner=?",
                                      (owner,)):
                    known[owner][row["path"]] = (row["size"], row["modified_ns"], row["version"])
        return known

    @staticmethod
    def _persona_changes(persona: KnowledgeOwner, known: dict[str, tuple[int, int, str]]) -> tuple[list[_Change], set[str]]:
        changes = []
        for path, document in persona.knowledge.items():
            data = document.content.encode("utf-8")
            version = _version(data)
            if path in known and known[path][2] == version:
                continue
            changes.append(_Change(path, version, len(data), 0,
                                   Extracted("markdown", document.content, tags=tuple(document.tags))))
        return changes, set(known) - set(persona.knowledge)

    async def _scene_changes(self, scene: str, known: dict[str, tuple[int, int, str]]) -> tuple[list[_Change], set[str]]:
        found = await asyncio.to_thread(scan, self.directory(scene))
        changes = []
        for path, item in found.items():
            before = known.get(path)
            if before is not None and before[:2] == (item.size, item.modified_ns):
                continue
            if item.size > MAX_FILE_BYTES:
                changes.append(_Change(path, "", item.size, item.modified_ns,
                                       error=f"文件超过 {MAX_FILE_BYTES // 1_000_000}MB 上限"))
                continue
            try:
                data = await asyncio.to_thread(item.file.read_bytes)
            except OSError as error:
                changes.append(_Change(path, "", item.size, item.modified_ns, error=f"无法读取：{error}"))
                continue
            version = _version(data)
            if before is not None and before[2] == version:
                changes.append(_Change(path, version, item.size, item.modified_ns, touch=True))
                continue
            try:
                changes.append(_Change(path, version, item.size, item.modified_ns, await extract(path, data)))
            except ValueError as error:
                changes.append(_Change(path, version, item.size, item.modified_ns, error=str(error)))
        return changes, set(known) - set(found)

    @staticmethod
    def _remove(db: sqlite3.Connection, owner: str, path: str) -> None:
        row = db.execute("SELECT id FROM reference_sources WHERE owner=? AND path=?", (owner, path)).fetchone()
        if row is not None:
            db.execute("DELETE FROM reference_chunks WHERE source=?", (row["id"],))
            db.execute("DELETE FROM reference_sources WHERE id=?", (row["id"],))

    def _apply(self, db: sqlite3.Connection, owner: str, changes: list[_Change], removed: set[str]) -> None:
        for path in sorted(removed):
            self._remove(db, owner, path)
        for change in changes:
            if change.touch:
                db.execute("UPDATE reference_sources SET size=?, modified_ns=? WHERE owner=? AND path=?",
                           (change.size, change.modified_ns, owner, change.path))
                continue
            self._remove(db, owner, change.path)
            extracted = change.extracted
            source = db.execute(
                "INSERT INTO reference_sources(owner, path, kind, version, size, modified_ns, text, pages, tags,"
                " error, indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (owner, change.path, kind_of(change.path), change.version, change.size, change.modified_ns,
                 "" if extracted is None else extracted.text,
                 len(extracted.pages) if extracted is not None and extracted.kind == "pdf" else None,
                 json.dumps([] if extracted is None else list(extracted.tags), ensure_ascii=False),
                 change.error, time.time())).lastrowid
            if extracted is None:
                continue
            for chunk in chunks(extracted):
                body = extracted.text[chunk.start_char:chunk.end_char]
                db.execute("INSERT INTO reference_chunks(source, heading, page, start_char, end_char, folded)"
                           " VALUES (?,?,?,?,?,?)",
                           (source, json.dumps(chunk.heading, ensure_ascii=False), chunk.page, chunk.start_char,
                            chunk.end_char, "\n".join((change.path, *chunk.heading, body)).casefold()))

    async def _run(self, scene: str, persona: KnowledgeOwner, scope: Scope,
                   operation: Callable[[sqlite3.Connection, list[str]], T]) -> T:
        owners = self.owners(scene, persona.id, scope)
        async with AsyncExitStack() as stack:
            for owner in sorted(owners):
                await stack.enter_async_context(self._locks.setdefault(owner, asyncio.Lock()))
            known = await asyncio.to_thread(self._known, owners)
            plans = {owner: (self._persona_changes(persona, known[owner]) if owner.startswith("persona:")
                             else await self._scene_changes(scene, known[owner])) for owner in owners}

            def run() -> T:
                with self._db() as db:
                    for owner, (changes, removed) in plans.items():
                        self._apply(db, owner, changes, removed)
                    return operation(db, owners)

            return await asyncio.to_thread(run)

    async def files(self, scene: str, persona: KnowledgeOwner, scope: Scope = "all") -> list[ReferenceFile]:
        def listing(db: sqlite3.Connection, owners: list[str]) -> list[ReferenceFile]:
            rows = db.execute(f"""SELECT owner, path, kind, length(text) AS chars, pages, tags, error
                FROM reference_sources WHERE owner IN ({",".join("?" for _ in owners)})""", owners).fetchall()
            return [ReferenceFile(row["owner"], row["path"], row["kind"], row["chars"], row["pages"],
                                  tuple(json.loads(row["tags"])), row["error"])
                    for row in sorted(rows, key=lambda row: (owners.index(row["owner"]), row["path"]))]
        return await self._run(scene, persona, scope, listing)

    async def search(self, scene: str, persona: KnowledgeOwner, query: str, *, scope: Scope = "all",
                     limit: int = 50) -> list[ReferenceHit]:
        """Chunks holding at least half of the keywords, most keywords first, then full-text rank."""
        terms = search_terms(query)
        return await self._run(scene, persona, scope, lambda db, owners: self._search(db, owners, terms, limit))

    @staticmethod
    def _search(db: sqlite3.Connection, owners: list[str], terms: tuple[str, ...], limit: int) -> list[ReferenceHit]:
        placeholders = ",".join("?" for _ in owners)
        long_terms = [term for term in terms if len(term) >= 3]
        short_terms = [term for term in terms if len(term) < 3]
        parts, parameters = [], []
        if long_terms:
            parts.append(f"""SELECT c.id, reference_fts.rank
                FROM reference_fts JOIN reference_chunks AS c ON c.id = reference_fts.rowid
                JOIN reference_sources AS s ON s.id = c.source
                WHERE reference_fts MATCH ? AND s.owner IN ({placeholders})""")
            parameters += [" OR ".join('"' + term.replace('"', '""') + '"' for term in long_terms), *owners]
        if short_terms:
            # The trigram index cannot hold one- or two-character keywords.
            parts.append(f"""SELECT c.id, 0.0 FROM reference_chunks AS c JOIN reference_sources AS s ON s.id = c.source
                WHERE s.owner IN ({placeholders}) AND ({" OR ".join("instr(c.folded, ?) > 0" for _ in short_terms)})""")
            parameters += [*owners, *short_terms]
        matched = " + ".join("(instr(c.folded, ?) > 0)" for _ in terms)
        rows = db.execute(f"""
            WITH hits(id, relevance) AS MATERIALIZED ({" UNION ALL ".join(parts)})
            SELECT s.owner, s.path, c.heading, c.page, c.start_char, c.folded,
                   substr(s.text, c.start_char + 1, c.end_char - c.start_char) AS body,
                   {matched} AS matched, MIN(hits.relevance) AS relevance
            FROM hits JOIN reference_chunks AS c ON c.id = hits.id JOIN reference_sources AS s ON s.id = c.source
            GROUP BY c.id HAVING matched >= ?
            ORDER BY matched DESC, relevance, s.owner, s.path, c.start_char LIMIT ?
        """, (*parameters, *terms, (len(terms) + 1) // 2, limit)).fetchall()
        return [ReferenceHit(row["owner"], row["path"], tuple(json.loads(row["heading"])), row["page"],
                             row["start_char"], row["body"], tuple(term for term in terms if term in row["folded"]))
                for row in rows]

    async def read(self, scene: str, persona: KnowledgeOwner, scope: Literal["persona", "chat"], path: str,
                   offset: int = 0, length: int = 4000) -> ReferencePage:
        def page(db: sqlite3.Connection, owners: list[str]) -> ReferencePage:
            [owner] = owners
            row = db.execute("SELECT kind, text, error FROM reference_sources WHERE owner=? AND path=?",
                             (owner, path)).fetchone()
            if row is None:
                raise ValueError(f"{scope} 范围没有资料文件 {path!r}")
            if row["error"] is not None:
                raise ValueError(f"{path} 没有建立索引：{row['error']}")
            text = row["text"]
            if offset > len(text):
                raise ValueError(f"offset {offset} exceeds {path!r} length {len(text)}")
            end = min(offset + length, len(text))
            return ReferencePage(owner, path, row["kind"], offset, len(text),
                                 end if end < len(text) else None, text[offset:end])
        return await self._run(scene, persona, scope, page)
