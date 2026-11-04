"""Process starter inside one local task sandbox, the counterpart of ``docker exec``.

bwrap runs this file as the sandbox's only program. The host sends one JSON
message per request on an inherited SOCK_SEQPACKET socket: ``spawn`` carries
the program's stdin, stdout and stderr as SCM_RIGHTS descriptors, ``signal``
names a started program. Replies are ``ready``, ``started``, ``failed`` and
``exited``. When the host socket closes, every started process group is killed
and this process exits, which ends the sandbox. Uses only the standard library.

``RLIMIT_DATA`` does not count shared anonymous mappings (``mmap.mmap(-1, n)``,
``MAP_SHARED|MAP_ANONYMOUS``), and ``RLIMIT_AS`` cannot stand in for it: Chromium
reserves far more address space than any sane memory limit. Without a cgroup, a
``memory_bytes`` limit therefore starts a watchdog thread that sums the proportional
anonymous and shared memory of every process in the sandbox's PID namespace
and ends the whole sandbox, exiting with ``MEMORY_EXIT``, once the sum exceeds the limit.
"""

from __future__ import annotations

import json
import os
import resource
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time

MAX_MESSAGE_BYTES = 1024 * 1024
LIMITS = {"file_bytes": resource.RLIMIT_FSIZE, "data_bytes": resource.RLIMIT_DATA,
          "processes": resource.RLIMIT_NPROC, "open_files": resource.RLIMIT_NOFILE}
MEMORY_EXIT = 137
MEMORY_POLL_SECONDS = 0.1


def sandbox_memory() -> int:
    """Bytes of anonymous and shared memory in use by every process of this PID namespace.

    Shared pages are divided among the processes mapping them (``Pss_Anon`` and ``Pss_Shmem`` in
    ``smaps_rollup``), so Chromium's cross-process buffers are not counted once per process; file-backed
    pages (libraries, the task runtime) are not counted at all.
    """
    total = 0
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/smaps_rollup") as rollup:
                for line in rollup:
                    if line.startswith(("Pss_Anon:", "Pss_Shmem:")):
                        total += int(line.split()[1]) * 1024
        except OSError:
            continue  # the process exited, or is a kernel thread without a rollup
    return total


def watch_memory(limit: int) -> None:
    while True:
        time.sleep(MEMORY_POLL_SECONDS)
        used = sandbox_memory()
        if used > limit:
            sys.stderr.write(f"sandbox memory limit exceeded: {used} bytes in use, limit {limit}\n")
            sys.stderr.flush()
            os._exit(MEMORY_EXIT)  # bwrap's init then exits and the namespace kills every program


def send(control: socket.socket, body: dict) -> None:
    control.sendmsg([json.dumps(body, ensure_ascii=False).encode()])


def main() -> None:
    control = socket.socket(fileno=int(sys.argv[1]))
    limits = json.loads(sys.argv[2])
    memory = limits.pop("memory_bytes", None)
    for name, value in limits.items():
        resource.setrlimit(LIMITS[name], (value, value))
    if memory is not None:
        threading.Thread(target=watch_memory, args=(memory,), daemon=True).start()
    children: dict[int, subprocess.Popen] = {}
    watching = selectors.DefaultSelector()
    watching.register(control, selectors.EVENT_READ)
    send(control, {"ready": True})

    def stop_all(*_):
        for child in children.values():
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for child in children.values():
            child.wait()
        os._exit(0)

    signal.signal(signal.SIGTERM, stop_all)
    while True:
        for key, _ in watching.select():
            if key.fileobj is not control:
                ident, child, pidfd = key.data
                watching.unregister(pidfd)
                os.close(pidfd)
                send(control, {"exited": ident, "status": child.wait()})
                del children[ident]
                continue
            try:
                data, descriptors, _, _ = socket.recv_fds(control, MAX_MESSAGE_BYTES, 3)
            except OSError:
                data, descriptors = b"", []
            if not data:
                stop_all()
            request = json.loads(data)
            if "signal" in request:
                child = children.get(request["signal"])
                if child is not None:
                    try:
                        os.killpg(child.pid, request["number"])
                    except ProcessLookupError:
                        pass
                continue
            ident = request["spawn"]
            try:
                if len(descriptors) != 3:
                    raise ValueError(f"spawn needs stdin, stdout and stderr descriptors, got {len(descriptors)}")
                child = subprocess.Popen(request["argv"], cwd=request["cwd"], env=request["env"],
                                         stdin=descriptors[0], stdout=descriptors[1], stderr=descriptors[2],
                                         start_new_session=True)
            except Exception as error:
                send(control, {"failed": ident, "error": f"{type(error).__name__}: {error}"})
            else:
                children[ident] = child
                pidfd = os.pidfd_open(child.pid)
                watching.register(pidfd, selectors.EVENT_READ, (ident, child, pidfd))
                send(control, {"started": ident, "pid": child.pid})
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)


if __name__ == "__main__":
    main()
