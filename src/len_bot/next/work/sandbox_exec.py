"""Process starter inside one local task sandbox, the counterpart of ``docker exec``.

bwrap runs this file as the sandbox's only program. The host sends one JSON
message per request on an inherited SOCK_SEQPACKET socket: ``spawn`` carries
the program's stdin, stdout and stderr as SCM_RIGHTS descriptors, ``signal``
names a started program. Replies are ``ready``, ``started``, ``failed`` and
``exited``. When the host socket closes, every started process group is killed
and this process exits, which ends the sandbox. Uses only the standard library.
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

MAX_MESSAGE_BYTES = 1024 * 1024
LIMITS = {"file_bytes": resource.RLIMIT_FSIZE, "data_bytes": resource.RLIMIT_DATA,
          "processes": resource.RLIMIT_NPROC, "open_files": resource.RLIMIT_NOFILE}


def send(control: socket.socket, body: dict) -> None:
    control.sendmsg([json.dumps(body, ensure_ascii=False).encode()])


def main() -> None:
    control = socket.socket(fileno=int(sys.argv[1]))
    for name, value in json.loads(sys.argv[2]).items():
        resource.setrlimit(LIMITS[name], (value, value))
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
