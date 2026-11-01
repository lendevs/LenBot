"""The packaged official catalog plus remote indexes read on refresh; installation stays in PluginManager."""

import asyncio
from importlib.metadata import version
from pathlib import Path
import time
from typing import Literal

import httpx
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..configuration.plugin import PLUGIN_NAME, PLUGIN_RESERVED, PluginCatalogSettings, catalog_url
from ...plugin import INTERFACE
from .install import repository_url, revision_ref
from .manifest import ChatPlatform, PluginPermission, host_satisfies

CATALOG = Path(__file__).with_name('plugin_catalog.json')
COMMUNITY = 'https://raw.githubusercontent.com/lendevs/lenbot-plugin-index/main/catalog.json'


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1)
    license: str = Field(min_length=1)
    version: str = Field(min_length=1)
    interface: int = Field(gt=0)
    requires_lenbot: str | None = None
    category: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    usage: list[str] = Field(default_factory=list)
    install: Literal['git']
    repository: str
    homepage: str | None = None
    ref: str | None = None
    # The host capabilities the plugin uses, as its plugin.toml declares them (or will); None: not stated.
    # Shown before installation; what the installed plugin may do is still its own manifest.
    permissions: list[PluginPermission] | None = None
    # Chat platforms the plugin declares; None: every platform. Checked against the manifest on install.
    chat_platforms: list[ChatPlatform] | None = Field(default=None, min_length=1)

    @field_validator('permissions', 'chat_platforms')
    @classmethod
    def distinct_permissions(cls, value: list[str] | None, info) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError(f'{info.field_name} 不能重复')
        return value

    @field_validator('name')
    @classmethod
    def plugin_name(cls, value: str) -> str:
        if PLUGIN_NAME.fullmatch(value) is None or value in PLUGIN_RESERVED:
            raise ValueError('目录条目使用插件清单的有效名称')
        return value

    @field_validator('requires_lenbot')
    @classmethod
    def host_range(cls, value: str | None) -> str | None:
        return None if value is None else str(SpecifierSet(value))

    @field_validator('repository')
    @classmethod
    def source(cls, value: str) -> str:
        return repository_url(value)

    @field_validator('homepage')
    @classmethod
    def page(cls, value: str | None) -> str | None:
        return None if value is None else catalog_url(value)

    @field_validator('ref')
    @classmethod
    def selected_ref(cls, value: str | None) -> str | None:
        return None if value is None else revision_ref(value)

