"""Scene conversation, expression, attention and arrangement settings."""

from __future__ import annotations

import re
from datetime import time as WallTime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .types import STRICT, _valid_timezone
from ..runtime.identity import IdentitySettings
from .learning import LearningSettings
from .tasks import TaskSettings


class Compaction(BaseModel):
    model_config = STRICT

    input_tokens: int = Field(default=60000, gt=0, strict=True)
    keep_recent_tokens: int = Field(default=20000, gt=0, strict=True)
    max_output_tokens: int | None = Field(default=None, gt=0)
    # Recap requests think at this effort instead of the mind's quick effort, so the thinking a model spends
    # on folding history cannot use up the recap's output allowance; null keeps the quick effort.
    reasoning_effort: str | None = Field(default=None, min_length=1, pattern=r"\S")


class TextDelivery(BaseModel):
    model_config = STRICT

    max_chars: int = Field(default=300, gt=0, strict=True)
    min_interval_seconds: float = Field(default=0.6, ge=0, allow_inf_nan=False)
    max_interval_seconds: float = Field(default=2.0, ge=0, allow_inf_nan=False)
    chars_per_second: float = Field(default=40.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_interval(self) -> TextDelivery:
        if self.min_interval_seconds > self.max_interval_seconds:
            raise ValueError("min_interval_seconds must not exceed max_interval_seconds")
        return self


class WebReadSettings(BaseModel):
    model_config = STRICT

    # local fetches the page from this machine; the others read it through a keyed service.
    provider: Literal["local", "deepseek", "tavily", "jina"] = "local"
    connection: str | None = Field(default=None, min_length=1, pattern=r"\S")
    timeout_seconds: float = Field(default=20, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def read_connection(self) -> WebReadSettings:
        if self.provider != "local" and self.connection is None:
            raise ValueError(f"{self.provider} 读取需要选择连接")
        if self.provider == "local" and self.connection is not None:
            raise ValueError("本机读取不使用连接")
        return self


class ImageSettings(BaseModel):
    model_config = STRICT

    max_bytes: int = Field(default=10000000, gt=0)
    max_pixels: int = Field(default=25000000, gt=0)
    max_dimension: int = Field(default=1280, gt=0)
    timeout_seconds: float = Field(default=20, gt=0, allow_inf_nan=False)


ScheduleRole = Literal["owner", "admin", "group_manager", "whitelist", "member"]


class ScheduleSettings(BaseModel):
    model_config = STRICT

    enabled: bool = True
    max_pending: int = Field(default=50, gt=0)
    owner: str | None = None
    admins: list[str] = Field(default_factory=list)
    whitelist: list[str] = Field(default_factory=list)
    own: list[ScheduleRole] = Field(
        default_factory=lambda: ["owner", "admin", "group_manager", "whitelist", "member"]
    )
    others: list[ScheduleRole] = Field(default_factory=lambda: ["owner", "admin", "group_manager"])
    manage: list[ScheduleRole] = Field(default_factory=lambda: ["owner", "admin", "group_manager"])
    autonomous: bool = True

    @field_validator("owner")
    @classmethod
    def valid_owner(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[a-z][a-z0-9_-]*:[^:\s/\\]+", value) is None:
            raise ValueError("owner must be a platform:account identity")
        return value

    @field_validator("admins", "whitelist")
    @classmethod
    def valid_identities(cls, values: list[str]) -> list[str]:
        if any(re.fullmatch(r"[a-z][a-z0-9_-]*:[^:\s/\\]+", value) is None for value in values):
            raise ValueError("must contain platform:account identities")
        return values

    @field_validator("own", "others", "manage")
    @classmethod
    def unique_roles(cls, values: list[ScheduleRole]) -> list[ScheduleRole]:
        if len(values) != len(set(values)):
            raise ValueError("roles must not repeat")
        return values


def _local_clock(value: object) -> WallTime:
    if not isinstance(value, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?", value) is None:
        raise ValueError("must be a local HH:MM or HH:MM:SS clock without offset or fraction")
    return WallTime.fromisoformat(value)


class QuietHours(BaseModel):
    model_config = STRICT

    start: WallTime
    end: WallTime
    direct: Literal["allow", "notice", "defer"] = "defer"
    notice_text: str | None = None

    @field_validator("start", "end", mode="before")
    @classmethod
    def local_clock(cls, value: object) -> WallTime:
        return _local_clock(value)

    @model_validator(mode="after")
    def valid_period(self) -> "QuietHours":
        if self.start == self.end:
            raise ValueError("quiet_hours start and end must differ")
        if self.direct == "notice":
            if self.notice_text is None or not self.notice_text.strip():
                raise ValueError("quiet_hours notice requires nonblank notice_text")
        elif self.notice_text is not None:
            raise ValueError("quiet_hours notice_text is only accepted for direct=notice")
        return self


class Proactive(BaseModel):
    """Wake a quiet group at most once per scene-local day inside active hours."""

    model_config = STRICT

    idle_seconds: float = Field(default=10800.0, ge=600, allow_inf_nan=False)
    start: WallTime = WallTime(10, 0)
    end: WallTime = WallTime(22, 0)

    @field_validator("start", "end", mode="before")
    @classmethod
    def local_clock(cls, value: object) -> WallTime:
        return _local_clock(value)

    @model_validator(mode="after")
    def valid_period(self) -> Proactive:
        if self.start == self.end:
            raise ValueError("proactive start and end must differ")
        return self


class AttentionDeclarations(BaseModel):
    """Persistent intents; absent means the tool and runtime are disabled."""
    model_config = STRICT

    mode: Literal['enforce', 'record', 'context'] = 'enforce'
    max_minutes: float = Field(default=240.0, gt=0, allow_inf_nan=False)
    max_intents: int = Field(default=5, ge=1, strict=True)
    max_conditions: int = Field(default=4, ge=1, strict=True)
    max_people: int = Field(default=5, ge=1, strict=True)
    max_keywords: int = Field(default=5, ge=1, strict=True)


class TurnDisposition(BaseModel):
    """Optional local participation state, independent of persistent intents."""
    model_config = STRICT

    mode: Literal['enforce', 'record'] = 'enforce'
    max_minutes: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    max_people: int = Field(default=5, ge=1, strict=True)


class Attention(BaseModel):
    model_config = STRICT

    only_direct: bool = False
    keywords: list[str] = Field(default_factory=list)
    other_bot_ids: list[str] = Field(default_factory=list)
    direct_idle_seconds: float = Field(default=1.5, ge=0, allow_inf_nan=False)
    direct_max_seconds: float = Field(default=4.0, gt=0, allow_inf_nan=False)
    named_idle_seconds: float = Field(default=3.0, ge=0, allow_inf_nan=False)
    named_max_seconds: float = Field(default=8.0, gt=0, allow_inf_nan=False)
    keyword_cooldown_seconds: float = Field(default=60.0, ge=0, allow_inf_nan=False)
    # Each message the bot sends opens one follow-up: the next message within this window from the person it
    # answered, or from anyone after an interjection that answered no one, wakes it once. 0 turns follow-ups off.
    focus_seconds: float = Field(default=120.0, ge=0, allow_inf_nan=False)
    focus_idle_seconds: float = Field(default=4.0, ge=0, allow_inf_nan=False)
    focus_max_seconds: float = Field(default=12.0, gt=0, allow_inf_nan=False)
    # Joining in unprompted: at least the minimum after the bot last spoke, doubling up to the maximum
    # while its interjections go unanswered or a look at the chat ends silent.
    ambient_min_interval_seconds: float = Field(default=600.0, gt=0, allow_inf_nan=False)
    ambient_max_interval_seconds: float = Field(default=2400.0, gt=0, allow_inf_nan=False)
    # Pace of every chat wake, @ included: up to speech_burst messages in a row, then one more each
    # speech_interval_seconds. Reminders and task results are not held. 0 seconds turns the pace off.
    speech_burst: int = Field(default=3, ge=1, strict=True)
    speech_interval_seconds: float = Field(default=120.0, ge=0, allow_inf_nan=False)
    # Per message the interjection rule does not admit; batches like focus.
    explore_probability: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    max_extensions: int = Field(default=4, ge=0)
    quiet_hours: QuietHours | None = None
    # On by default: the model may declare whom or what to keep following; null turns it off.
    declarations: AttentionDeclarations | None = Field(default_factory=AttentionDeclarations)
    disposition: TurnDisposition | None = None

    @field_validator("keywords")
    @classmethod
    def valid_keywords(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("keywords must be nonempty after stripping whitespace")
        if len(stripped) != len(set(stripped)):
            raise ValueError("keywords must not repeat")
        return stripped

    @field_validator("other_bot_ids")
    @classmethod
    def valid_other_bot_ids(cls, values: list[str]) -> list[str]:
        if any(re.fullmatch(r"[a-z][a-z0-9_-]*:[^:\s/\\]+", value) is None for value in values):
            raise ValueError("other_bot_ids must contain platform:account identities")
        return values

    @model_validator(mode="after")
    def idle_within_max(self) -> Attention:
        if self.direct_idle_seconds > self.direct_max_seconds:
            raise ValueError("direct_idle_seconds must not exceed direct_max_seconds")
        if self.named_idle_seconds > self.named_max_seconds:
            raise ValueError("named_idle_seconds must not exceed named_max_seconds")
        if self.focus_idle_seconds > self.focus_max_seconds:
            raise ValueError("focus_idle_seconds must not exceed focus_max_seconds")
        if self.ambient_min_interval_seconds > self.ambient_max_interval_seconds:
            raise ValueError("ambient_min_interval_seconds must not exceed ambient_max_interval_seconds")
        return self


# Participation presets for the panel's wake level; each sets only these attention fields.
# Answering @, replies and follow-ups works the same at every level.
WAKE_LEVELS: dict[str, dict[str, float | int]] = {
    'active': {'ambient_min_interval_seconds': 600.0, 'ambient_max_interval_seconds': 2400.0,
               'speech_burst': 3, 'speech_interval_seconds': 120.0},
    'moderate': {'ambient_min_interval_seconds': 1800.0, 'ambient_max_interval_seconds': 7200.0,
                 'speech_burst': 3, 'speech_interval_seconds': 180.0},
    'quiet': {'ambient_min_interval_seconds': 5400.0, 'ambient_max_interval_seconds': 21600.0,
              'speech_burst': 2, 'speech_interval_seconds': 300.0},
}


def wake_level(attention: Attention, *, joining: bool = False) -> str | None:
    """The preset the attention fields match; None for hand-tuned values.

    A chat that only answers calls has no level unless ``joining`` asks which one it would join in at.
    """
    if attention.only_direct and not joining:
        return None
    for level, values in WAKE_LEVELS.items():
        if all(getattr(attention, field) == value for field, value in values.items()):
            return level
    return None


class Participation(BaseModel):
    """Chosen when a chat is added or tried: answer calls only, or also join in at a wake level.

    ``level`` None keeps the attention fields other than ``only_direct``.
    """
    model_config = STRICT

    only_direct: bool = True
    level: Literal['active', 'moderate', 'quiet'] | None = 'moderate'

    def attention(self) -> dict[str, float | int | bool]:
        return {**({} if self.level is None else WAKE_LEVELS[self.level]), 'only_direct': self.only_direct}


class ScenePersona(BaseModel):
    model_config = STRICT

    persona_aliases: list[str]
    relationships: dict[str, str]
    behavior_addendum: str | None

    @field_validator("persona_aliases")
    @classmethod
    def nonblank_persona_aliases(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("persona_aliases must not contain blank entries")
        return values

    @field_validator("relationships")
    @classmethod
    def valid_relationships(cls, values: dict[str, str]) -> dict[str, str]:
        for qq, description in values.items():
            if re.fullmatch(r"[a-z][a-z0-9_-]*:[^:\s/\\]+", qq) is None:
                raise ValueError(f"relationships key must be a platform:account identity: {qq!r}")
            if not description.strip():
                raise ValueError(f"relationships[{qq!r}] must not be blank")
        return values

    @field_validator("behavior_addendum")
    @classmethod
    def nonblank_behavior_addendum(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("behavior_addendum must not be blank")
        return value


class SceneSettings(ScenePersona):
    replay_web: Path | None = None
    replay_images: Path | None = None
    chat_control_roles: list[ScheduleRole] = Field(default_factory=lambda: ["owner", "admin", "group_manager"])

    @field_validator("chat_control_roles")
    @classmethod
    def distinct_control_roles(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("chat_control_roles must not repeat")
        return values

    permissions: IdentitySettings | None = None
    # Explicit IANA override for this scene; None uses the root timezone.
    timezone: str | None = None
    persona_aliases: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)
    behavior_addendum: str | None = None
    persona: Path
    voice_mode: Literal["direct"] = "direct"
    attention: Attention = Field(default_factory=Attention)
    schedules: ScheduleSettings = Field(default_factory=ScheduleSettings)
    tasks: TaskSettings = Field(default_factory=TaskSettings)
    learning: LearningSettings | None = None
    proactive: Proactive | None = None
    transcribe_audio: bool = False
    # Plugins enabled in this scene; each must be loaded by root ``plugins``.
    plugins: list[str] = Field(default_factory=list)
    # The enabled plugin that recalls memory for this scene instead of the native memory; None keeps native.
    memory_plugin: str | None = None
    # The enabled plugin that writes this scene's compaction recaps; None keeps the native recap.
    recap_plugin: str | None = None
    # Scene aliases, relationships and addendum of roles not in use here, by role id; switching back restores them.
    inactive_personas: dict[str, ScenePersona] = Field(default_factory=dict)

    @model_validator(mode="after")
    def proactive_requirements(self) -> SceneSettings:
        if self.proactive is None:
            return self
        quiet = self.attention.quiet_hours
        if quiet is not None:
            def intervals(start: WallTime, end: WallTime) -> list[tuple[int, int]]:
                a = start.hour * 3600 + start.minute * 60 + start.second
                b = end.hour * 3600 + end.minute * 60 + end.second
                return [(a, b)] if a < b else [(a, 86400), (0, b)]

            active = intervals(self.proactive.start, self.proactive.end)
            silent = intervals(quiet.start, quiet.end)
            available = sum(b - a - sum(max(0, min(b, d) - max(a, c)) for c, d in silent)
                            for a, b in active)
            if available == 0:
                raise ValueError("proactive active hours are entirely covered by quiet_hours")
        return self

    @field_validator("timezone")
    @classmethod
    def valid_scene_timezone(cls, value: str | None) -> str | None:
        return None if value is None else _valid_timezone(value)

    @field_validator("plugins")
    @classmethod
    def distinct_plugins(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("plugins must not repeat a name")
        return value

    @model_validator(mode="after")
    def memory_plugins_enabled(self) -> SceneSettings:
        for name in ("memory_plugin", "recap_plugin"):
            if getattr(self, name) is not None and getattr(self, name) not in self.plugins:
                raise ValueError(f"{name} must be one of this scene's plugins")
        return self
