"""Regular stderr files and the process starter signature for task subprocesses."""

from collections.abc import Awaitable, Callable
import os
from pathlib import Path
import stat
from typing import Any

# Same call shape as asyncio.create_subprocess_exec; returns a Process-like object.
Launch = Callable[..., Awaitable[Any]]


def open_stderr(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"Task stderr must be a regular file: {path}")
        os.set_blocking(descriptor, True)
        return os.fdopen(descriptor, "ab")
    except BaseException:
        os.close(descriptor)
        raise
