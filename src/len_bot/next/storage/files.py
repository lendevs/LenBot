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


def is_link(info: os.stat_result) -> bool:
    """A symbolic link, or on Windows any reparse point such as a junction."""
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
        if is_link(os.lstat(path)):
            raise OSError(errno.ELOOP, 'Too many levels of symbolic links', str(path))
    except FileNotFoundError:
        if not flags & os.O_CREAT:
            raise
    descriptor = os.open(path, flags | os.O_BINARY, mode)
    try:
        opened, named = os.fstat(descriptor), os.lstat(path)
        if is_link(named) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise OSError(errno.ELOOP, 'Too many levels of symbolic links', str(path))
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


# Windows cannot open a directory as a descriptor or resolve names relative to one.
DESCRIPTORS = os.open in os.supports_dir_fd and hasattr(os, 'O_DIRECTORY')


class Directory:
    """One directory reached without following links, for walking trees a task can write to.

    POSIX holds a descriptor, so later steps resolve names against the directory actually opened.
    Windows holds the path and refuses a link or reparse point at every step by name.
    """

    def __init__(self, path: Path, descriptor: int | None):
        self.path, self.descriptor = path, descriptor

    @classmethod
    def open(cls, path: Path) -> 'Directory':
        if DESCRIPTORS:
            return cls(path, os.open(path, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW))
        _require_directory(os.lstat(path), path)
        return cls(path, None)

    def child(self, name: str) -> 'Directory':
        if self.descriptor is not None:
            return Directory(self.path / name, os.open(name, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW,
                                                       dir_fd=self.descriptor))
        path = self.path / name
        _require_directory(os.lstat(path), path)
        return Directory(path, None)

    def names(self) -> list[str]:
        with os.scandir(self.path if self.descriptor is None else self.descriptor) as children:
            return [child.name for child in children]

    def stat(self, name: str | None = None) -> os.stat_result:
        """The entry ``name`` without following it, or the directory itself."""
        if self.descriptor is not None:
            return os.fstat(self.descriptor) if name is None else os.stat(name, dir_fd=self.descriptor,
                                                                          follow_symlinks=False)
        return os.lstat(self.path if name is None else self.path / name)

    def open_file(self, name: str, flags: int, mode: int = 0o777) -> int:
        if self.descriptor is not None:
            return os.open(name, flags | NOFOLLOW, mode, dir_fd=self.descriptor)
        return open_no_follow(self.path / name, flags, mode)

    def unlink(self, name: str) -> None:
        if self.descriptor is not None:
            os.unlink(name, dir_fd=self.descriptor)
        else:
            os.unlink(self.path / name)

    def close(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def __enter__(self) -> 'Directory':
        return self

    def __exit__(self, *_) -> None:
        self.close()


def _require_directory(info: os.stat_result, path: Path) -> None:
    if is_link(info):
        raise OSError(errno.ELOOP, 'Too many levels of symbolic links', str(path))
    if not stat.S_ISDIR(info.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, 'Not a directory', str(path))


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
