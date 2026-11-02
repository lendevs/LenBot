"""Root configuration sources of earlier formats, brought to the current one step by step."""

from __future__ import annotations

import copy


def _format_1_to_2(source: dict) -> dict:
    # Format 2 adds Telegram and Feishu; real sending is named for all platforms instead of OneBot.
    if source.get("delivery") == "onebot":
        source["delivery"] = "live"
    source["config_version"] = 2
    return source


def _format_2_to_3(source: dict) -> dict:
    # Format 3 adds owner private chats and the focus limit for unanswered replies; both have defaults.
    source["config_version"] = 3
    return source


STEPS = {1: _format_1_to_2, 2: _format_2_to_3}


def migrate_source(source: dict, target: int) -> dict:
    """A copy of ``source`` in format ``target``; a file without the field is format 1."""
    version = source.get("config_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"配置格式 {version!r} 无效，应为 1 到 {target} 的整数")
    if version > target:
        raise ValueError(f"配置格式是 {version}，由更新版本的 LenBot 写入；当前版本使用格式 {target}")
    migrated = copy.deepcopy(source)
    while version < target:
        migrated = STEPS[version](migrated)
        version = migrated["config_version"]
    return migrated
