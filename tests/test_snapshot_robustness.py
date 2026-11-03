"""Snapshots of instances with top-level links."""
import os
from pathlib import Path

import pytest

from len_bot.next.maintenance.snapshot import create, restore

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='symbolic links need privileges on Windows')


def test_restore_puts_back_symbolic_links_directly_in_the_instance_root(tmp_path):
    root, shared = tmp_path / 'instance', tmp_path / 'shared-logs'
    root.mkdir()
    shared.mkdir()
    (root / 'lenbot.config.json').write_text('{}')
    (root / 'logs').symlink_to(shared)
    (root / 'plugins').symlink_to('../missing-shared')
    (root / 'data').mkdir()
    (root / 'data' / 'note.txt').write_text('before')
    snapshot = tmp_path / 'backups' / 's1'
    create([str(root)], snapshot)

    (root / 'lenbot.config.json').write_text('{"broken": true}')
    (root / 'logs').unlink()
    (root / 'logs').mkdir()
    (root / 'data' / 'note.txt').write_text('after')
    restore(root, snapshot)

    assert (root / 'lenbot.config.json').read_text() == '{}'
    assert (root / 'logs').is_symlink() and os.readlink(root / 'logs') == str(shared)
    assert (root / 'plugins').is_symlink() and os.readlink(root / 'plugins') == '../missing-shared'
    assert (root / 'data' / 'note.txt').read_text() == 'before'
    assert list(shared.iterdir()) == []
    assert not any(path.name.endswith('.lenbot-restoring') for path in tmp_path.iterdir())
