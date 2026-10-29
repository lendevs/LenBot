"""Durable replacement of instance text files."""

import errno
import os
from pathlib import Path
import stat
import tempfile

# Windows has neither flag; FIFOs cannot appear in its file systems, and open_no_follow checks links itself.
NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
NONBLOCK = getattr(os, 'O_NONBLOCK', 0)


def sync_directory(path: Path) -> None:
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0)
                                              & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def open_no_follow(path: Path, flags: int, mode: int = 0o777) -> int:
    """``os.open`` that refuses a symbolic link or other reparse point as the last path component.

    POSIX passes ``O_NOFOLLOW``. Windows checks the name before opening and compares the opened file
    with the name afterwards, so a link put in place between the two is refused as well; the file is
    opened in binary mode.
    """
    if NOFOLLOW:
        return os.open(path, flags | NOFOLLOW, mode)
    try:
        if _link(os.lstat(path)):
            raise OSError(errno.ELOOP, 'Too many levels of symbolic links', str(path))
    except FileNotFoundError:
        if not flags & os.O_CREAT:
            raise
    descriptor = os.open(path, flags | os.O_BINARY, mode)
    try:
        opened, named = os.fstat(descriptor), os.lstat(path)
        if _link(named) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise OSError(errno.ELOOP, 'Too many levels of symbolic links', str(path))
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def atomic_text(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.file-write-')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)
