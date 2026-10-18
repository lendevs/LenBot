"""A packaged or explicitly refreshed JSON directory; installation stays in PluginManager."""

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
from .manifest import PluginPermission

CATALOG = Path(__file__).with_name('plugin_catalog.json')


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

    @field_validator('permissions')
    @classmethod
    def distinct_permissions(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError('permissions 不能重复')
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


class CatalogView(BaseModel):
    source: Literal['builtin', 'remote']
    url: str | None
    loaded_at: float | None
    entries: list[CatalogEntry]


def parse_index(raw: bytes, source: str) -> CatalogIndex:
    try:
        return CatalogIndex.model_validate_json(raw)
    except ValidationError as error:
        raise ValueError(f'插件目录 {source} 解析失败：{error}；原文开头：{raw[:300]!r}') from error


class PluginCatalog:
    def __init__(self):
        self.builtin = parse_index(CATALOG.read_bytes(), str(CATALOG))
        self.loaded_at = time.time()
        self.remote: CatalogView | None = None

    def view(self, settings: PluginCatalogSettings) -> CatalogView:
        if settings.url is None:
            return CatalogView(source='builtin', url=None, loaded_at=self.loaded_at, entries=self.builtin.entries)
        if self.remote is not None and self.remote.url == settings.url:
            return self.remote
        return CatalogView(source='remote', url=settings.url, loaded_at=None, entries=[])

    async def refresh(self, settings: PluginCatalogSettings) -> CatalogView:
        if settings.url is None:
            return self.view(settings)
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=True) as client:
            async with client.stream('GET', settings.url) as response:
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError('插件目录超过 2 MiB')
        index = parse_index(bytes(raw), settings.url)
        self.remote = CatalogView(source='remote', url=settings.url, loaded_at=time.time(), entries=index.entries)
        return self.remote


class MarketEntry(CatalogEntry):
    installed: bool
    installed_version: str | None
    update_available: bool
    compatible: bool
    incompatible_reason: str | None


class MarketView(BaseModel):
    source: Literal['builtin', 'remote']
    url: str | None
    loaded_at: float | None
    categories: list[str]
    total: int
    entries: list[MarketEntry]


def _newer(candidate: str, installed: str) -> bool:
    try:
        return Version(candidate) > Version(installed)
    except InvalidVersion:
        return candidate != installed


def market_entry(entry: CatalogEntry, installed: bool, installed_version: str | None,
                 host: str | None = None) -> MarketEntry:
    """Annotate one catalog entry with what this host already has and whether it can load it."""
    host = version('len-bot') if host is None else host
    reason = None
    if entry.interface != INTERFACE:
        reason = f'插件接口版本 {entry.interface}，本机宿主是 {INTERFACE}'
    elif entry.requires_lenbot is not None and Version(host) not in SpecifierSet(entry.requires_lenbot):
        reason = f'需要宿主 {entry.requires_lenbot}，本机是 {host}'
    return MarketEntry(**entry.model_dump(), installed=installed, installed_version=installed_version,
                       update_available=(installed_version is not None
                                         and _newer(entry.version, installed_version)),
                       compatible=reason is None, incompatible_reason=reason)


def market(view: CatalogView, installed: dict[str, str | None], *, query: str = '', category: str | None = None,
           host: str | None = None) -> MarketView:
    """Filter the catalog by a case-insensitive text query and a category.

    installed maps installed plugin names to their manifest version (None when the manifest is
    unreadable); categories always lists every category of the unfiltered catalog."""
    words = query.casefold().split()

    def matches(entry: CatalogEntry) -> bool:
        text = ' '.join([entry.name, entry.title, entry.description, entry.category,
                         *entry.capabilities, *entry.authors]).casefold()
        return (category is None or entry.category == category) and all(word in text for word in words)

    entries = [market_entry(entry, entry.name in installed, installed.get(entry.name), host)
               for entry in view.entries if matches(entry)]
    return MarketView(source=view.source, url=view.url, loaded_at=view.loaded_at,
                      categories=sorted({entry.category for entry in view.entries}),
                      total=len(view.entries), entries=entries)
