"""Plugin events and model-call queries; scene consumption stays in the chat transaction."""

from __future__ import annotations

import json
from typing import Literal, TYPE_CHECKING

from ..storage.codec import encode

if TYPE_CHECKING:
    from ..storage.store import Store


SCHEMA = """
CREATE TABLE plugin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scene TEXT NOT NULL, plugin TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('event','reply')),
    content TEXT NOT NULL, created REAL NOT NULL, delivered_at REAL
);
CREATE INDEX plugin_events_pending ON plugin_events(scene,id) WHERE delivered_at IS NULL;
CREATE TABLE plugin_memory_progress (
    scene TEXT NOT NULL, plugin TEXT NOT NULL, through_seq INTEGER NOT NULL, updated REAL NOT NULL,
    PRIMARY KEY(scene, plugin)
);
"""


class PluginStore:
    def __init__(self, store: Store):
        self.db, self.now = store.db, store.now

    def add_plugin_event(self, scene: str, plugin: str, kind: Literal["event", "reply"], content: str) -> int:
        with self.db:
            return self.db.execute(
                "INSERT INTO plugin_events(scene,plugin,kind,content,created) VALUES (?,?,?,?,?)",
                (scene, plugin, kind, content, self.now()),
            ).lastrowid

    def pending_plugin_events(self, scene: str, *, include_events: bool = True) -> list[tuple[int, str]]:
        return [(row[0], row[1]) for row in self.db.execute(
            "SELECT id,content FROM plugin_events WHERE scene=? AND delivered_at IS NULL "
            "AND (? OR kind='reply') ORDER BY id", (scene, include_events))]

    def plugin_wake_pending(self, scene: str) -> bool:
        """Only ``event`` rows wake the mind; ``reply`` rows wait for the next turn."""
        return self.db.execute(
            "SELECT 1 FROM plugin_events WHERE scene=? AND delivered_at IS NULL AND kind='event' LIMIT 1",
            (scene,)).fetchone() is not None

    def plugin_events(self, scene: str, *, limit: int = 20) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT id,plugin,kind,content,created,delivered_at FROM plugin_events "
            "WHERE scene=? ORDER BY id DESC LIMIT ?", (scene, limit))]

    def report_memory_progress(self, scene: str, plugin: str, message_id: str) -> int:
        """Record that ``plugin`` has processed this scene's messages through ``message_id``; never moves back."""
        row = self.db.execute("SELECT seq FROM messages WHERE scene=? AND json_extract(body,'$.id')=?",
                              (scene, message_id)).fetchone()
        if row is None:
            raise ValueError(f"场景 {scene} 没有消息 {message_id}")
        with self.db:
            self.db.execute(
                "INSERT INTO plugin_memory_progress(scene,plugin,through_seq,updated) VALUES (?,?,?,?) "
                "ON CONFLICT(scene,plugin) DO UPDATE SET through_seq=MAX(through_seq,excluded.through_seq),"
                "updated=excluded.updated", (scene, plugin, row[0], self.now()))
        return row[0]

    def memory_progress(self, scene: str, plugin: str) -> int | None:
        row = self.db.execute("SELECT through_seq FROM plugin_memory_progress WHERE scene=? AND plugin=?",
                              (scene, plugin)).fetchone()
        return None if row is None else row[0]

    def start_plugin_call(self, scene: str, plugin: str, role: str, request: dict) -> int:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO model_calls(scene,plugin,role,started,request) VALUES (?,?,?,?,?)",
                (scene, plugin, role, self.now(), encode(request)),
            )
        return cursor.lastrowid

    def plugin_calls(self, plugin: str, limit: int = 20) -> list[dict]:
        return [{**dict(row), "usage": None if row["usage"] is None else json.loads(row["usage"]),
                 "tokens": None if row["tokens"] is None else json.loads(row["tokens"])}
                for row in self.db.execute(
                    "SELECT id,scene,role,started,ended,usage,tokens,error FROM model_calls "
                    "WHERE plugin=? ORDER BY id DESC LIMIT ?", (plugin, limit))]

    def recover_plugin_calls(self) -> None:
        with self.db:
            self.db.execute("UPDATE model_calls SET ended=?,error=? WHERE plugin IS NOT NULL AND ended IS NULL",
                            (self.now(), "宿主在插件模型请求完成前结束；未重发。"))
