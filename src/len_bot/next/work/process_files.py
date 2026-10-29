"""Regular stderr files and the process starter signature for task subprocesses."""

from collections.abc import Awaitable, Callable
import os
from pathlib import Path
import stat
from typing import Any
from ..storage.files import NONBLOCK, open_no_follow

# Same call shape as asyncio.create_subprocess_exec; returns a Process-like object.
Launch = Callable[..., Awaitable[Any]]


def open_stderr(path: Path):
    descriptor = open_no_follow(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"Task stderr must be a regular file: {path}")
        os.set_blocking(descriptor, True)
        return os.fdopen(descriptor, "ab")
    except BaseException:
        os.close(descriptor)
        raise
