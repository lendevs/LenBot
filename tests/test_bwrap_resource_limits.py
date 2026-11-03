"""Task memory is bounded in the bubblewrap sandbox: /tmp, /dev and /dev/shm."""

from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from len_bot.next.work.bwrap import BwrapSandbox, _check_settings
from test_task_lifecycle import SCENE, bwrap_usable, task_runtime

MIB = 1024 * 1024
pytestmark = pytest.mark.skipif(not bwrap_usable(), reason='bwrap cannot create user namespaces here')


async def run(tmp_path, *program: str, memory: int | None = None, tmpfs: int | None = None):
    settings = _check_settings(Path(shutil.which('bwrap')), task_runtime(tmp_path), tmp_path / 'tasks')
    settings = replace(settings, memory_bytes=memory or settings.memory_bytes, tmpfs_bytes=tmpfs or settings.tmpfs_bytes)
    sandbox = BwrapSandbox(settings)
    handle = await sandbox.ensure(SCENE, '1')
    try:
        return await sandbox._run(handle, sandbox.python, '-I', '-c', *program)
    finally:
        await sandbox.stop(handle)


@pytest.mark.asyncio
async def test_dev_shm_is_bounded_by_tmpfs_size_and_the_rest_of_dev_is_read_only(tmp_path):
    result = await run(tmp_path, f'''
import os
def fill(path, size):
    try:
        with open(path, "wb") as file:
            for _ in range(size // {MIB}):
                file.write(b"x" * {MIB})
            file.flush()
        return "written"
    except OSError as error:
        return type(error).__name__ + ":" + str(error.errno)
print("tmp", fill("/tmp/fill", 80 * {MIB}))
print("shm", fill("/dev/shm/fill", 80 * {MIB}))
print("dev", fill("/dev/fill", {MIB}))
print("opt", fill("/opt/fill", {MIB}))
''', tmpfs=32 * MIB)
    assert result.returncode == 0, result.stderr
    # ENOSPC on the sized tmpfs mounts, EROFS everywhere else.
    assert dict(line.split(' ', 1) for line in result.stdout.splitlines()) == {
        'tmp': 'OSError:28', 'shm': 'OSError:28', 'dev': 'OSError:30', 'opt': 'OSError:30'}
