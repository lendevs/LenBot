"""Host-wide simulated sending: turns still run and are recorded, nothing reaches QQ.

The switch is kept in `state/send-hold.json` so a restart does not resume real sending by itself.
An unreadable file counts as on: an unintended message to a group is the worse mistake.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .logs import log_event

logger = logging.getLogger(__name__)


class SendHold:
    def __init__(self, root: Path | None):
        self.path: Path | None = None if root is None else root / "state" / "send-hold.json"
        self.enabled = False
        if self.path is not None and self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(saved.get("enabled"), bool):
                    raise ValueError("enabled must be a boolean")
                self.enabled = saved["enabled"]
            except (OSError, ValueError, AttributeError) as error:
                logger.warning("模拟发送开关读取失败，按开启处理：%s: %s", type(error).__name__, error)
                self.enabled = True

    def set(self, enabled: bool, *, at: float) -> None:
        if self.path is not None:
            temporary = self.path.with_suffix(".tmp")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"enabled": enabled, "changed_at": at}) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        self.enabled = enabled
        log_event(logger, "send_hold", enabled=enabled, at=at)
