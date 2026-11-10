"""Root configuration sources of earlier formats, brought to the current one step by step."""

from __future__ import annotations

import copy

from .chat import WAKE_LEVELS, Attention


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


def _format_3_to_4(source: dict) -> dict:
    # Format 4 drops simulated sending: a host with a platform sends to it, and scenes lose their own switch.
    if any(source.get(name) for name in ("onebot", "telegram", "feishu")):
        source["delivery"] = "live"
    for scene in source.get("scenes", {}).values():
        if isinstance(scene, dict):
            scene.pop("simulated_delivery", None)
    source["config_version"] = 4
    return source


# Wake level fields of format 4, by level.
_FORMAT_4_LEVELS = {
    "active": {"activity": 0.3, "ambient_min_interval_seconds": 60.0, "ambient_max_interval_seconds": 900.0,
               "focus_seconds": 180.0, "focus_unanswered_limit": 2},
    "moderate": {"activity": 0.15, "ambient_min_interval_seconds": 180.0, "ambient_max_interval_seconds": 1800.0,
                 "focus_seconds": 90.0, "focus_unanswered_limit": 1},
    "quiet": {"activity": 0.06, "ambient_min_interval_seconds": 600.0, "ambient_max_interval_seconds": 3600.0,
              "focus_seconds": 30.0, "focus_unanswered_limit": 1},
}
_FORMAT_4_DEFAULTS = {"activity": 0.3, "ambient_min_interval_seconds": 60.0, "ambient_max_interval_seconds": 900.0,
                      "focus_seconds": 180.0, "focus_unanswered_limit": 2, "explore_probability": 0.0}


def _format_4_to_5(source: dict) -> dict:
    # Format 5 replaces the participation score with follow-ups, interjection intervals and a speech pace.
    # A chat at a wake level moves to the same level; hand-tuned intervals and follow-up windows stay.
    for scene in source.get("scenes", {}).values():
        attention = scene.get("attention") if isinstance(scene, dict) else None
        if not isinstance(attention, dict):
            continue
        current = {**_FORMAT_4_DEFAULTS, **attention}
        level = next((name for name, values in _FORMAT_4_LEVELS.items()
                      if current["explore_probability"] == 0
                      and all(current[field] == value for field, value in values.items())), None)
        for name in ("activity", "ambient_threshold", "ambient_score_in_reason", "close_focus_on_silence",
                     "focus_unanswered_limit"):
            attention.pop(name, None)
        if level is not None:
            for name in _FORMAT_4_LEVELS[level]:
                attention.pop(name, None)
            attention.update({name: value for name, value in WAKE_LEVELS[level].items()
                              if value != Attention.model_fields[name].default})
    source["config_version"] = 5
    return source


def _format_5_to_6(source: dict) -> dict:
    # Format 6 adds the recap's own reasoning effort; leaving it out keeps the mind's quick effort.
    # It adds model_alert_failed_turns; leaving it out keeps 3.
    # It also turns persistent intents on by default. Before, null was how the panel saved the default
    # off, so it becomes the new default; from format 6 on, null is a choice to turn them off.
    blocks = [source.get("attention"), *(scene.get("attention") for scene in source.get("scenes", {}).values()
                                         if isinstance(scene, dict))]
    for attention in blocks:
        if isinstance(attention, dict) and "declarations" in attention and attention["declarations"] is None:
            del attention["declarations"]
    source["config_version"] = 6
    return source


STEPS = {1: _format_1_to_2, 2: _format_2_to_3, 3: _format_3_to_4, 4: _format_4_to_5, 5: _format_5_to_6}


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
