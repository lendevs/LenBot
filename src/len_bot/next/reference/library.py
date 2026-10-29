"""The reference index: a role's knowledge files and each scene's files, searched by full text and,
with an embeddings connection, by vectors as well.

The index holds only what its sources give again, so when its schema differs from this version's the
tables are dropped and built anew from the sources. Each lookup first brings the owners it reads up to
date. Owners are ``persona:<id>``, visible in the scenes that use the role, and ``scene:<scene>``,
visible only in that scene. Without an instance directory the index lives in memory for one lookup,
holds only the role's knowledge and uses no vectors.

Vectors are added lazily, at most ``EMBED_PER_LOOKUP`` chunks per lookup; chunks without one are still
found by full text. A failed embeddings request leaves that lookup on full text. A library without
an embeddings connection adds no vectors and keeps the existing ones in step with deleted chunks.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, closing, contextmanager, nullcontext
from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import TYPE_CHECKING, Iterator, Literal, Protocol, TypeVar
from uuid import uuid4

from ..memory.embeddings import EmbeddingBatch
from ..models.tokens import token_record
from ..models.usage import record_usage
from ..persona.knowledge import PersonaDocument
from ..runtime.logs import log_event
from ..storage.sqlite import connect
from .sources import MAX_FILE_BYTES, Chunk, Extracted, chunks, extract, kind_of, scan, scene_directory

if TYPE_CHECKING:
    from ..memory.embeddings import EmbeddingClient
    from ..memory.service import MemoryService
    from ..models.slots import ModelSlots
    from ..storage.store import Store

logger = logging.getLogger(__name__)
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
    # Files the chat may have read before they changed; each scene is told once (reference_notices).
    """CREATE TABLE reference_changes (
        id INTEGER PRIMARY KEY,
        owner TEXT NOT NULL,
        path TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('updated', 'removed')),
        at REAL NOT NULL
    )""",
    """CREATE TABLE reference_notices (
        scene TEXT PRIMARY KEY,
        through INTEGER NOT NULL
    )""",
    """CREATE TABLE reference_embedding_binding (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        provider TEXT NOT NULL,
        base_url TEXT NOT NULL,
        model TEXT NOT NULL,
        dimensions INTEGER NOT NULL CHECK(dimensions > 0)
    )""",
)
MAX_TERMS = 8
EMBED_PER_LOOKUP = 200
EMBED_BATCH = 100
# Nearest chunks asked per owner; at most VECTOR_ONLY of those without a full-text hit are returned,
# and none farther than MAX_VECTOR_DISTANCE. Answerable and unanswerable questions overlap in
# distance, so only clearly unrelated neighbours are cut.
VECTOR_NEIGHBOURS = 10
VECTOR_ONLY = 3
MAX_VECTOR_DISTANCE = 0.6
# A neighbour without a full-text hit is also kept only this close to the nearest one.
VECTOR_MARGIN = 0.03


class KnowledgeOwner(Protocol):
    """The role whose knowledge files are read: its id and its loaded ``knowledge/`` snapshot."""
    id: str

    @property
    def knowledge(self) -> Mapping[str, PersonaDocument]: ...


@dataclass(frozen=True, slots=True)
class ReferenceEmbedding:
    """The embeddings connection of ``memory.local.embedding``; ``embed`` requests one batch for a scene."""
    provider: str
    base_url: str
    model: str
    dimensions: int | None
    embed: Callable[[str, list[str]], Awaitable[EmbeddingBatch]]


def reference_embedding(client: EmbeddingClient, store: Store, slots: ModelSlots | None) -> ReferenceEmbedding:
    """Requests share the model slots and are recorded in the usage ledger as ``reference_embedding``."""
    settings = client.settings

    async def embed(scene: str, texts: list[str]) -> EmbeddingBatch:
        async with (nullcontext() if slots is None else slots.slot(scene=scene)):
            started = store.now()
            batch = await client.embed(texts)
            with store.db:
                record_usage(store.db, time=started, scene=scene, purpose="reference_embedding",
                             provider=settings.provider, model=settings.model, tokens=token_record(batch.token_usage))
            return batch

    return ReferenceEmbedding(settings.provider, settings.base_url, settings.model, settings.dimensions, embed)


def open_library(root: Path | None, memory: MemoryService | None, store: Store,
                 slots: ModelSlots | None) -> ReferenceLibrary:
    """The instance's library, with vectors when ``memory.local.embedding`` is configured."""
    client = None if memory is None else memory.backend.embedding
    return ReferenceLibrary(root, embedding=None if client is None else reference_embedding(client, store, slots))


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
class ReferenceFileState:
    """A file of a scene's directory as the panel shows it; ``processing`` until the index has it as it is now."""
    path: str
    kind: str
    size: int
    modified: float
    status: Literal["processing", "indexed", "failed"]
    error: str | None
    chars: int | None
    pages: int | None
    chunks: int
    vectors: int


