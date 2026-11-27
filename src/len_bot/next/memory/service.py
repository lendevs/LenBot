"""Local memory, scene-bound tools and transient per-turn recall."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import AsyncExitStack, asynccontextmanager, nullcontext
from dataclasses import asdict
import logging
import re
from typing import Annotated, Literal, TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from .embeddings import EmbeddingClient, EmbeddingSettings
from .local import LocalMemory, LocalMemorySettings
from .jobs import MemoryJobs
from .summary import MemorySummarizer
from .role_paths import require_bot_path
from .sections import Section, evidence, excerpt, split_sections
from ..platform.messages import ChatMessage, plain_text, render_message
from ..models.client import ChatModel, ModelConnectionError, ModelHTTPError
from ..models.slots import ModelSlots
from ..runtime.logs import log_event
from ..storage.store import Store, encode
from ..models.tokens import token_record
from ..models.usage import record_usage

if TYPE_CHECKING:
    from ..config import SharedConfig


logger = logging.getLogger(__name__)
STRICT = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
Scope = Literal["scene", "public"]


class IngestSettings(BaseModel):
    model_config = STRICT
    idle_seconds: float = Field(default=1800, ge=0, allow_inf_nan=False)
    min_messages: int = Field(default=50, ge=1, le=100)
    max_age_seconds: float = Field(default=86400, gt=0, allow_inf_nan=False)
    batch_size: int = Field(default=100, ge=1, le=100)
    max_steps: int = Field(default=8, ge=1, le=30)
    timeout_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)


class RecallSettings(BaseModel):
    model_config = STRICT
    auto_recall: bool = True
    recall_budget_chars: int = Field(default=1500, ge=100, le=12000)
    recall_limit: int = Field(default=5, ge=1, le=20)
    ingest: IngestSettings | None = None


class LocalMemoryConfig(RecallSettings):
    backend: Literal["local"]
    local: LocalMemorySettings
    # Derived directory abstracts/overviews generated with models.roles.memory.
    summaries: bool = False


MemorySettings = LocalMemoryConfig

class BrowseMemory(BaseModel):
    model_config = STRICT
    action: Literal["browse"]
    path: str = ""
    scope: Scope = "scene"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class ReadMemory(BaseModel):
    model_config = STRICT
    action: Literal["read"]
    path: str = Field(min_length=1)
    scope: Scope = "scene"


class SearchMemory(BaseModel):
    model_config = STRICT
    action: Literal["search"]
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class WriteMemory(BaseModel):
    model_config = STRICT
    action: Literal["write"]
    path: str = Field(min_length=1)
    content: str
    reason: str = Field(min_length=1)


class DeleteMemory(BaseModel):
    model_config = STRICT
    action: Literal["delete"]
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ForgetMemory(BaseModel):
    model_config = STRICT
    action: Literal["forget"]
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    exclude_records: list[Annotated[int, Field(gt=0)]] = Field(max_length=500)


class HistoryMemory(BaseModel):
    model_config = STRICT
    action: Literal["history"]
    path: str = Field(min_length=1)


MEMORY_ARGUMENTS = TypeAdapter(Annotated[
    BrowseMemory | ReadMemory | SearchMemory | WriteMemory | DeleteMemory | ForgetMemory | HistoryMemory,
    Field(discriminator="action"),
])
MEMORY_TOOL = {"type": "function", "function": {
    "name": "memory", "description": "浏览、检索、读写当前场景长期记忆；公共分区只读。"
    "普通删除保留修改历史；forget 清除该文件及其历史。",
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ["browse", "read", "search", "write", "delete", "forget", "history"]},
            "path": {"type": "string", "description": "除 search 外的相对路径；browse 可为空，其他动作必填。"},
            "scope": {"type": "string", "enum": ["scene", "public"], "description": "仅 browse/read 可选；默认 scene。"},
            "query": {"type": "string", "description": "search 必填的检索文字。"},
            "content": {"type": "string", "description": "write 必填的新完整正文。"},
            "reason": {"type": "string", "description": "write/delete/forget 必填的实际原因。"},
            "exclude_records": {"type": "array", "items": {"type": "integer", "minimum": 1},
                                "maxItems": 500, "description": "仅 forget 必填：选中的 recall_chat 原话 record 此后不再后台抽取。"
                                "显式 [] 表示不排除旧输入。"},
            "offset": {"type": "integer", "minimum": 0, "description": "仅 browse 的分页起点，默认 0。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                      "description": "browse 默认 20、最多 100；search 默认 5、最多 20。"},
        },
    },
}}


# Recall characters each query fragment found in a section earns it in text-only recall.
EVIDENCE_CHARS = 200
# Recap sections whose items lead recall to the matters they concern, and how much of them is used.
CUE_SECTIONS = ("我答应的事", "没回答的问题")
CUE_CHARS = 400
CUE_HITS = 2
_ARTIFACT_CUE = re.compile(
    r"(?:resources/|file_id(?![0-9A-Za-z_])|交付文件|(?<![0-9A-Za-z])#\d+(?![0-9A-Za-z])|"
    r"[\w\u3400-\u9fff-]+\.(?:md|txt|csv|tsv|xlsx?|pdf|docx?|pptx?|json|html?|png|jpe?g|webp|svg|zip|tar|gz|py|sql)(?![0-9A-Za-z_]))",
    re.IGNORECASE,
)
_RESOURCE_INTENT = re.compile(
    r"(?:资料|文件|报告|报表|表格|文档|附件|产物|交付|清单|手册|汇总表|统计表|"
    r"上次生成|之前生成|刚生成|上次导出|之前导出|上次做的|之前做的|"
    r"resources/|file_id(?![0-9A-Za-z_])|(?<![0-9A-Za-z])#\d+(?![0-9A-Za-z])|"
    r"[\w\u3400-\u9fff-]+\.(?:md|txt|csv|tsv|xlsx?|pdf|docx?|pptx?|json|html?|png|jpe?g|webp|svg|zip|tar|gz|py|sql)(?![0-9A-Za-z_]))",
    re.IGNORECASE,
)
_PREFERENCE_HEADING = re.compile(r'^ {0,3}#{1,6}[ \t]+相处偏好')
_SETEXT_UNDERLINE = re.compile(r'^(?:=+|-+)$')
_PLACEHOLDER_PREFERENCES = frozenset({
    "暂无明确记录",
    "暂无记录",
    "暂无",
    "无",
    "无明确记录",
    "暂无偏好",
    "暂无明确偏好",
    "暂无特别记录",
    "暂无明确偏好或雷点",
    "暂无明显偏好",
    "暂无明显雷点",
    "暂未发现",
    "暂未记录",
    "没有明确记录",
    "没有记录",
    "none",
    "n/a",
})


def _is_placeholder_text(text: str) -> bool:
    for line in text.splitlines():
        normalized = line.strip().lstrip("-*•·").strip().rstrip("。.;；，,!！:：").strip()
        if normalized and normalized.casefold() not in _PLACEHOLDER_PREFERENCES:
            return False
    return True


def _section_body(content: str, section: Section) -> str:
    lines = section.text(content).splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith('#'):
            index += 1
            continue
        if index + 1 < len(lines) and _SETEXT_UNDERLINE.fullmatch(lines[index + 1].strip()):
            index += 2
            continue
        break
    return '\n'.join(lines[index:]).strip()


def _is_placeholder_preference(content: str, section: Section) -> bool:
    return _is_placeholder_text(_section_body(content, section))


def _is_resource_hit(hit: dict) -> bool:
    return hit["path"].startswith("resources/")


def _has_resource_intent(text: str) -> bool:
    return bool(text and _RESOURCE_INTENT.search(text))


def _select_recall_hits(hits: list[dict], limit: int, *, prefer_resource: bool,
                        require_evidence: bool, match_query: str) -> list[dict]:
    selected = list(hits[:limit])
    if not prefer_resource or limit <= 0 or not selected or any(_is_resource_hit(hit) for hit in selected):
        return selected
    candidate = next(
        (hit for hit in hits[limit:]
         if _is_resource_hit(hit) and (not require_evidence or evidence(hit["preview"], match_query) > 0)),
        None,
    )
    if candidate is not None:
        selected[-1] = candidate
    return selected


def recall_cues(recap: str | None) -> str:
    """The recap's promises, unanswered questions and task/resource clues, latest last."""
    lines: list[str] = []
    section: str | None = None
    for line in (recap or "").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section is not None and line.strip():
            cleaned = line.strip().removeprefix("- ").removeprefix("* ").strip()
            if cleaned and (section in CUE_SECTIONS or _ARTIFACT_CUE.search(cleaned)):
                lines.append(cleaned)
    return "\n".join(lines)[-CUE_CHARS:]