class CatalogIndex(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: Literal[1]
    entries: list[CatalogEntry]

    @field_validator('entries')
    @classmethod
    def names(cls, entries: list[CatalogEntry]) -> list[CatalogEntry]:
        names = [entry.name for entry in entries]
        if len(set(names)) != len(names):
            raise ValueError('同一目录不能重复插件名称')
        return entries


CatalogSourceKind = Literal['official', 'community', 'custom']


class CatalogSource(BaseModel):
    kind: CatalogSourceKind
    url: str | None
    loaded_at: float | None
    error: str | None
    total: int


class SourcedEntry(CatalogEntry):
    source: CatalogSourceKind


class CatalogView(BaseModel):
    """Every source in order; a name listed by an earlier source hides the same name further down."""
    url: str | None
    sources: list[CatalogSource]
    entries: list[SourcedEntry]


def parse_index(raw: bytes, source: str) -> CatalogIndex:
    try:
        return CatalogIndex.model_validate_json(raw)
    except ValidationError as error:
        raise ValueError(f'插件目录 {source} 解析失败：{error}；原文开头：{raw[:300]!r}') from error


class PluginCatalog:
    """The packaged official catalog, the community index and an optional custom URL.

    Remote sources are read only on refresh; one source failing keeps the others and records its error."""

    def __init__(self):
        self.builtin = parse_index(CATALOG.read_bytes(), str(CATALOG))
        self.loaded_at = time.time()
        self.community: str | None = COMMUNITY
        self.remote: dict[str, tuple[float, CatalogIndex] | str] = {}

    def _remote(self, kind: CatalogSourceKind, url: str) -> tuple[CatalogSource, list[CatalogEntry]]:
        loaded = self.remote.get(url)
        if isinstance(loaded, tuple):
            return CatalogSource(kind=kind, url=url, loaded_at=loaded[0], error=None,
                                 total=len(loaded[1].entries)), loaded[1].entries
        return CatalogSource(kind=kind, url=url, loaded_at=None, error=loaded, total=0), []

    def view(self, settings: PluginCatalogSettings) -> CatalogView:
        sources = [(CatalogSource(kind='official', url=None, loaded_at=self.loaded_at, error=None,
                                  total=len(self.builtin.entries)), self.builtin.entries)]
        if self.community is not None:
            sources.append(self._remote('community', self.community))
        if settings.url is not None and settings.url != self.community:
            sources.append(self._remote('custom', settings.url))
        seen: set[str] = set()
        entries = []
        for source, listed in sources:
            for entry in listed:
                if entry.name not in seen:
                    seen.add(entry.name)
                    entries.append(SourcedEntry(**entry.model_dump(), source=source.kind))
        return CatalogView(url=settings.url, sources=[source for source, _ in sources], entries=entries)

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> None:
        try:
            async with client.stream('GET', url) as response:
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError('插件目录超过 2 MiB')
            self.remote[url] = (time.time(), parse_index(bytes(raw), url))
        except (ValueError, httpx.HTTPError, httpx.InvalidURL) as error:
            self.remote[url] = str(error) or type(error).__name__

    async def refresh(self, settings: PluginCatalogSettings) -> CatalogView:
        urls = list(dict.fromkeys(url for url in (self.community, settings.url) if url is not None))
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=True) as client:
            await asyncio.gather(*(self._fetch(client, url) for url in urls))
        return self.view(settings)


class MarketEntry(SourcedEntry):
    installed: bool
    installed_version: str | None
    update_available: bool
    compatible: bool
    incompatible_reason: str | None


class MarketView(BaseModel):
    url: str | None
    sources: list[CatalogSource]
    categories: list[str]
    total: int
    entries: list[MarketEntry]


def _newer(candidate: str, installed: str) -> bool:
    try:
        return Version(candidate) > Version(installed)
    except InvalidVersion:
        return candidate != installed


def market_entry(entry: SourcedEntry, installed: bool, installed_version: str | None,
                 host: str | None = None) -> MarketEntry:
    """Annotate one catalog entry with what this host already has and whether it can load it."""
    host = version('len-bot') if host is None else host
    reason = None
    if entry.interface != INTERFACE:
        reason = f'插件接口版本 {entry.interface}，本机宿主是 {INTERFACE}'
    elif entry.requires_lenbot is not None and not host_satisfies(host, entry.requires_lenbot):
        reason = f'需要宿主 {entry.requires_lenbot}，本机是 {host}'
    return MarketEntry(**entry.model_dump(), installed=installed, installed_version=installed_version,
                       update_available=(installed_version is not None
                                         and _newer(entry.version, installed_version)),
                       compatible=reason is None, incompatible_reason=reason)


def market(view: CatalogView, installed: dict[str, str | None], *, query: str = '', category: str | None = None,
           source: CatalogSourceKind | None = None, host: str | None = None) -> MarketView:
    """Filter the catalog by a case-insensitive text query, a category and a source.

    installed maps installed plugin names to their manifest version (None when the manifest is
    unreadable); categories always lists every category of the unfiltered catalog."""
    words = query.casefold().split()

    def matches(entry: SourcedEntry) -> bool:
        text = ' '.join([entry.name, entry.title, entry.description, entry.category,
                         *entry.capabilities, *entry.authors]).casefold()
        return ((category is None or entry.category == category) and (source is None or entry.source == source)
                and all(word in text for word in words))

    entries = [market_entry(entry, entry.name in installed, installed.get(entry.name), host)
               for entry in view.entries if matches(entry)]
    return MarketView(url=view.url, sources=view.sources,
                      categories=sorted({entry.category for entry in view.entries}),
                      total=len(view.entries), entries=entries)