@dataclass(frozen=True, slots=True)
class ReferenceChange:
    owner: str
    path: str
    action: Literal["updated", "removed"]
    at: float


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
    pieces: tuple[Chunk, ...] = field(default=())


@dataclass(slots=True)
class _Vectors:
    dimensions: int | None = None
    # New chunks by (owner, path, position in the file); existing chunks by row id.
    added: dict[tuple[str, str, int], tuple[float, ...]] = field(default_factory=dict)
    missing: dict[int, tuple[float, ...]] = field(default_factory=dict)
    query: tuple[float, ...] | None = None
    # Whether this lookup asked for as many chunk vectors as one lookup may.
    full: bool = False


def _create(db: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        db.execute(statement)
    db.execute("INSERT INTO reference_fts(reference_fts, rank) VALUES('secure-delete', 1)")


def _vector_table(name: str) -> bool:
    return name == "reference_vec" or name.startswith("reference_vec_")


def _schema(db: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    return sorted(tuple(row) for row in db.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'") if not _vector_table(row[1]))


with closing(sqlite3.connect(":memory:")) as _expected:
    _create(_expected)
    EXPECTED_SCHEMA = _schema(_expected)


def _has_vectors(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='reference_vec'").fetchone() is not None


def _load_vec(db: sqlite3.Connection) -> None:
    import sqlite_vec

    db.enable_load_extension(True)
    try:
        sqlite_vec.load(db)
    finally:
        db.enable_load_extension(False)


def _vector_bytes(vector: tuple[float, ...]) -> bytes:
    from sqlite_vec import serialize_float32

    return serialize_float32(list(vector))


def search_terms(query: str) -> tuple[str, ...]:
    """Whitespace-separated keywords, case-folded, at most ``MAX_TERMS``."""
    terms = tuple(dict.fromkeys(query.casefold().split()))[:MAX_TERMS]
    if not terms:
        raise ValueError("query must contain a keyword")
    return terms


def _version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _embedding_text(path: str, heading: tuple[str, ...], body: str) -> str:
    return "\n".join((path, *heading, body))


def _changed(path: str, version: str, size: int, modified_ns: int, extracted: Extracted) -> _Change:
    return _Change(path, version, size, modified_ns, extracted, pieces=tuple(chunks(extracted)))


class ReferenceLibrary:
    def __init__(self, root: Path | None, *, embedding: ReferenceEmbedding | None = None):
        self.root = root
        self.index = None if root is None else root / "state" / "reference" / "index.sqlite3"
        self.embedding = None if root is None else embedding
        self._ready = False
        self._prepare_lock = threading.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._jobs: dict[str, asyncio.Task] = {}
        self._again: set[str] = set()

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

    def _binding_matches(self, db: sqlite3.Connection) -> bool:
        row = db.execute("SELECT base_url, model, dimensions FROM reference_embedding_binding").fetchone()
        embedding = self.embedding
        return row is not None and (row[0], row[1]) == (embedding.base_url, embedding.model) and (
            embedding.dimensions is None or row[2] == embedding.dimensions)

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
                vectors = _has_vectors(db)
                if vectors:
                    _load_vec(db)
                current = _schema(db)
                if current != EXPECTED_SCHEMA:
                    if vectors:
                        db.execute("DROP TABLE reference_vec")
                    # Dropping the full-text table also drops its own tables; triggers and indexes go with theirs.
                    for kind, name, _ in current:
                        if kind == "table":
                            db.execute(f'DROP TABLE IF EXISTS "{name}"')
                    _create(db)
                elif vectors and self.embedding is not None and not self._binding_matches(db):
                    db.execute("DROP TABLE reference_vec")
                    db.execute("DELETE FROM reference_embedding_binding")
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
            if self.embedding is not None or _has_vectors(db):
                _load_vec(db)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _known(self, owners: list[str]) -> tuple[dict[str, dict[str, tuple[int, int, str]]], int | None]:
        """Recorded files of each owner, and the vector dimensions when vectors exist."""
        known: dict[str, dict[str, tuple[int, int, str]]] = {owner: {} for owner in owners}
        if self.index is None:
            return known, None
        with self._db() as db:
            for owner in owners:
                for row in db.execute("SELECT path, size, modified_ns, version FROM reference_sources WHERE owner=?",
                                      (owner,)):
                    known[owner][row["path"]] = (row["size"], row["modified_ns"], row["version"])
            row = db.execute("SELECT dimensions FROM reference_embedding_binding").fetchone()
            return known, None if row is None or not _has_vectors(db) else row[0]

    @staticmethod
    def _persona_changes(persona: KnowledgeOwner, known: dict[str, tuple[int, int, str]]) -> tuple[list[_Change], set[str]]:
        changes = []
        for path, document in persona.knowledge.items():
            data = document.content.encode("utf-8")
            version = _version(data)
            if path in known and known[path][2] == version:
                continue
            changes.append(_changed(path, version, len(data), 0,
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
                changes.append(_changed(path, version, item.size, item.modified_ns, await extract(path, data)))
            except ValueError as error:
                changes.append(_Change(path, version, item.size, item.modified_ns, error=str(error)))
        return changes, set(known) - set(found)

    def _missing(self, owners: list[str], limit: int, replaced: set[tuple[str, str]]) -> list[tuple[int, str]]:
        """Existing chunks without a vector, outside the files this lookup replaces."""
        conditions, parameters = "", [*owners]
        if replaced:
            conditions += f" AND (s.owner, s.path) NOT IN (VALUES {','.join('(?, ?)' for _ in replaced)})"
            parameters += [part for pair in sorted(replaced) for part in pair]
        with self._db() as db:
            if _has_vectors(db):
                conditions += " AND c.id NOT IN (SELECT rowid FROM reference_vec)"
            rows = db.execute(f"""
                SELECT c.id, s.path, c.heading, substr(s.text, c.start_char + 1, c.end_char - c.start_char) AS body
                FROM reference_chunks AS c JOIN reference_sources AS s ON s.id = c.source
                WHERE s.owner IN ({",".join("?" for _ in owners)}){conditions} ORDER BY c.id LIMIT ?
            """, (*parameters, limit)).fetchall()
        return [(row["id"], _embedding_text(row["path"], tuple(json.loads(row["heading"])), row["body"]))
                for row in rows]

    async def _vectors(self, scene: str, plans: dict[str, tuple[list[_Change], set[str]]],
                       dimensions: int | None, query: str | None) -> _Vectors:
        vectors = _Vectors(dimensions)
        if self.embedding is None:
            return vectors
        pending: list[tuple[tuple[str, str, int] | int, str]] = []
        for owner, (changes, _) in plans.items():
            for change in changes:
                for position, piece in enumerate(change.pieces):
                    body = change.extracted.text[piece.start_char:piece.end_char]
                    pending.append(((owner, change.path, position), _embedding_text(change.path, piece.heading, body)))
        pending = pending[:EMBED_PER_LOOKUP]
        vectors.full = len(pending) == EMBED_PER_LOOKUP
        if len(pending) < EMBED_PER_LOOKUP:
            replaced = {(owner, path) for owner, (changes, removed) in plans.items()
                        for path in {change.path for change in changes} | removed}
            pending += await asyncio.to_thread(self._missing, list(plans), EMBED_PER_LOOKUP - len(pending), replaced)
            vectors.full = len(pending) == EMBED_PER_LOOKUP
        try:
            for offset in range(0, len(pending), EMBED_BATCH):
                part = pending[offset:offset + EMBED_BATCH]
                batch = await self.embedding.embed(scene, [text for _, text in part])
                self._check_dimensions(vectors, batch.dimensions)
                for (key, _), vector in zip(part, batch.vectors):
                    if isinstance(key, int):
                        vectors.missing[key] = vector
                    else:
                        vectors.added[key] = vector
            if query is not None and vectors.dimensions is not None:
                batch = await self.embedding.embed(scene, [query])
                self._check_dimensions(vectors, batch.dimensions)
                vectors.query = batch.vectors[0]
        except (ValueError, TimeoutError) as error:
            # This lookup stays on full text; the chunks get their vectors on a later lookup.
            log_event(logger, "reference_text_retrieval", "资料改用全文检索", level=logging.WARNING,
                      scene=scene, error=error)
            return _Vectors(dimensions)
        return vectors

    @staticmethod
    def _check_dimensions(vectors: _Vectors, dimensions: int) -> None:
        if vectors.dimensions is not None and dimensions != vectors.dimensions:
            raise ValueError(f"embedding dimensions {dimensions} differ from reference index {vectors.dimensions}")
        vectors.dimensions = dimensions

    def _ensure_vectors(self, db: sqlite3.Connection, dimensions: int) -> None:
        if _has_vectors(db):
            return
        db.execute(f"CREATE VIRTUAL TABLE reference_vec USING vec0("
                   f"embedding float[{dimensions}] distance_metric=cosine, owner text)")
        db.execute("DELETE FROM reference_embedding_binding")
        db.execute("INSERT INTO reference_embedding_binding(id, provider, base_url, model, dimensions) VALUES (1,?,?,?,?)",
                   (self.embedding.provider, self.embedding.base_url, self.embedding.model, dimensions))

    @staticmethod
    def _remove(db: sqlite3.Connection, owner: str, path: str) -> bool:
        """Drop a file from the index; whether the chat could find it before."""
        row = db.execute("SELECT id, error FROM reference_sources WHERE owner=? AND path=?", (owner, path)).fetchone()
        if row is None:
            return False
        if _has_vectors(db):
            db.execute("DELETE FROM reference_vec WHERE rowid IN (SELECT id FROM reference_chunks WHERE source=?)",
                       (row["id"],))
        db.execute("DELETE FROM reference_chunks WHERE source=?", (row["id"],))
        db.execute("DELETE FROM reference_sources WHERE id=?", (row["id"],))
        return row["error"] is None

    @staticmethod
    def _log(db: sqlite3.Connection, owner: str, path: str, action: str) -> None:
        db.execute("INSERT INTO reference_changes(owner, path, action, at) VALUES (?,?,?,?)",
                   (owner, path, action, time.time()))

    def _apply(self, db: sqlite3.Connection, owner: str, changes: list[_Change], removed: set[str],
               vectors: _Vectors) -> None:
        for path in sorted(removed):
            if self._remove(db, owner, path):
                self._log(db, owner, path, "removed")
        for change in changes:
            if change.touch:
                db.execute("UPDATE reference_sources SET size=?, modified_ns=? WHERE owner=? AND path=?",
                           (change.size, change.modified_ns, owner, change.path))
                continue
            extracted = change.extracted
            if self._remove(db, owner, change.path):
                self._log(db, owner, change.path, "removed" if extracted is None else "updated")
            source = db.execute(
                "INSERT INTO reference_sources(owner, path, kind, version, size, modified_ns, text, pages, tags,"
                " error, indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (owner, change.path, kind_of(change.path), change.version, change.size, change.modified_ns,
                 "" if extracted is None else extracted.text,
                 len(extracted.pages) if extracted is not None and extracted.kind == "pdf" else None,
                 json.dumps([] if extracted is None else list(extracted.tags), ensure_ascii=False),
                 change.error, time.time())).lastrowid
            for position, piece in enumerate(change.pieces):
                body = extracted.text[piece.start_char:piece.end_char]
                rowid = db.execute(
                    "INSERT INTO reference_chunks(source, heading, page, start_char, end_char, folded)"
                    " VALUES (?,?,?,?,?,?)",
                    (source, json.dumps(piece.heading, ensure_ascii=False), piece.page, piece.start_char,
                     piece.end_char, _embedding_text(change.path, piece.heading, body).casefold())).lastrowid
                vector = vectors.added.get((owner, change.path, position))
                if vector is not None:
                    self._ensure_vectors(db, vectors.dimensions)
                    db.execute("INSERT INTO reference_vec(rowid, embedding, owner) VALUES (?,?,?)",
                               (rowid, _vector_bytes(vector), owner))

    def _apply_missing(self, db: sqlite3.Connection, vectors: _Vectors) -> None:
        for rowid, vector in vectors.missing.items():
            row = db.execute("SELECT s.owner FROM reference_chunks AS c JOIN reference_sources AS s ON s.id = c.source"
                             " WHERE c.id=?", (rowid,)).fetchone()
            if row is None:
                continue
            self._ensure_vectors(db, vectors.dimensions)
            db.execute("INSERT INTO reference_vec(rowid, embedding, owner) VALUES (?,?,?)",
                       (rowid, _vector_bytes(vector), row["owner"]))

    async def _run(self, scene: str, persona: KnowledgeOwner, scope: Scope,
                   operation: Callable[[sqlite3.Connection, list[str], tuple[float, ...] | None], T],
                   *, query: str | None = None) -> T:
        return (await self._execute(scene, persona, scope, operation, query=query))[0]

    async def _execute(self, scene: str, persona: KnowledgeOwner, scope: Scope,
                       operation: Callable[[sqlite3.Connection, list[str], tuple[float, ...] | None], T],
                       *, query: str | None = None) -> tuple[T, bool]:
        """The operation's result and whether more chunks may still be waiting for vectors."""
        owners = self.owners(scene, persona.id, scope)
        async with AsyncExitStack() as stack:
            for owner in sorted(owners):
                await stack.enter_async_context(self._locks.setdefault(owner, asyncio.Lock()))
            known, dimensions = await asyncio.to_thread(self._known, owners)
            plans = {owner: (self._persona_changes(persona, known[owner]) if owner.startswith("persona:")
                             else await self._scene_changes(scene, known[owner])) for owner in owners}
            vectors = await self._vectors(scene, plans, dimensions, query)

            def run() -> T:
                with self._db() as db:
                    for owner, (changes, removed) in plans.items():
                        self._apply(db, owner, changes, removed, vectors)
                    self._apply_missing(db, vectors)
                    return operation(db, owners, vectors.query)

            return await asyncio.to_thread(run), vectors.full

    async def files(self, scene: str, persona: KnowledgeOwner, scope: Scope = "all") -> list[ReferenceFile]:
        def listing(db: sqlite3.Connection, owners: list[str], _) -> list[ReferenceFile]:
            rows = db.execute(f"""SELECT owner, path, kind, length(text) AS chars, pages, tags, error
                FROM reference_sources WHERE owner IN ({",".join("?" for _ in owners)})""", owners).fetchall()
            return [ReferenceFile(row["owner"], row["path"], row["kind"], row["chars"], row["pages"],
                                  tuple(json.loads(row["tags"])), row["error"])
                    for row in sorted(rows, key=lambda row: (owners.index(row["owner"]), row["path"]))]
        return await self._run(scene, persona, scope, listing)

    async def search(self, scene: str, persona: KnowledgeOwner, query: str, *, scope: Scope = "all",
                     filename: str | None = None, limit: int = 50) -> list[ReferenceHit]:
        """Full-text hits hold at least half of the keywords, or as many as the best chunk of the same
        owner holds when that is fewer; most keywords first, then full-text rank.

        With vectors the full-text order and the nearest chunks are merged by reciprocal rank; nearest
        chunks without a full-text hit add at most ``VECTOR_ONLY`` results, each within ``VECTOR_MARGIN``
        of the nearest chunk and ``MAX_VECTOR_DISTANCE``.
        """
        terms = search_terms(query)

        def found(db: sqlite3.Connection, owners: list[str], vector: tuple[float, ...] | None) -> list[ReferenceHit]:
            lexical = self._lexical(db, owners, terms, limit, filename)
            ranks = {rowid: 1 / position for position, rowid in enumerate(lexical, 1)}
            if vector is not None and _has_vectors(db):
                nearest = []
                for owner in owners:
                    condition = (" AND rowid IN (SELECT c.id FROM reference_chunks c "
                                 "JOIN reference_sources s ON s.id=c.source WHERE s.owner=? AND s.path=?)"
                                 if filename is not None else "")
                    nearest += db.execute(f"""SELECT rowid, distance FROM reference_vec
                        WHERE embedding MATCH ? AND k=? AND owner=?{condition} ORDER BY distance""",
                        (_vector_bytes(vector), VECTOR_NEIGHBOURS, owner,
                         *((owner, filename) if filename is not None else ()))).fetchall()
                close = sorted((row for row in nearest if row["distance"] <= MAX_VECTOR_DISTANCE),
                               key=lambda row: row["distance"])
                added = 0
                for position, row in enumerate(close, 1):
                    if row["rowid"] not in ranks:
                        if added == VECTOR_ONLY or row["distance"] > close[0]["distance"] + VECTOR_MARGIN:
                            continue
                        added += 1
                    ranks[row["rowid"]] = ranks.get(row["rowid"], 0.0) + 1 / position
            keyword_hits = set(lexical)
            ordered = sorted(ranks, key=lambda rowid: (-ranks[rowid], rowid not in keyword_hits))[:limit]
            return self._hits(db, ordered, terms)

        return await self._run(scene, persona, scope, found, query=query)

    @staticmethod
    def _lexical(db: sqlite3.Connection, owners: list[str], terms: tuple[str, ...], limit: int,
                 filename: str | None = None) -> list[int]:
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
            if filename is not None:
                parts[-1] += " AND s.path=?"
                parameters.append(filename)
        if short_terms:
            # The trigram index cannot hold one- or two-character keywords.
            parts.append(f"""SELECT c.id, 0.0 FROM reference_chunks AS c JOIN reference_sources AS s ON s.id = c.source
                WHERE s.owner IN ({placeholders}) AND ({" OR ".join("instr(c.folded, ?) > 0" for _ in short_terms)})""")
            parameters += [*owners, *short_terms]
            if filename is not None:
                parts[-1] += " AND s.path=?"
                parameters.append(filename)
        matched = " + ".join("(instr(c.folded, ?) > 0)" for _ in terms)
        return [row[0] for row in db.execute(f"""
            WITH hits(id, relevance) AS MATERIALIZED ({" UNION ALL ".join(parts)}),
            scored AS (
                SELECT c.id, s.owner, s.path, c.start_char, {matched} AS matched, MIN(hits.relevance) AS relevance
                FROM hits JOIN reference_chunks AS c ON c.id = hits.id JOIN reference_sources AS s ON s.id = c.source
                GROUP BY c.id
            ),
            ranked AS (SELECT *, MAX(matched) OVER (PARTITION BY owner) AS best FROM scored)
            SELECT id FROM ranked WHERE matched >= min(?, best)
            ORDER BY matched DESC, relevance, owner, path, start_char LIMIT ?
        """, (*parameters, *terms, (len(terms) + 1) // 2, limit))]

    @staticmethod
    def _hits(db: sqlite3.Connection, ids: list[int], terms: tuple[str, ...]) -> list[ReferenceHit]:
        hits = []
        for rowid in ids:
            row = db.execute("""SELECT s.owner, s.path, c.heading, c.page, c.start_char, c.folded,
                    substr(s.text, c.start_char + 1, c.end_char - c.start_char) AS body
                FROM reference_chunks AS c JOIN reference_sources AS s ON s.id = c.source WHERE c.id=?""",
                             (rowid,)).fetchone()
            hits.append(ReferenceHit(row["owner"], row["path"], tuple(json.loads(row["heading"])), row["page"],
                                     row["start_char"], row["body"],
                                     tuple(term for term in terms if term in row["folded"])))
        return hits

    async def read(self, scene: str, persona: KnowledgeOwner, scope: Literal["persona", "chat"], path: str,
                   offset: int = 0, length: int = 4000) -> ReferencePage:
        def page(db: sqlite3.Connection, owners: list[str], _) -> ReferencePage:
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

    async def refresh(self, scene: str, persona: KnowledgeOwner, scope: Scope = "chat") -> None:
        """Bring the owners up to date and give every chunk a vector, as far as the connection answers."""
        while (await self._execute(scene, persona, scope, lambda *_: None))[1]:
            pass

    def schedule(self, scene: str, persona: KnowledgeOwner, on_done: Callable[[], None] | None = None) -> None:
        """Index the scene's files in the background; a request while it runs adds one more pass."""
        job = self._jobs.get(scene)
        if job is not None and not job.done():
            self._again.add(scene)
            return

        async def work() -> None:
            while True:
                self._again.discard(scene)
                try:
                    await self.refresh(scene, persona)
                except Exception as error:
                    log_event(logger, "reference_index_failed", "资料索引失败", level=logging.WARNING,
                              scene=scene, error=error)
                if scene not in self._again:
                    break
            if on_done is not None:
                on_done()

        self._jobs[scene] = asyncio.create_task(work())

    def processing(self, scene: str) -> bool:
        job = self._jobs.get(scene)
        return job is not None and not job.done()

    async def close(self) -> None:
        jobs = [job for job in self._jobs.values() if not job.done()]
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    def _states(self, owner: str, found: dict[str, tuple[str, int, float]]) -> list[ReferenceFileState]:
        rows = {}
        if self.index is not None:
            with self._db() as db:
                vectors = "(SELECT count(*) FROM reference_chunks AS c WHERE c.source = s.id AND c.id IN (SELECT rowid FROM reference_vec))" \
                    if _has_vectors(db) else "0"
                rows = {row["path"]: row for row in db.execute(f"""
                    SELECT s.path, s.size, s.modified_ns, s.version, s.error, length(s.text) AS chars, s.pages,
                           (SELECT count(*) FROM reference_chunks AS c WHERE c.source = s.id) AS chunks,
                           {vectors} AS vectors
                    FROM reference_sources AS s WHERE s.owner=?""", (owner,))}
        states = []
        for path, (stamp, size, modified) in found.items():
            row = rows.get(path)
            current = row is not None and (stamp == row["version"] if owner.startswith("persona:")
                                           else stamp == (row["size"], row["modified_ns"]))
            status = "processing" if not current else "failed" if row["error"] is not None else "indexed"
            states.append(ReferenceFileState(
                path, kind_of(path) or "markdown", size, modified, status, row["error"] if current else None,
                row["chars"] if current and row["error"] is None else None, row["pages"] if current else None,
                row["chunks"] if current else 0, row["vectors"] if current else 0))
        return states

    async def scene_files(self, scene: str) -> list[ReferenceFileState]:
        """The scene's files on disk now, each with what the index holds for it."""
        def read() -> list[ReferenceFileState]:
            found = {path: ((item.size, item.modified_ns), item.size, item.modified_ns / 1e9)
                     for path, item in scan(self.directory(scene)).items()}
            return self._states(f"scene:{scene}", found)
        return await asyncio.to_thread(read)

    async def persona_files(self, persona: KnowledgeOwner) -> list[ReferenceFileState]:
        """The role's knowledge files after indexing them."""
        await self.refresh("", persona, "persona")
        found = {path: (_version(document.content.encode("utf-8")), len(document.content.encode("utf-8")), 0.0)
                 for path, document in persona.knowledge.items()}
        return await asyncio.to_thread(self._states, f"persona:{persona.id}", found)

    async def announce(self, scene: str, persona_id: str) -> list[ReferenceChange]:
        """Changes to files the scene could read, since the scene was last told; the first call only marks."""
        if self.index is None:
            return []
        owners = self.owners(scene, persona_id, "all")

        def read() -> list[ReferenceChange]:
            with self._db() as db:
                latest = db.execute("SELECT coalesce(max(id), 0) FROM reference_changes").fetchone()[0]
                row = db.execute("SELECT through FROM reference_notices WHERE scene=?", (scene,)).fetchone()
                db.execute("INSERT INTO reference_notices(scene, through) VALUES (?, ?)"
                           " ON CONFLICT(scene) DO UPDATE SET through=excluded.through", (scene, latest))
                if row is None:
                    return []
                changes = {}
                for change in db.execute(f"""SELECT owner, path, action, at FROM reference_changes
                        WHERE id > ? AND id <= ? AND owner IN ({",".join("?" for _ in owners)}) ORDER BY id""",
                                         (row[0], latest, *owners)):
                    changes[change["owner"], change["path"]] = ReferenceChange(*change)
                return list(changes.values())
        return await asyncio.to_thread(read)

    def _file(self, scene: str, name: str) -> Path:
        directory = self.directory(scene)
        if directory is None:
            raise ValueError("没有实例目录，不能保存资料文件")
        if (not name or name != name.strip() or name.startswith(".") or len(name) > 200
                or any(character in name for character in "/\\\0")):
            raise ValueError(f"文件名不能用：{name!r}")
        if kind_of(name) is None:
            raise ValueError("只支持 Markdown、纯文本和 PDF")
        return directory / name

    def save(self, scene: str, name: str, data: bytes) -> None:
        """Write a file into the scene's directory in one step; an existing file of that name is replaced."""
        target = self._file(scene, name)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"文件超过 {MAX_FILE_BYTES // 1_000_000}MB 上限")
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{uuid4().hex}.part")
        try:
            with partial.open("wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)

    def delete(self, scene: str, name: str) -> None:
        target = self._file(scene, name)
        if target.is_symlink() or not target.is_file():
            raise FileNotFoundError(f"没有资料文件 {name}")
        target.unlink()

    def reprocess(self, scene: str, name: str) -> None:
        """Have the next pass read the file again even though it has not changed."""
        target = self._file(scene, name)
        if not target.is_file():
            raise FileNotFoundError(f"没有资料文件 {name}")
        with self._db() as db:
            db.execute("UPDATE reference_sources SET size=-1, version='' WHERE owner=? AND path=?",
                       (f"scene:{scene}", name))
