"""open_no_follow refuses a link as the last component on every platform and opens files in binary mode."""

import os
from pathlib import Path

import pytest

from len_bot.next.storage.files import open_no_follow


def test_regular_file_opens_and_keeps_line_endings(tmp_path: Path) -> None:
    path = tmp_path / 'data.txt'
    path.write_bytes(b'a\r\nb\n')
    with os.fdopen(open_no_follow(path, os.O_RDONLY), 'rb') as source:
        assert source.read() == b'a\r\nb\n'


def test_created_file_is_new_and_a_missing_one_is_not_created_without_o_creat(tmp_path: Path) -> None:
    created = tmp_path / 'new.bin'
    os.close(open_no_follow(created, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    assert created.is_file()
    with pytest.raises(FileNotFoundError):
        open_no_follow(tmp_path / 'missing', os.O_RDONLY)


def test_link_as_last_component_is_refused(tmp_path: Path) -> None:
    target = tmp_path / 'target.txt'
    target.write_text('secret', encoding='utf-8')
    link = tmp_path / 'link.txt'
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f'symbolic links unavailable: {error}')
    with pytest.raises(OSError):
        open_no_follow(link, os.O_RDONLY)
    with pytest.raises(OSError):
        open_no_follow(link, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    assert target.read_text(encoding='utf-8') == 'secret'
