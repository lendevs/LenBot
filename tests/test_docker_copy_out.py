"""Deliveries read through ``docker cp`` accept exactly one regular file within the size limit."""

import io
import tarfile

import pytest

from len_bot.next.work.sandbox import SandboxError, extract_regular_member


def archive(*members: tuple[str, bytes | None, bytes]) -> io.BytesIO:
    """Members as (name, content or None, type); content None makes a link or directory."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as output:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.SYMTYPE:
                info.linkname = '/etc/passwd'
            info.size = len(content or b'')
            output.addfile(info, io.BytesIO(content) if content else None)
    buffer.seek(0)
    return buffer


def test_one_regular_file_is_copied() -> None:
    output = io.BytesIO()
    assert extract_regular_member(archive(('report.txt', b'done\r\n', tarfile.REGTYPE)), output, 100) == 6
    assert output.getvalue() == b'done\r\n'


@pytest.mark.parametrize('members', [
    [('report.txt', None, tarfile.SYMTYPE)],
    [('out', None, tarfile.DIRTYPE), ('out/report.txt', b'x', tarfile.REGTYPE)],
    [('report.txt', b'x', tarfile.REGTYPE), ('extra.txt', b'y', tarfile.REGTYPE)],
    [('report.txt', b'x' * 101, tarfile.REGTYPE)],
])
def test_links_directories_extra_members_and_large_files_are_refused(members) -> None:
    with pytest.raises(SandboxError):
        extract_regular_member(archive(*members), io.BytesIO(), 100)


def test_an_empty_stream_is_refused() -> None:
    with pytest.raises(SandboxError):
        extract_regular_member(io.BytesIO(), io.BytesIO(), 100)
