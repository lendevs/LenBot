"""Offline local index upgrades, without model calls or Markdown changes."""

from contextlib import ExitStack
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

from ..config import load_instance_config
from ..instance_lock import instance_lock
from ..memory.local import (FORMAT_VERSION, SUMMARY_FILES, SUMMARY_SCHEMA, _APPLICATION_ID, _INDEX_NAME,
                            LocalMemory, scope_directory, _source_text)
from ..memory.sections import SECTION_STATEMENTS, put_sections
from ..memory.service import LocalMemoryConfig
from .migrations import Format, upgrade
from ..runtime.logs import run_maintenance


def _summary_clock(directory: Path):
    def step(db: sqlite3.Connection):
        db.execute(SUMMARY_SCHEMA)

        def clear() -> None:
            for category in ('public', 'scenes'):
                for name in SUMMARY_FILES:
                    for summary in (directory / category).rglob(name):
                        summary.unlink()
        return clear
    return step


def _section_index(directory: Path):
    def step(db: sqlite3.Connection):
        # Old vectors describe whole files. Section vectors require an explicit
        # rebuild with the configured model after this offline text migration.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_vec'").fetchone():
            LocalMemory._load_vec(db)
            db.execute('DROP TABLE memory_vec')
        db.execute('DELETE FROM memory_vector_binding')
        db.execute('DROP TABLE memory_fts')
        for statement in SECTION_STATEMENTS:
            db.execute(statement)
        for scope, path, indexed in db.execute('SELECT scope,path,content FROM memory_files').fetchall():
            base = directory / 'public' if scope == 'public' else directory / 'scenes' / scope_directory(scope)
            parts = path.split('/')
            source = base.joinpath(*(quote(part, safe='') for part in parts)) if sys.platform == 'win32' else base / path
            content = _source_text(source)
            if content.casefold() != indexed:
                raise ValueError(f'local memory Markdown/index mismatch at {scope}/{path}; rebuild the memory index')
            put_sections(db, scope, path, content)
    return step


def migrate(directory: Path, *, backup: bool = True) -> Path | None:
    index = directory / _INDEX_NAME
    if not index.exists():
        print(f'{directory}: no local memory index to migrate')
        return None
    copy = upgrade(index, Format('本地记忆索引', _APPLICATION_ID, FORMAT_VERSION, 2,
                                {2: _summary_clock(directory), 3: _section_index(directory)}),
                   backup=backup)
    print(f'{index}: local memory format {FORMAT_VERSION}'
          + ('' if copy is None else f'; input-format copy: {copy}'))
    return copy


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit('Local memory migration takes no arguments; stop the instance and run from its root')
    root = Path.cwd()
    with ExitStack() as locks:
        locks.enter_context(instance_lock(root))
        trials = sorted((root / '.runtime' / 'chat-tests').glob('*/lenbot.config.json'))
        for path in trials:
            locks.enter_context(instance_lock(path.parent))
        directories = set()
        for instance in (root, *(path.parent for path in trials)):
            config = load_instance_config(instance)
            if isinstance(config.memory, LocalMemoryConfig):
                directories.add(config.memory.local.directory)
        for directory in sorted(directories):
            migrate(directory)


if __name__ == '__main__':
    run_maintenance(main, 'migrate_local_memory')
