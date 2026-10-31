"""One-task local sandbox on Linux with bubblewrap, the counterpart of ``DockerSandbox``.

Each task gets one bwrap process with new user, mount, PID, network, IPC, UTS
and cgroup namespaces. Inside it ``sandbox_exec.py`` starts the model bridge,
the egress bridge and Pi on host request, so the three share one loopback
network and still talk to the host only through their own pipes. The sandbox
sees the system's read-only ``/usr``, a few read-only ``/etc`` entries, the
task runtime at ``/opt/lenbot``, and this task's directories at the same
container paths as the worker image.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import itertools
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import uuid

from .pi_rpc import PiRpc
from .sandbox import SandboxError, SandboxHandle, copy_regular_out, prepare_task_directories, task_identity
from ..tools.skills import Skill
from ..configuration.tasks import EgressSettings, WorkerSettings
from .worker_egress import EgressTransport
from .worker_model import WorkerModelProxy
from .worker_transport import WorkerTransport
from ..platform.identity import scene_directory
from ..runtime.logs import log_event

logger = logging.getLogger(__name__)
_WORK = Path(__file__).parent
_PROGRAMS = ("sandbox_exec.py", "worker_bridge.py", "egress_wire.py", "worker_egress_bridge.py")
_ETC = ("ssl", "ca-certificates", "pki", "fonts", "alternatives", "localtime", "ld.so.cache",
        "ld.so.conf", "ld.so.conf.d", "mime.types", "nsswitch.conf")
_SYSTEM = ("bin", "sbin", "lib", "lib32", "lib64", "libx32")
_AGENT = 10000
_HOST_PROGRAMS = "/opt/lenbot-host"
# /opt/lenbot-host/bin holds python3 and python: the host's base interpreter, with the runtime's task libraries.
_PATH = "/opt/lenbot/bin:/opt/lenbot/node/bin:/opt/lenbot-host/bin:/usr/local/bin:/usr/bin:/bin"
_PROBE = """\
import os
import tempfile
for directory in ('/workspace', '/workspace/out', '/workspace/.pi-sessions', '/home/agent', '/home/agent/.pi/agent'):
    descriptor, path = tempfile.mkstemp(prefix='.lenbot-permission-', dir=directory)
    os.close(descriptor)
    os.unlink(path)
