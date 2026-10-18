"""Task archive after a kill or power loss: the leftover WAL is folded in, not a refusal."""
import shutil
from contextlib import closing
from pathlib import Path

import pytest

from len_bot.next.maintenance.archive_tasks import stopped
from len_bot.next.storage.sqlite import connect, fold_log


def crashed_database(tmp_path: Path) -> Path:
    """A database whose last commit is only in its WAL, as an unclean stop leaves it."""
    live, path = tmp_path / 'live', tmp_path / 'state.db'
    live.mkdir()
    db = connect(live / 'state.db')
    db.execute('PRAGMA wal_autocheckpoint=0')
    with db:
        db.execute('CREATE TABLE probe(value)')
        db.execute("INSERT INTO probe VALUES ('committed before the crash')")
    for suffix in ('', '-wal', '-shm'):
        shutil.copyfile(live / f'state.db{suffix}', tmp_path / f'state.db{suffix}')
    db.close()
    return path


def test_a_leftover_log_is_folded_and_the_archive_check_passes(tmp_path):
    path = crashed_database(tmp_path)
    with pytest.raises(ValueError, match='nonempty'):
        stopped(path)
    assert fold_log(path) is True
    stopped(path)
    with closing(connect(path, immutable=True)) as db:
        assert db.execute('SELECT value FROM probe').fetchall() == [('committed before the crash',)]
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    assert fold_log(path) is False
