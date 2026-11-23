"""Small JSON business values in one plugin's own data directory."""

from contextlib import closing, contextmanager
import json
from pathlib import Path
import threading

from pydantic import ConfigDict, JsonValue, TypeAdapter

from ..storage.schema import FORMAT_RESET, require_columns, stored_state
from ..storage.sqlite import connect


JSON = TypeAdapter(JsonValue, config=ConfigDict(strict=True, allow_inf_nan=False))
APPLICATION_ID = 0x4C424B56  # "LBKV"
FORMAT_VERSION = 1
SCHEMA = "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
_VERIFIED_LOCK = threading.Lock()
_VERIFIED: dict[tuple[Path, str], tuple[tuple[int, int, int, int, bytes, int, int], int]] = {}
_VERIFIED_LIMIT = 256


def _file_signature(path: Path) -> tuple[int, int, int, int, bytes, int, int] | None:
    try:
        main = path.stat()
        if main.st_size == 0:
            return None
        with path.open("rb") as stream:
            header = stream.read(100)
    except FileNotFoundError:
        return None
    try:
        wal = path.with_name(path.name + "-wal").stat()
        wal_size, wal_mtime = wal.st_size, wal.st_mtime_ns
    except FileNotFoundError:
        wal_size, wal_mtime = -1, -1
    return (main.st_dev, main.st_ino, main.st_size, main.st_mtime_ns, header, wal_size, wal_mtime)


class PluginKV:
    def __init__(self, directory: Path):
        self.path = directory / "kv.sqlite3"

    @contextmanager
    def connection(self, key: str):
        if not key.strip():
            raise ValueError("插件 KV key 不能为空")
        resolved = self.path.resolve()
        cache_key = (resolved, SCHEMA)
        signature = _file_signature(resolved)
        with _VERIFIED_LOCK:
            cached = _VERIFIED.get(cache_key)
        verified = cached is not None and signature is not None and cached[0] == signature
        identity: tuple[int, int] = (APPLICATION_ID, FORMAT_VERSION)
        if not verified:
            # Opening read-write switches the file to WAL, so a file of another format is refused before that.
            state = stored_state(self.path)
            identity = (0, 0) if state is None else state[:2]
            if identity not in {(0, 0), (APPLICATION_ID, FORMAT_VERSION)}:
                raise ValueError(f"{self.path} 不是当前格式的插件 KV：application_id={identity[0]}, format={identity[1]}。{FORMAT_RESET}")
        with closing(connect(self.path)) as db, db:
            if not verified:
                if identity == (0, 0):
                    # A new file, or one written before the format was marked; the table shape is the same.
                    db.execute(SCHEMA)
                require_columns(db, SCHEMA, path=self.path, label='插件 KV', version=FORMAT_VERSION)
                if identity == (0, 0):
                    db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    db.execute(f"PRAGMA user_version={FORMAT_VERSION}")
                schema_version = db.execute("PRAGMA schema_version").fetchone()[0]
            else:
                schema_version = db.execute("PRAGMA schema_version").fetchone()[0]
                if schema_version != cached[1]:
                    require_columns(db, SCHEMA, path=self.path, label='插件 KV', version=FORMAT_VERSION)
            yield db
        new_signature = _file_signature(resolved)
        if new_signature is not None:
            with _VERIFIED_LOCK:
                if len(_VERIFIED) >= _VERIFIED_LIMIT and cache_key not in _VERIFIED:
                    _VERIFIED.clear()
                _VERIFIED[cache_key] = (new_signature, schema_version)

    def get(self, key: str, default: JsonValue) -> JsonValue:
        with self.connection(key) as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else JSON.validate_json(row[0])

    def set(self, key: str, value: JsonValue) -> None:
        data = json.dumps(JSON.validate_python(value), ensure_ascii=False, allow_nan=False)
        with self.connection(key) as db:
            db.execute("INSERT INTO kv(key,value) VALUES (?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, data))

    def delete(self, key: str) -> bool:
        with self.connection(key) as db:
            return db.execute("DELETE FROM kv WHERE key=?", (key,)).rowcount == 1