os.listdir('/run/lenbot')
"""


@dataclass(frozen=True)
class BwrapSettings:
    bwrap_binary: Path
    task_runtime: Path
    workspace_root: Path
    runtime_root: Path
    memory_bytes: int
    pids_limit: int
    file_bytes: int
    tmpfs_bytes: int
    command_timeout_seconds: float = 30.0


def byte_size(value: str) -> int:
    """A Docker-style size such as 2g, as bytes."""
    return int(value[:-1]) * 1024 ** "kmg".index(value[-1].lower()) * 1024


class _WriteProtocol(asyncio.streams.FlowControlMixin):
    """A write pipe's protocol with the close waiter ``StreamWriter.wait_closed`` needs, as asyncio's own subprocess pipes have."""

    def __init__(self) -> None:
        super().__init__()
        self._closed = asyncio.get_running_loop().create_future()

    def connection_lost(self, exc: Exception | None) -> None:
        super().connection_lost(exc)
        if not self._closed.done():
            self._closed.set_result(None)

    def _get_close_waiter(self, stream: asyncio.StreamWriter) -> asyncio.Future:
        return self._closed


class SandboxProcess:
    """The parts of ``asyncio.subprocess.Process`` the task transports use."""

    def __init__(self, session: _Session, ident: int, stdin: asyncio.StreamWriter, stdout: asyncio.StreamReader):
        self._session, self._ident = session, ident
        self.stdin, self.stdout = stdin, stdout
        self.pid: int | None = None
        self.returncode: int | None = None
        self._exited: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    def _exit(self, status: int) -> None:
        if not self._exited.done():
            self.returncode = status
            self._exited.set_result(status)

    async def wait(self) -> int:
        return await asyncio.shield(self._exited)

    def send_signal(self, number: int) -> None:
        if self.returncode is not None:
            raise ProcessLookupError(f"sandbox process {self._ident} already exited")
        self._session.send({"signal": self._ident, "number": number})

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)


class _Session:
    """The host end of one running sandbox's control socket."""

    def __init__(self, process: asyncio.subprocess.Process, control: socket.socket):
        self.process, self.control = process, control
        self.processes: dict[int, SandboxProcess] = {}
        self.starting: dict[int, asyncio.Future[int]] = {}
        self.ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.ended: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._ids = itertools.count(1)
        self._reading = asyncio.create_task(self._read())

    def send(self, body: dict, descriptors: tuple[int, ...] = ()) -> None:
        if self.ended.done():
            raise SandboxError(f"task sandbox already ended: {self.ended.result()}")
        message = [json.dumps(body, ensure_ascii=False).encode()]
        if descriptors:
            socket.send_fds(self.control, message, list(descriptors))
        else:
            self.control.sendmsg(message)

    def _end(self, reason: str) -> None:
        if not self.ended.done():
            self.ended.set_result(reason)
        for future in (self.ready, *self.starting.values()):
            if not future.done():
                future.set_exception(SandboxError(f"task sandbox ended: {reason}"))
        for child in self.processes.values():
            child._exit(-signal.SIGKILL)

    async def _read(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                data = await loop.sock_recv(self.control, 1024 * 1024)
                if not data:
                    break
                message = json.loads(data)
                if "ready" in message:
                    self.ready.set_result(None)
                elif "started" in message:
                    starting = self.starting.pop(message["started"], None)
                    if starting is None or starting.done():
                        # The launch was cancelled before the starter answered: stop the process it left behind.
                        self.processes.pop(message["started"], None)
                        log_event(logger, "sandbox_orphan_process", level=logging.WARNING,
                                  ident=message["started"], pid=message["pid"])
                        self.send({"signal": message["started"], "number": signal.SIGKILL})
                    else:
                        starting.set_result(message["pid"])
                elif "failed" in message:
                    starting = self.starting.pop(message["failed"], None)
                    if starting is None or starting.done():
                        log_event(logger, "sandbox_unknown_failure", level=logging.WARNING,
                                  ident=message["failed"], error=message["error"])
                    else:
                        starting.set_exception(SandboxError(message["error"]))
                elif "exited" in message:
                    child = self.processes.pop(message["exited"], None)
                    if child is None:
                        log_event(logger, "sandbox_unknown_exit", level=logging.INFO,
                                  ident=message["exited"], status=message["status"])
                    else:
                        child._exit(message["status"])
                else:
                    raise SandboxError(f"unknown sandbox control message: {data[:500]!r}")
            status = await self.process.wait()
            self._end(f"bwrap exited with status {status}")
        except Exception as error:
            self._end(f"{type(error).__name__}: {error}")

    async def launch(self, *argv: str, cwd: PurePosixPath, env: dict[str, str], stdin, stdout,
                     stderr) -> SandboxProcess:
        """Start one program in the sandbox; the arguments mirror ``create_subprocess_exec``."""
        loop = asyncio.get_running_loop()
        child_stdin, host_stdin = os.pipe()
        host_stdout, child_stdout = os.pipe()
        ident = next(self._ids)
        reader = asyncio.StreamReader(limit=2 ** 26)
        # Each host end is owned by exactly one file object from here on, so a cancelled start closes it once.
        stdout_file, stdin_file = os.fdopen(host_stdout, "rb", 0), os.fdopen(host_stdin, "wb", 0)
        read_transport = write_transport = None
        try:
            read_transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), stdout_file)
            write_transport, protocol = await loop.connect_write_pipe(_WriteProtocol, stdin_file)
            child = SandboxProcess(self, ident, asyncio.StreamWriter(write_transport, protocol, None, loop), reader)
            # Registered before the request: a quick exit can be reported right after its start.
            started = self.starting[ident] = loop.create_future()
            self.processes[ident] = child
            self.send({"spawn": ident, "argv": list(argv), "cwd": str(cwd), "env": env},
                      (child_stdin, child_stdout, stderr.fileno()))
            child.pid = await started
            return child
        except BaseException:
            self.starting.pop(ident, None)
            self.processes.pop(ident, None)
            for transport, file in ((read_transport, stdout_file), (write_transport, stdin_file)):
                if transport is None:
                    file.close()
                else:
                    transport.close()
            raise
        finally:
            os.close(child_stdin)
            os.close(child_stdout)

    async def close(self, timeout: float) -> None:
        """Closing the control socket makes the starter kill every process group and exit."""
        self._reading.cancel()
        await asyncio.gather(self._reading, return_exceptions=True)
        self.control.close()
        try:
            await asyncio.wait_for(self.process.wait(), timeout)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()
        self._end("closed by host")