class MemoryService:
    def __init__(self, settings: LocalMemoryConfig,
                 backend: LocalMemory, *, jobs: MemoryJobs, store: Store,
                 active_personas: dict[str, str]):
        self.settings, self.backend = settings, backend
        self.jobs, self.store = jobs, store
        self.active_personas = dict(active_personas)
        for scene in self.store.message_persona_scenes() | self.active_personas.keys():
            ids = self.store.message_persona_ids(scene)
            if scene in self.active_personas:
                ids.add(self.active_personas[scene])
            self.jobs.remember_personas(scene, ids)
        self.summarizer: MemorySummarizer | None = None
        # A complete read/generate/write extraction shares this queue with edits.
        self.write_locks: dict[str, asyncio.Lock] = {}
        self.reindexing = False

    async def rebuild_index(self) -> int:
        """Rebuild derivations while existing scene queues hold edits and extraction."""
        if self.reindexing:
            raise FileExistsError('记忆索引正在重建')
        self.reindexing = True
        try:
            async with AsyncExitStack() as stack:
                for scene in sorted(set(self.active_personas) | set(self.write_locks) | {'public'}):
                    await stack.enter_async_context(self.write_lock(scene))
                if self.backend.embedding is not None:
                    return await self.backend.reindex_embeddings()
                return await self.backend.reindex_text()
        finally:
            self.reindexing = False

    async def read_group_profile(self, scene: str) -> str | None:
        """Read the current derived profile under the backend's existing write/read lock."""
        if self.summarizer is None:
            return None
        summary = await self.backend.summary(scene)
        return summary.overview if summary.changed_after is None else None

    def write_lock(self, scene: str) -> asyncio.Lock:
        return self.write_locks.setdefault(scene, asyncio.Lock())

    def known_persona_ids(self, scene: str) -> set[str]:
        return self.jobs.persona_ids(scene)

    @property
    def actions(self) -> list[str]:
        return ["browse", "read", "search", "write", "delete", "history", "forget"]

    async def search(self, scene: str, query: str, limit: int, *, automatic: bool = False,
                     text_query: str | None = None, persona: str | None = None,
                     literal: bool = False) -> list[dict]:
        """``persona`` hides other roles' Bot records; the panel searches without it."""
        hits = await self.backend.search(scene, query, limit, automatic=automatic, text_query=text_query,
                                         bot_persona=persona, literal=literal)
        return [{**asdict(hit), "score": None} for hit in hits]

    def own_bot_path(self, scene: str, path: str) -> None:
        """The current role reads and writes only its own ``bot/<id>/`` records."""
        persona = self.active_personas.get(scene)
        parts = path.strip('/').split('/')
        if persona is not None and parts[0] == 'bot' and len(parts) > 1 and parts[1] != persona:
            raise ValueError(f'{path!r} 是另一个角色的记录；当前角色只读写 bot/{persona}/ 下的文件')

    async def write(self, scene: str, path: str, content: str, reason: str, *,
                    scope: Scope = "scene") -> dict:
        if not reason.strip():
            raise ValueError("memory write reason must not be blank")
        async with self.write_lock("public" if scope == "public" else scene):
            require_bot_path(path, self.known_persona_ids(scene))
            result = (await self.backend.write(scene, path, content, reason) if scope == "scene"
                      else await self.backend.owner_write_public(path, content, reason))
            return asdict(result)

    async def delete(self, scene: str, path: str, reason: str, *, forget: bool,
                     exclude_records: list[int] | None = None) -> dict:
        if not reason.strip():
            raise ValueError("memory delete reason must not be blank")
        if forget != (exclude_records is not None):
            raise ValueError("forget 必须显式选择 exclude_records（可为 []）；普通 delete 不接受来源排除")
        async with self.write_lock(scene):
            if forget:
                selected = sorted(set(exclude_records))
                self.store.check_message_records(scene, selected)
                added = self.jobs.exclude_records(scene, selected)
                try:
                    result = await self.backend.forget(scene, path)
                except Exception as error:
                    raise RuntimeError(
                        f"已保存 {len(selected)} 条原话的抽取排除；记忆遗忘未完成：{type(error).__name__}: {error}"
                    ) from error
                return {**asdict(result), "excluded_records": selected, "new_exclusions": added}
            result = await self.backend.delete(scene, path, reason)
            return asdict(result)

    async def history(self, scene: str, path: str) -> list[dict]:
        return [asdict(change) for change in await self.backend.history(scene, path)]

    async def execute(self, scene: str, arguments: dict) -> str:
        try:
            item = MEMORY_ARGUMENTS.validate_python(arguments)
        except ValidationError as error:
            raise ValueError(f"Invalid memory arguments: {repr(arguments)[:500]}; {error}") from error
        persona = self.active_personas.get(scene)
        if not isinstance(item, SearchMemory):
            self.own_bot_path(scene, item.path)
        if isinstance(item, BrowseMemory):
            result = asdict(await self.backend.browse(scene, item.path, scope=item.scope,
                                                     offset=item.offset, limit=item.limit, bot_persona=persona))
        elif isinstance(item, ReadMemory):
            result = asdict(await self.backend.read(scene, item.path, scope=item.scope))
        elif isinstance(item, SearchMemory):
            result = {"hits": await self.search(scene, item.query, item.limit, persona=persona)}
        elif isinstance(item, WriteMemory):
            result = await self.write(scene, item.path, item.content, item.reason)
        elif isinstance(item, (DeleteMemory, ForgetMemory)):
            result = await self.delete(scene, item.path, item.reason, forget=isinstance(item, ForgetMemory),
                                       exclude_records=item.exclude_records if isinstance(item, ForgetMemory) else None)
        else:
            result = {"changes": await self.history(scene, item.path)}
        return encode(result)

    async def recall(self, scene: str, messages: list[ChatMessage], cues: str = "", *,
                     target_uids: Sequence[str] = (), vector_timeout_seconds: float | None = 0.75) -> dict:
        """Recall from actual chat only; returned text never becomes a native history entry.

        ``cues`` (see ``recall_cues``) find what the recent chat does not name; their hits only use the
        budget the chat's own hits leave, and are searched by wording alone, with no vector request."""
        relevant = [message for message in messages if not message.is_self]
        # Semantic retrieval keeps speakers; literal retrieval must not match timestamps/accounts.
        text_only = self.backend.embedding is None
        # Short replies still need the preceding topic, including our question.
        queries = [plain_text(message) if text_only else render_message(message, timezone="UTC") for message in messages
                   if plain_text(message).strip() and message.send_status in {"received", "sent", "simulated"}]
        budget = self.settings.recall_budget_chars
        items: list[dict] = []
        seen: set[tuple[str, str]] = set()

        def append(scope: str, path: str, content: str, limit: int, *,
                   kind: str = "file", source_chars: int | None = None, sections: tuple[dict, ...] = ()) -> None:
            nonlocal budget
            if not content.strip() or limit == 0 or (scope, path) in seen or budget <= 0:
                return
            shown = content[:min(budget, limit)]
            items.append({"scope": scope, "path": path, "content": shown, "kind": kind,
                          "truncated": len(shown) < len(content) or (
                              source_chars is not None and len(shown) < source_chars)})
            if sections:
                items[-1]['sections'] = sections
            seen.add((scope, path))
            budget -= len(shown)

        own_uids = {message.bot_id for message in messages if message.scene == scene}
        candidates = [uid for uid in target_uids if uid and uid not in own_uids]
        candidates.extend(message.sender.uid for message in reversed(relevant))
        active_uids = set(candidates)

        def eligible_hit(hit: dict) -> bool:
            path = hit["path"]
            if hit["scope"] == "scene" and path.startswith("people/"):
                uid, _, relative_path = path.removeprefix("people/").partition("/")
                return bool(relative_path) and uid in active_uids
            return True

        users = list(dict.fromkeys(candidates))[:4]
        profiles = await self.backend.profiles(scene, users)
        # Keep room for the latest topic; source and dates remain in the real file text.
        per_profile = min(900, budget // 2 // len(profiles)) if profiles else 0
        for profile in profiles:
            if profile.path.endswith('/preferences.md') and _is_placeholder_text(profile.content):
                continue
            sections = split_sections(profile.content)
            all_preferences = [section for section in sections if section.heading
                               and section.heading[-1].startswith('相处偏好')]
            has_empty_pref_heading = any(_PREFERENCE_HEADING.match(line) for line in profile.content.splitlines())
            if not all_preferences and not has_empty_pref_heading:
                append("scene", profile.path, profile.content, per_profile)
                continue
            preferences = [section for section in all_preferences
                           if not _is_placeholder_preference(profile.content, section)]
            ordered = preferences + [section for section in sections if section not in all_preferences]
            if not ordered:
                continue
            remaining, parts = per_profile, []
            for index, section in enumerate(ordered):
                if remaining <= 0:
                    break
                # Preferences go first; share the rest so a long facts section leaves room for
                # dated recent circumstances and uncertain observations in the same profile.
                share = (remaining if index == len(ordered) - 1 else remaining // 2
                         if index < len(preferences) else remaining // (len(ordered) - index))
                part = section.text(profile.content)[:share].rstrip()
                if part:
                    parts.append(part)
                    remaining -= len(part) + 2
            if parts:
                append("scene", profile.path, '\n\n'.join(parts), per_profile, kind='excerpt',
                       source_chars=len(profile.content))
        query = "\n".join(queries)[-1200:]
        text_query = "\n".join(plain_text(message) for message in messages
                               if plain_text(message).strip() and message.send_status in {"received", "sent", "simulated"})[-1200:]
        cues = cues.strip()
        resource_intent = _has_resource_intent(text_query)
        persona = self.active_personas.get(scene)
        recall_limit = self.settings.recall_limit

        query_entries: list[tuple[dict, str, bool]] = []
        if query and budget > 0:
            fetch_limit = min(100, max(recall_limit * 8, 50)) if resource_intent else recall_limit
            search = self.search(scene, query, fetch_limit, automatic=True, text_query=text_query, persona=persona)
            if text_only or vector_timeout_seconds is None:
                hits = await search
            else:
                try:
                    hits = await asyncio.wait_for(search, timeout=vector_timeout_seconds)
                except (OSError, httpx.HTTPError, ModelHTTPError, ModelConnectionError) as error:
                    log_event(logger, 'memory_recall_vector_degraded', '自动记忆召回改用字面检索',
                              level=logging.WARNING, scene=scene, timeout_seconds=vector_timeout_seconds, error=error)
                    text_only = True
                    hits = await self.search(scene, text_query, fetch_limit, automatic=True, persona=persona, literal=True)
            raw_hits = [hit for hit in hits if eligible_hit(hit) and (hit["scope"], hit["path"]) not in seen]
            selected = _select_recall_hits(raw_hits, recall_limit, prefer_resource=resource_intent,
                                           require_evidence=text_only, match_query=text_query)
            query_entries = [(hit, text_query, text_only) for hit in selected]

        cue_prefer_resource = resource_intent or _has_resource_intent(cues)
        need_resource_from_cues = (
            bool(cues) and budget > 0 and resource_intent
            and not any(_is_resource_hit(hit) for hit, _, _ in query_entries)
        )
        prefetched_cue_hits: list[dict] | None = None
        if need_resource_from_cues:
            query_keys = seen | {(hit["scope"], hit["path"]) for hit, _, _ in query_entries}
            cue_fetch = min(100, max(CUE_HITS * 8, 50))
            prefetched_cue_hits = [hit for hit in await self.search(scene, cues, cue_fetch, automatic=True,
                                                                    persona=persona, literal=True)
                                   if eligible_hit(hit) and (hit["scope"], hit["path"]) not in query_keys]
            resource_cue = next(
                (hit for hit in prefetched_cue_hits
                 if _is_resource_hit(hit) and evidence(hit["preview"], cues) > 0),
                None,
            )
            if resource_cue is not None:
                if query_entries and len(query_entries) >= recall_limit:
                    query_entries[-1] = (resource_cue, cues, True)
                else:
                    query_entries.append((resource_cue, cues, True))

        for position, (hit, match_text, evidence_capped) in enumerate(query_entries):
            # Each remaining hit gets an equal share; what a short one leaves goes to the next.
            share = max(budget // (len(query_entries) - position), min(budget, 200))
            if evidence_capped:
                # Without vectors the only sign of relevance is the shared wording: a section sharing
                # one fragment with the recent chat is shown around that fragment only.
                share = min(share, EVIDENCE_CHARS * evidence(hit["preview"], match_text))
            append(hit["scope"], hit["path"], excerpt(hit["preview"], match_text, share), share,
                   kind="excerpt",
                   source_chars=hit["total_chars"], sections=hit["sections"])

        if cues and budget > 0:
            has_resource = any(_is_resource_hit(item) for item in items)
            if prefetched_cue_hits is None:
                cue_fetch = min(100, max(CUE_HITS * 8, 50)) if (cue_prefer_resource and not has_resource) else CUE_HITS
                raw_cue_hits = [hit for hit in await self.search(scene, cues, cue_fetch, automatic=True,
                                                                 persona=persona, literal=True)
                                if eligible_hit(hit) and (hit["scope"], hit["path"]) not in seen]
            else:
                raw_cue_hits = [hit for hit in prefetched_cue_hits if (hit["scope"], hit["path"]) not in seen]
            cue_hits = _select_recall_hits(raw_cue_hits, CUE_HITS,
                                           prefer_resource=cue_prefer_resource and not has_resource,
                                           require_evidence=True, match_query=cues)
            for position, hit in enumerate(cue_hits):
                share = min(budget // (len(cue_hits) - position), EVIDENCE_CHARS * evidence(hit["preview"], cues))
                append(hit["scope"], hit["path"], excerpt(hit["preview"], cues, share), share, kind="excerpt",
                       source_chars=hit["total_chars"], sections=hit["sections"])
        return {"backend": self.settings.backend, "query": query, "cues": cues, "items": items,
                "content_chars": self.settings.recall_budget_chars - budget,
                "budget_chars": self.settings.recall_budget_chars}


@asynccontextmanager
async def open_memory_backend(config: SharedConfig):
    settings = config.memory
    if settings is None:
        yield None
    else:
        binding = settings.local.embedding
        if binding is None:
            yield await asyncio.to_thread(LocalMemory, settings.local)
        else:
            provider = config.models.providers[binding.provider]
            resolved = EmbeddingSettings(**binding.model_dump(), base_url=provider.base_url,
                                         api_key=provider.api_key, proxy=provider.proxy)
            async with EmbeddingClient(resolved) as embedding:
                backend = await asyncio.to_thread(LocalMemory, settings.local, embedding=embedding)
                yield backend


@asynccontextmanager
async def open_memory(config: SharedConfig, store: Store, *, active_personas: dict[str, str] | None = None,
                      slots: ModelSlots | None = None):
    async with open_memory_backend(config) as backend:
        if backend is None:
            yield None
            return
        with MemoryJobs(config.database.with_name(config.database.name + ".memory.sqlite3")) as jobs:
            jobs.recover_embeddings(store.now())
            # Offline index/import owners do not have a running chat role.
            service = MemoryService(config.memory, backend, jobs=jobs, store=store,
                                    active_personas={} if active_personas is None else active_personas)
            if backend.embedding is not None:
                async def embed(source, texts, purpose):
                    async with (slots.slot(scene=source) if slots is not None else nullcontext()):
                        started = store.now()
                        with jobs.db:
                            call_id = jobs.db.execute(
                                "INSERT INTO memory_embedding_calls(scene,purpose,started,request) VALUES(?,?,?,?)",
                                (source, purpose, started, encode({"texts": texts,
                                 "settings": backend.embedding.settings.model_dump(mode="json", exclude={"api_key"})})),
                            ).lastrowid
                        try:
                            batch = await backend.embedding.embed(texts)
                        except BaseException as error:
                            with jobs.db:
                                jobs.db.execute("UPDATE memory_embedding_calls SET ended=?,error=? WHERE id=?",
                                                (store.now(), f"{type(error).__name__}: {error}", call_id))
                            raise
                        with jobs.db:
                            tokens = token_record(batch.token_usage)
                            jobs.db.execute("UPDATE memory_embedding_calls SET ended=?,response=?,usage=?,tokens=? WHERE id=?",
                                            (store.now(), encode({"vector_count":len(batch.vectors),"dimensions":batch.dimensions}),
                                             None if batch.usage is None else encode(batch.usage),
                                             None if tokens is None else encode(tokens), call_id))
                        with store.db:
                            record_usage(store.db, time=started, scene=source, purpose="memory_embedding",
                                         provider=backend.embedding.settings.provider,
                                         model=backend.embedding.settings.model, tokens=tokens)
                        return batch
                backend.track_embedding = embed

            if not config.memory.summaries:
                yield service
                return
            async with ChatModel(config.model_settings("memory")) as model:
                service.summarizer = MemorySummarizer(config, backend, jobs, model, store, slots=slots)
                yield service