def _system_binds() -> list[str]:
    arguments: list[str] = []
    for name in _SYSTEM:
        path = Path("/") / name
        if path.is_symlink():
            arguments += ["--symlink", os.readlink(path), str(path)]
        elif path.is_dir():
            arguments += ["--ro-bind", str(path), str(path)]
    for name in _ETC:
        arguments += ["--ro-bind-try", f"/etc/{name}", f"/etc/{name}"]
    return arguments


class BwrapSandbox:
    """Create, use and remove one local task sandbox, keeping its files."""

    def __init__(self, settings: BwrapSettings):
        self.settings = settings
        self._sessions: dict[str, _Session] = {}
        self._version: tuple[int, ...] | None = None
        # The host interpreter's base installation, at the same path; the bridges use only the stdlib.
        base = Path(sys.base_prefix).resolve()
        self.python = str(base / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}")
        self._python_binds = [] if base == Path("/usr") else ["--ro-bind", str(base), str(base)]

    def _tmpfs_size(self) -> list[str]:
        """bwrap 0.8.0 added ``--size``; older releases get an unsized /tmp."""
        if self._version is None:
            output = subprocess.run([str(self.settings.bwrap_binary), "--version"], capture_output=True,
                                    text=True, timeout=self.settings.command_timeout_seconds).stdout
            self._version = tuple(int(part) for part in re.findall(r"\d+", output)[:3])
        return ["--size", str(self.settings.tmpfs_bytes)] if self._version >= (0, 8, 0) else []

    async def ensure(self, scene: str, task_id: str, *, skills: tuple[Skill, ...] = (),
                     input_names: tuple[str, ...] = (),
                     on_container: Callable[[str], None] | None = None) -> SandboxHandle:
        task_identity(scene, task_id)
        workspace, home, control, runtime = prepare_task_directories(
            self.settings.workspace_root, self.settings.runtime_root, scene, task_id)
        system = runtime / "system"
        system.mkdir(exist_ok=True)
        (system / "passwd").write_text(f"agent:x:{_AGENT}:{_AGENT}::/home/agent:/bin/bash\n", encoding="utf-8")
        (system / "group").write_text(f"agent:x:{_AGENT}:\n", encoding="utf-8")
        arguments = [
            str(self.settings.bwrap_binary), "--unshare-all", "--die-with-parent", "--new-session",
            "--cap-drop", "ALL", "--uid", str(_AGENT), "--gid", str(_AGENT), "--hostname", "lenbot-task",
            "--ro-bind", "/usr", "/usr", *_system_binds(), *self._python_binds,
            "--ro-bind", str(system / "passwd"), "/etc/passwd", "--ro-bind", str(system / "group"), "/etc/group",
            "--proc", "/proc", "--dev", "/dev", *self._tmpfs_size(), "--tmpfs", "/tmp",
            "--tmpfs", "/opt", "--ro-bind", str(self.settings.task_runtime), "/opt/lenbot",
            *itertools.chain.from_iterable(("--ro-bind", str(_WORK / name), f"{_HOST_PROGRAMS}/{name}")
                                           for name in _PROGRAMS),
            "--symlink", self.python, f"{_HOST_PROGRAMS}/bin/python3",
            "--symlink", self.python, f"{_HOST_PROGRAMS}/bin/python",
            "--bind", str(workspace), "/workspace", "--bind", str(home), "/home/agent",
            "--ro-bind", str(control), "/run/lenbot",
        ]
        if input_names:
            arguments += ["--ro-bind", str(runtime / "inputs"), "/inputs"]
        for skill in skills:
            if skill.source != "task":
                arguments += ["--ro-bind", str(skill.host_path), skill.container_path]
        host, inside = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        limits = {"file_bytes": self.settings.file_bytes, "data_bytes": self.settings.memory_bytes,
                  "processes": self.settings.pids_limit, "open_files": 4096}
        arguments += ["--remount-ro", "/", "--clearenv", "--setenv", "PATH", _PATH, "--chdir", "/workspace",
                      "--", self.python, "-I", f"{_HOST_PROGRAMS}/sandbox_exec.py", str(inside.fileno()),
                      json.dumps(limits)]
        name = f"lenbot-bwrap-{uuid.uuid4().hex}"
        if on_container is not None:
            on_container(name)
        stderr = open(runtime / "sandbox.stderr", "ab")
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=stderr,
                pass_fds=(inside.fileno(),), env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        except BaseException:
            host.close()
            raise
        finally:
            inside.close()
            stderr.close()
        host.setblocking(False)
        session = _Session(process, host)
        self._sessions[name] = session
        handle = SandboxHandle(scene, task_id, name, workspace, home, control)
        try:
            await asyncio.wait_for(asyncio.shield(session.ready), self.settings.command_timeout_seconds)
            output = await self._run(handle, self.python, "-I", "-c", _PROBE)
            if output.returncode:
                raise SandboxError(f"task sandbox write/read probe failed ({output.returncode}): {output.stderr}")
        except BaseException as error:
            diagnostic = (runtime / "sandbox.stderr").read_text(encoding="utf-8", errors="replace")[-4000:]
            if diagnostic:
                error.add_note(f"bwrap stderr: {diagnostic}")
            try:
                await self.stop(handle)
            except BaseException as cleanup_error:
                error.add_note(f"Sandbox cleanup also failed: {cleanup_error}")
            raise
        return handle

    def _environment(self, **extra: str) -> dict[str, str]:
        return {"PATH": _PATH, "HOME": "/home/agent", "PI_CODING_AGENT_DIR": "/home/agent/.pi/agent",
                "LANG": "C.UTF-8", "TMPDIR": "/tmp", "PYTHONPATH": "/opt/lenbot/python",
                "MATPLOTLIBRC": "/opt/lenbot/matplotlibrc", **extra}

    def _launch(self, sandbox: SandboxHandle, **extra: str):
        session = self._sessions[sandbox.container_id]
        environment = self._environment(**extra)

        async def launch(*argv, cwd, env, stdin, stdout, stderr):
            return await session.launch(*argv, cwd=PurePosixPath("/workspace"), env=environment,
                                        stdin=stdin, stdout=stdout, stderr=stderr)
        return launch

    async def _run(self, sandbox: SandboxHandle, *argv: str):
        """Run one short command to completion and collect its output."""
        directory = sandbox.control.parent
        out_path, err_path = directory / ".run.stdout", directory / ".run.stderr"
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            child = await self._launch(sandbox)(*argv, cwd=None, env=None, stdin=None, stdout=None, stderr=err)
            child.stdin.close()
            copying = asyncio.create_task(child.stdout.read())
            try:
                status = await asyncio.wait_for(child.wait(), self.settings.command_timeout_seconds)
                out.write(await copying)
            except BaseException:
                copying.cancel()
                if child.returncode is None:
                    child.kill()
                raise
        result = _Completed(status, out_path.read_text(encoding="utf-8", errors="replace"),
                            err_path.read_text(encoding="utf-8", errors="replace"))
        out_path.unlink()
        err_path.unlink()
        return result

    async def browser_cli_version(self, sandbox: SandboxHandle) -> str | None:
        """None when this task runtime has no browser installed."""
        if not (self.settings.task_runtime / "bin" / "lenbot-browser").exists():
            return None
        output = await self._run(sandbox, "lenbot-browser", "--version")
        try:
            result = json.loads(output.stdout)
        except ValueError as error:
            raise SandboxError(f"Invalid browser CLI response: {error}; raw={output.stdout[:500]!r}") from error
        if not isinstance(result, dict) or result.get("isError") is True or result.get("version") != "1.62.0":
            raise SandboxError(f"Task runtime requires browser CLI 1.62.0; raw={output.stdout[:500]!r}")
        return result["version"]

    async def spawn_model_bridge(self, sandbox: SandboxHandle, *, proxy: WorkerModelProxy, stderr_path: Path,
                                 task_request: Callable[[str, bytes], Awaitable[dict]] | None = None
                                 ) -> WorkerTransport:
        (sandbox.control / "model-bridge.json").write_text(json.dumps({
            "port": 18181, "max_request_bytes": proxy.limits.max_request_bytes,
        }), encoding="utf-8")
        return await WorkerTransport.spawn(
            [self.python, "-I", f"{_HOST_PROGRAMS}/worker_bridge.py", "/run/lenbot/model-bridge.json"],
            cwd=sandbox.workspace, env={}, stderr_path=stderr_path, proxy=proxy,
            startup_timeout_seconds=self.settings.command_timeout_seconds, task_request=task_request,
            launch=self._launch(sandbox))

    async def spawn_egress_bridge(
        self, sandbox: SandboxHandle, *, settings: EgressSettings, fake_ip_networks: tuple, bytes_per_second: int,
        before_bytes: Callable[[int, str, int], None], on_connection: Callable[[dict], None],
        on_bytes: Callable[[int, str, int], None], stderr_path: Path, public_dns_url: str | None = None,
    ) -> EgressTransport:
        # Not -I: the bridge imports egress_wire from its own directory.
        command = [self.python, f"{_HOST_PROGRAMS}/worker_egress_bridge.py", "--port", "18182",
                   "--max-connections", str(settings.max_connections),
                   "--header-timeout-seconds", str(settings.header_timeout_seconds)]
        return await EgressTransport.spawn(
            command, cwd=sandbox.workspace, env={}, stderr_path=stderr_path,
            max_connections=settings.max_connections, connect_timeout_seconds=settings.connect_timeout_seconds,
            fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url, bytes_per_second=bytes_per_second,
            before_bytes=before_bytes, on_connection=on_connection, on_bytes=on_bytes,
            launch=self._launch(sandbox))

    def pi_command(self, provider: str, model: str, skills: tuple[Skill, ...]) -> list[str]:
        command = ["pi", "--mode", "rpc", "--session", "/workspace/session.jsonl",
                   "--session-dir", "/workspace/.pi-sessions", "--provider", provider, "--model", model,
                   "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve",
                   "--extension", "/opt/lenbot/lenbot-extension.ts"]
        for skill in skills:
            command.extend(("--skill", str(PurePosixPath(skill.container_path) / "SKILL.md")))
        return command

    async def spawn_pi(self, sandbox: SandboxHandle, *, provider: str, model: str, stderr_path: Path,
                       proxy_port: int | None = None, skills: tuple[Skill, ...] = ()) -> PiRpc:
        if not provider.strip() or not model.strip():
            raise ValueError("Pi provider and model must be explicitly configured")
        proxy: dict[str, str] = {}
        if proxy_port is not None:
            address = f"http://127.0.0.1:{proxy_port}"
            proxy = {name: address for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")}
            proxy |= {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
                      # Node's fetch() reads the proxy variables only with this set (Node 24).
                      "NODE_USE_ENV_PROXY": "1"}
        rpc: PiRpc | None = None
        try:
            rpc = await PiRpc.spawn(self.pi_command(provider, model, skills), cwd=sandbox.workspace, env={},
                                    stderr_path=stderr_path, launch=self._launch(sandbox, **proxy))
            state = await asyncio.wait_for(rpc.command("get_state"), timeout=self.settings.command_timeout_seconds)
            data = state.body.get("data")
            selected = data.get("model") if isinstance(data, dict) else None
            if (not isinstance(selected, dict) or selected.get("provider") != provider
                    or selected.get("id") != model):
                raise SandboxError(f"Pi selected a different model than {provider}/{model}: {selected!r}")
            return rpc
        except BaseException as error:
            error.add_note(f"Pi startup stderr: {stderr_path}")
            if rpc is not None:
                try:
                    await rpc.close()
                except BaseException as cleanup_error:
                    error.add_note(f"Pi RPC cleanup also failed: {cleanup_error}")
            raise

    async def copy_out(self, sandbox: SandboxHandle, source: str, dest: Path, *, max_bytes: int) -> None:
        await copy_regular_out(sandbox.workspace, source, dest, max_bytes)

    async def stop(self, sandbox: SandboxHandle) -> None:
        session = self._sessions.pop(sandbox.container_id, None)
        if session is not None:
            await session.close(self.settings.command_timeout_seconds)
        if sandbox.control.exists():
            shutil.rmtree(sandbox.control)

    async def stop_recorded(self, scene: str, task_id: str, container: str) -> None:
        """bwrap ends with the host process (``--die-with-parent``); only a live session needs stopping."""
        task_identity(scene, task_id)
        session = self._sessions.pop(container, None)
        if session is not None:
            await session.close(self.settings.command_timeout_seconds)
        control = self.settings.runtime_root.resolve() / scene_directory(scene) / task_id / "control"
        if control.exists():
            shutil.rmtree(control)


@dataclass(frozen=True)
class _Completed:
    returncode: int
    stdout: str
    stderr: str


async def check_local_sandbox(bwrap_binary: Path, task_runtime: Path) -> list[dict]:
    """Each startup step in order, stopping at the first failure; ``detail`` keeps the original output."""
    defaults = WorkerSettings.model_fields
    steps: list[dict] = []

    def record(step: str, ok: bool, detail: str) -> bool:
        steps.append({"step": step, "ok": ok, "detail": detail.strip()})
        return ok

    binary = bwrap_binary
    if not record("bwrap", binary.is_file() and os.access(binary, os.X_OK),
                  f"{binary} 可执行" if binary.is_file() and os.access(binary, os.X_OK) else f"{binary} 不存在或不可执行"):
        return steps
    trial = await asyncio.create_subprocess_exec(
        str(binary), "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--proc", "/proc",
        "--dev", "/dev", "true", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, error = await asyncio.wait_for(trial.communicate(), defaults["command_timeout_seconds"].default)
    detail = error.decode("utf-8", errors="replace")
    restriction = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    if trial.returncode and restriction.is_file() and restriction.read_text().strip() == "1":
        detail += "\nkernel.apparmor_restrict_unprivileged_userns=1"
    if not record("namespaces", trial.returncode == 0, detail or "能创建用户、网络、PID 与挂载命名空间"):
        return steps
    runtime = task_runtime
    missing = [name for name in ("node/bin/node", "node/bin/pi", "lenbot-extension.ts", "python")
               if not (runtime / name).exists()]
    if not record("task_runtime", not missing,
                  f"{runtime} 缺少 {', '.join(missing)}" if missing else f"{runtime} 含 Node、Pi、任务扩展与 Python 库"):
        return steps
    with tempfile.TemporaryDirectory(prefix="lenbot-sandbox-check-") as directory:
        root = Path(directory)
        sandbox = BwrapSandbox(BwrapSettings(
            bwrap_binary=bwrap_binary, task_runtime=task_runtime,
            workspace_root=root / "workspaces", runtime_root=root / "runtime",
            memory_bytes=byte_size(defaults["memory"].default), pids_limit=defaults["pids_limit"].default,
            file_bytes=defaults["max_workspace_bytes"].default, tmpfs_bytes=byte_size(defaults["tmpfs_size"].default),
            command_timeout_seconds=defaults["command_timeout_seconds"].default))
        try:
            handle = await sandbox.ensure("local:private:check", "check")
        except Exception as error:
            record("sandbox", False, "".join([f"{type(error).__name__}: {error}", *(
                "\n" + note for note in getattr(error, "__notes__", ()))]))
            return steps
        try:
            record("sandbox", True, "任务目录可写，配置目录只读")
            output = await sandbox._run(handle, "pi", "--version")
            record("pi", output.returncode == 0, output.stdout or output.stderr)
        finally:
            await sandbox.stop(handle)
    return steps
