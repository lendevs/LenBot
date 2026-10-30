"""One-task Docker lifecycle for the P3 work agent.

Public network access is unavailable until task egress is installed. The model
endpoint is carried over exec pipes, with ``--network none`` still in effect.
"""

from __future__ import annotations

import asyncio
import csv
from io import StringIO
from collections.abc import Awaitable, Callable
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from .pi_rpc import PiRpc
from .docker_mounts import require_task_mounts, require_task_volume_mounts
from ..tools.skills import Skill
from .materials import finish_file_operation
from ..configuration.tasks import EgressSettings, local_docker_endpoint
from .worker_egress import EgressTransport
from .worker_model import WorkerModelProxy
from .worker_transport import WorkerTransport
from ..platform.identity import scene_directory
from ..storage.files import NONBLOCK, Directory


_SCENE = re.compile(r"[a-z][a-z0-9_-]*:(group|private):[^:\s/\\]+\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_WRITE_PROBE = """\
import os
import tempfile
for directory in (
    '/workspace', '/workspace/out', '/workspace/.pi-sessions',
    '/home/agent', '/home/agent/.pi/agent',
):
    descriptor, path = tempfile.mkstemp(prefix='.lenbot-permission-', dir=directory)
    os.close(descriptor)
    os.unlink(path)
os.listdir('/run/lenbot')
"""


class SandboxError(RuntimeError):
    """A task container or file boundary did not complete."""


@dataclass(frozen=True)
class DockerSettings:
    docker_binary: Path
    docker_host: str
    image: str
    workspace_root: Path
    runtime_root: Path
    uid: int
    gid: int
    cpus: float = 2.0
    memory: str = "2g"
    tmpfs_size: str = "256m"
    pids_limit: int = 512
    command_timeout_seconds: float = 30.0
    # (volume name, its path in the host container): task directories mount as subpaths of the volume.
    volume: tuple[str, Path] | None = None

    def __post_init__(self) -> None:
        if not self.image.strip() or not self.docker_binary.is_absolute():
            raise ValueError("Docker image and absolute docker_binary are required")
        local_docker_endpoint(self.docker_host)
        workspace = self.workspace_root.resolve()
        runtime = self.runtime_root.resolve()
        if (not self.workspace_root.is_absolute() or not self.runtime_root.is_absolute()
                or workspace.is_relative_to(runtime) or runtime.is_relative_to(workspace)):
            raise ValueError("workspace_root and runtime_root must be separate absolute trees")
        if (self.uid < 1 or self.gid < 1 or not math.isfinite(self.cpus)
                or self.cpus <= 0 or self.pids_limit <= 0):
            raise ValueError("container uid, gid, CPUs and process limit must be positive")
        if not re.fullmatch(r"[1-9][0-9]*[kmgKMG]", self.memory):
            raise ValueError("memory must be a Docker byte limit such as 2g")
        if (not math.isfinite(self.command_timeout_seconds)
                or self.command_timeout_seconds <= 0):
            raise ValueError("command_timeout_seconds must be finite and positive")


@dataclass(frozen=True)
class SandboxHandle:
    scene: str
    task_id: str
    container_id: str
    workspace: Path
    home: Path
    control: Path


class TaskSandbox(Protocol):
    """One way to run a task: Docker task containers or the Linux local sandbox.

    Every implementation gives a task the same paths (``/workspace``,
    ``/home/agent``, ``/run/lenbot``, ``/inputs``) and starts the model bridge,
    the egress bridge and Pi with pipes to the host only.
    """

    async def ensure(self, scene: str, task_id: str, *, skills: tuple[Skill, ...] = (),
                     input_names: tuple[str, ...] = (),
                     on_container: Callable[[str], None] | None = None) -> SandboxHandle: ...
    async def browser_cli_version(self, sandbox: SandboxHandle) -> str | None:
        """The browser CLI version, or None when this sandbox has no browser."""
    async def spawn_model_bridge(self, sandbox: SandboxHandle, *, proxy: WorkerModelProxy, stderr_path: Path,
                                 task_request: Callable[[str, bytes], Awaitable[dict]] | None = None
                                 ) -> WorkerTransport: ...
    async def spawn_egress_bridge(
        self, sandbox: SandboxHandle, *, settings: EgressSettings, fake_ip_networks: tuple, bytes_per_second: int,
        before_bytes: Callable[[int, str, int], None], on_connection: Callable[[dict], None],
        on_bytes: Callable[[int, str, int], None], stderr_path: Path, public_dns_url: str | None = None,
    ) -> EgressTransport: ...
    async def spawn_pi(self, sandbox: SandboxHandle, *, provider: str, model: str, stderr_path: Path,
                       proxy_port: int | None = None, skills: tuple[Skill, ...] = ()) -> PiRpc: ...
    async def copy_out(self, sandbox: SandboxHandle, source: str, dest: Path, *, max_bytes: int) -> None: ...
    async def stop(self, sandbox: SandboxHandle) -> None: ...
    async def stop_recorded(self, scene: str, task_id: str, container: str) -> None: ...


def task_identity(scene: str, task_id: str) -> None:
    if _SCENE.fullmatch(scene) is None or _TASK.fullmatch(task_id) is None:
        raise ValueError("scene or task_id is not a valid task workspace identity")


def prepare_task_directories(workspace_root: Path, runtime_root: Path, scene: str,
                             task_id: str) -> tuple[Path, Path, Path, Path]:
    """Create one task's workspace, home and control directories; return them and the runtime directory."""
    workspace_root, runtime_root = workspace_root.resolve(), runtime_root.resolve()
    workspace = workspace_root / scene_directory(scene) / "tasks" / task_id
    runtime = runtime_root / scene_directory(scene) / task_id
    home, control = runtime / "home", runtime / "control"
    for directory in (
        workspace_root / scene_directory(scene), workspace_root / scene_directory(scene) / "tasks", workspace,
        workspace / "out", workspace / ".pi-sessions", runtime_root / scene_directory(scene), runtime,
        home, home / ".pi", home / ".pi" / "agent", control,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise SandboxError(f"task workspace component is a symbolic link: {directory}")
    return workspace, home, control, runtime


async def copy_regular_out(workspace: Path, source: str, dest: Path, max_bytes: int) -> None:
    """Copy a current task's regular out/ file without following symlinks."""
    copying = asyncio.create_task(asyncio.to_thread(_copy_out, workspace, source, dest, max_bytes))
    try:
        await asyncio.shield(copying)
    except asyncio.CancelledError as cancelled:
        while not copying.done():
            try:
                await asyncio.shield(copying)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            copying.result()
        except BaseException as error:
            cancelled.add_note(f"Delivery copy also failed: {type(error).__name__}: {error}")
            raise cancelled from error
        raise


def _docker_environment() -> dict[str, str]:
    # The daemon is fixed by DockerSettings, never by Docker environment.
    # Docker Desktop's CLI on Windows also needs the system root and the user's profile directories.
    names = ("PATH", "HOME", "TMPDIR", "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")
    return {name: os.environ[name] for name in names if name in os.environ}


def _ownership(path: Path) -> str:
    try:
        info = path.stat()
    except OSError as error:
        return f"{path}=unreadable({error})"
    return f"{path}={info.st_uid}:{info.st_gid}/{oct(info.st_mode & 0o777)}"


def _mount(source: Path, target: str, *, readonly: bool = False,
           volume: tuple[str, Path] | None = None) -> list[str]:
    output = StringIO()
    if volume is None:
        fields = ['type=bind', f'source={source}']
    else:
        name, root = volume
        fields = ['type=volume', f'source={name}', f'volume-subpath={source.relative_to(root.resolve()).as_posix()}']
    csv.writer(output, lineterminator='').writerow([*fields, f'target={target}', *(['readonly'] if readonly else [])])
    specification = output.getvalue()
    return ["--mount", specification]


def _source_parts(source: str) -> tuple[str, ...]:
    path = PurePosixPath(source)
    if path.is_absolute():
        parts = path.parts
        if parts[:3] != ("/", "workspace", "out"):
            raise SandboxError("deliver_file source must be in /workspace/out")
        relative = parts[3:]
    else:
        parts = path.parts
        if not parts or parts[0] != "out":
            raise SandboxError("deliver_file source must start with out/")
        relative = parts[1:]
    if not relative or any(part in {".", ".."} for part in relative):
        raise SandboxError("deliver_file source must name a file below out/")
    return relative


def _copy_out(workspace: Path, source: str, dest: Path, max_bytes: int) -> None:
    parts = _source_parts(source)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    with Directory.open(workspace) as root:
        directory = root.child("out")
    source_fd: int | None = None
    temporary: Path | None = None
    try:
        for part in parts[:-1]:
            child = directory.child(part)
            directory.close()
            directory = child
        # A FIFO must not block open before fstat can reject the non-regular source.
        source_fd = directory.open_file(parts[-1], os.O_RDONLY | NONBLOCK)
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise SandboxError("deliver_file source is not a regular file")
        if metadata.st_size > max_bytes:
            raise SandboxError(f"deliver_file exceeds {max_bytes} bytes")
        descriptor, name = tempfile.mkstemp(prefix=".lenbot-delivery-", dir=dest.parent)
        temporary = Path(name)
        count = 0
        with os.fdopen(descriptor, "wb") as output:
            while chunk := os.read(source_fd, 1024 * 1024):
                count += len(chunk)
                if count > max_bytes:
                    raise SandboxError(f"deliver_file exceeds {max_bytes} bytes")
                output.write(chunk)
        # A same-directory hard link is an atomic, no-overwrite publication.
        os.link(temporary, dest)
    finally:
        if source_fd is not None:
            os.close(source_fd)
        directory.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _copy_through_docker(command: list[str], dest: Path, max_bytes: int) -> None:
    """Publish the single regular file ``docker cp ... -`` writes as a tar stream."""
    descriptor, name = tempfile.mkstemp(prefix=".lenbot-delivery-", dir=dest.parent)
    temporary = Path(name)
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=_docker_environment()) as process:
            try:
                with os.fdopen(descriptor, "wb") as output:
                    extract_regular_member(process.stdout, output, max_bytes)
            except BaseException as error:
                process.kill()
                if detail := process.stderr.read().decode("utf-8", errors="replace").strip():
                    error.add_note(f"docker cp stderr: {detail}")
                raise
            detail = process.stderr.read().decode("utf-8", errors="replace").strip()
            if process.wait() != 0:
                raise SandboxError(f"docker cp failed ({process.returncode}): {detail}")
        os.link(temporary, dest)
    finally:
        temporary.unlink(missing_ok=True)


def extract_regular_member(stream, output, max_bytes: int) -> int:
    """Copy the only member of a tar stream, which must be a regular file of at most ``max_bytes``."""
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            member = archive.next()
            if member is None or not member.isreg():
                raise SandboxError("deliver_file source is not a regular file")
            if member.size > max_bytes:
                raise SandboxError(f"deliver_file exceeds {max_bytes} bytes")
            source = archive.extractfile(member)
            count = 0
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > max_bytes:
                    raise SandboxError(f"deliver_file exceeds {max_bytes} bytes")
                output.write(chunk)
            if archive.next() is not None:
                raise SandboxError("deliver_file source is not a regular file")
    except tarfile.TarError as error:
        raise SandboxError(f"docker cp did not return one file: {error}") from error
    return count


async def check_docker(docker_binary: Path, docker_host: str, image: str, *, pull: bool,
                       pull_timeout_seconds: float = 1800) -> list[dict]:
    """Whether the Docker daemon answers and the worker image is present, pulling it when asked.

    Steps stop at the first failure; ``detail`` keeps the CLI's own output.
    """
    steps: list[dict] = []

    def record(step: str, ok: bool, detail: str) -> bool:
        steps.append({"step": step, "ok": ok, "detail": detail.strip()})
        return ok

    async def docker(*arguments: str, timeout: float = 30) -> tuple[int, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                str(docker_binary), "--host", docker_host, *arguments, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, env=_docker_environment())
        except OSError as error:
            return 127, f"{docker_binary}: {error}"
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return 124, f"docker {arguments[0]} 超过 {timeout:g} 秒未完成"
        return process.returncode, output.decode("utf-8", errors="replace")

    code, output = await docker("version", "--format", "{{.Server.Version}}")
    if not record("docker", code == 0, f"Docker Engine {output.strip()}" if code == 0 else output):
        return steps
    code, output = await docker("image", "inspect", "--format", "{{.Id}}", image)
    if code != 0 and pull:
        code, output = await docker("pull", image, timeout=pull_timeout_seconds)
        if code == 0:
            code, output = await docker("image", "inspect", "--format", "{{.Id}}", image)
    record("image", code == 0, f"{image} {output.strip()}" if code == 0 else output)
    return steps


class DockerSandbox:
    """Create, use and remove one network-isolated task, keeping its files."""

    def __init__(self, settings: DockerSettings):
        self.settings = settings

    async def _docker(self, *arguments: str) -> str:
        process = await asyncio.create_subprocess_exec(
            str(self.settings.docker_binary), "--host", self.settings.docker_host, *arguments,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_docker_environment(),
        )
        try:
            output, error = await asyncio.wait_for(
                process.communicate(), timeout=self.settings.command_timeout_seconds
            )
        except BaseException as error:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            try:
                await process.communicate()
            except BaseException as cleanup_error:
                error.add_note(f"Docker CLI reap also failed: {cleanup_error}")
            raise
        if process.returncode != 0:
            detail = error.decode("utf-8", errors="replace")
            raise SandboxError(f"docker {arguments[0]} failed ({process.returncode}): {detail}")
        return output.decode("utf-8").strip()

    async def ensure(self, scene: str, task_id: str, *,
                     skills: tuple[Skill, ...] = (),
                     input_names: tuple[str, ...] = (),
                     on_container: Callable[[str], None] | None = None) -> SandboxHandle:
        """Create a task container with the configured network."""
        task_identity(scene, task_id)
        workspace, home, control, runtime = prepare_task_directories(
            self.settings.workspace_root, self.settings.runtime_root, scene, task_id)
        volume = self.settings.volume
        mounts = [*_mount(workspace, "/workspace", volume=volume),
                  *_mount(home, "/home/agent", volume=volume),
                  *_mount(control, "/run/lenbot", readonly=True, volume=volume)]
        if input_names:
            mounts.extend(_mount(runtime / 'inputs', '/inputs', readonly=True, volume=volume))
        skill_root = control / 'skills'
        if skill_root.exists():
            await finish_file_operation(shutil.rmtree, skill_root)
        for skill in skills:
            if skill.source != "task":
                # Installed and plugin paths may exist only inside the host container.
                snapshot = skill_root / skill.name
                await finish_file_operation(shutil.copytree, skill.host_path, snapshot, symlinks=True)
                mounts.extend(_mount(snapshot, skill.container_path, readonly=True, volume=volume))
        name = f"lenbot-next-{uuid.uuid4().hex}"
        if on_container is not None:
            on_container(name)
        command = [
            "create", "--name", name, "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--ipc", "private", "--init", "--user", f"{self.settings.uid}:{self.settings.gid}",
            "--pids-limit", str(self.settings.pids_limit),
            "--memory", self.settings.memory, "--cpus", str(self.settings.cpus),
            "--tmpfs", f"/tmp:rw,noexec,nosuid,size={self.settings.tmpfs_size}",
            "--env", "HOME=/home/agent", "--env", "PI_CODING_AGENT_DIR=/home/agent/.pi/agent",
            "--workdir", "/workspace", *mounts, self.settings.image, "sleep", "infinity",
        ]
        container_id: str | None = None
        try:
            container_id = await self._docker(*command)
            await self._docker("start", container_id)
            try:
                probe = _WRITE_PROBE
                if input_names:
                    probe += f"\nfor name in {list(input_names)!r}:\n    with open('/inputs/' + name, 'rb') as source:\n        source.read(1)\n"
                await self._docker("exec", container_id, "python3", "-c", probe)
            except SandboxError as error:
                paths = (workspace, workspace / "out", workspace / ".pi-sessions",
                         home, home / ".pi" / "agent", control)
                if input_names:
                    paths += (runtime / 'inputs', *(runtime / 'inputs' / name for name in input_names))
                ownership = "; ".join(_ownership(path) for path in paths)
                raise SandboxError(
                    f"Container uid:gid {self.settings.uid}:{self.settings.gid} bind-path write/read probe failed; "
                    f"host owners/modes: {ownership}; {error}"
                ) from error
        except BaseException as error:
            try:
                if container_id is not None:
                    await self._docker("rm", "-f", container_id)
                else:
                    await self.stop_recorded(scene, task_id, name)
            except BaseException as cleanup_error:
                error.add_note(f"Container cleanup also failed: {cleanup_error}")
            raise
        return SandboxHandle(scene, task_id, container_id, workspace, home, control)

    async def browser_cli_version(self, sandbox: SandboxHandle) -> str:
        """Check the installed command/binary, without opening a browser or URL."""
        raw = await self._docker("exec", "--workdir", "/workspace", sandbox.container_id,
                                 "lenbot-browser", "--version")
        try:
            result = json.loads(raw)
        except ValueError as error:
            raise SandboxError(f"Invalid browser CLI response: {error}; raw={raw[:500]!r}") from error
        if (not isinstance(result, dict) or result.get("isError") is True
                or result.get("version") != "1.62.0"):
            raise SandboxError(f"Task image requires browser CLI 1.62.0; raw={raw[:500]!r}")
        return result["version"]

    async def spawn_model_bridge(self, sandbox: SandboxHandle, *, proxy: WorkerModelProxy,
                                 stderr_path: Path,
                                 task_request: Callable[[str, bytes], Awaitable[dict]] | None = None
                                 ) -> WorkerTransport:
        """Listen only on container loopback and connect to this host-owned proxy."""
        (sandbox.control / "model-bridge.json").write_text(json.dumps({
            "port": 18181, "max_request_bytes": proxy.limits.max_request_bytes,
        }), encoding="utf-8")
        command = [
            str(self.settings.docker_binary), "--host", self.settings.docker_host,
            "exec", "-i", sandbox.container_id,
            "python3", "/opt/lenbot/worker_bridge.py", "/run/lenbot/model-bridge.json",
        ]
        return await WorkerTransport.spawn(
            command, cwd=sandbox.workspace, env=_docker_environment(),
            stderr_path=stderr_path, proxy=proxy,
            startup_timeout_seconds=self.settings.command_timeout_seconds,
            task_request=task_request,
        )

    async def spawn_egress_bridge(
        self, sandbox: SandboxHandle, *, settings: EgressSettings,
        fake_ip_networks: tuple,
        bytes_per_second: int,
        before_bytes: Callable[[int, str, int], None],
        on_connection: Callable[[dict], None],
        on_bytes: Callable[[int, str, int], None],
        stderr_path: Path,
        public_dns_url: str | None = None,
    ) -> EgressTransport:
        """Use a separate exec pipe for public TCP, never a Docker network."""
        command = [
            str(self.settings.docker_binary), "--host", self.settings.docker_host,
            "exec", "-i", sandbox.container_id,
            "python3", "/opt/lenbot/worker_egress_bridge.py",
            "--port", "18182",
            "--max-connections", str(settings.max_connections),
            "--header-timeout-seconds", str(settings.header_timeout_seconds),
        ]
        return await EgressTransport.spawn(
            command, cwd=sandbox.workspace, env=_docker_environment(),
            stderr_path=stderr_path, max_connections=settings.max_connections,
            connect_timeout_seconds=settings.connect_timeout_seconds,
            fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
            bytes_per_second=bytes_per_second, before_bytes=before_bytes,
            on_connection=on_connection, on_bytes=on_bytes,
        )

    async def spawn_pi(self, sandbox: SandboxHandle, *, provider: str, model: str,
                       stderr_path: Path, proxy_port: int | None = None,
                       skills: tuple[Skill, ...] = ()) -> PiRpc:
        """Start exactly one configured Pi RPC session, not an arbitrary argv."""
        if not provider.strip() or not model.strip():
            raise ValueError("Pi provider and model must be explicitly configured")
        proxy_environment: list[str] = []
        if proxy_port is not None:
            proxy = f"http://127.0.0.1:{proxy_port}"
            for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
                proxy_environment.extend(("--env", f"{name}={proxy}"))
            for name in ("NO_PROXY", "no_proxy"):
                proxy_environment.extend(("--env", f"{name}=127.0.0.1,localhost"))
        command = [
            str(self.settings.docker_binary), "--host", self.settings.docker_host,
            "exec", "-i", "--workdir", "/workspace", *proxy_environment,
            sandbox.container_id,
            "pi", "--mode", "rpc", "--session", "/workspace/session.jsonl",
            "--session-dir", "/workspace/.pi-sessions",
            "--provider", provider, "--model", model,
            "--no-extensions", "--no-skills", "--no-prompt-templates",
            "--no-context-files", "--no-approve",
            "--extension", "/opt/lenbot/lenbot-extension.ts",
        ]
        for skill in skills:
            command.extend(("--skill", str(PurePosixPath(skill.container_path) / "SKILL.md")))
        rpc: PiRpc | None = None
        try:
            rpc = await PiRpc.spawn(command, cwd=sandbox.workspace,
                                    env=_docker_environment(), stderr_path=stderr_path)
            # Pi has started once it answers get_state inside the container.
            state = await asyncio.wait_for(rpc.command("get_state"),
                                           timeout=self.settings.command_timeout_seconds)
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

    # Windows bind mounts cannot be walked by directory descriptor; the container resolves the path instead.
    copy_through_docker = sys.platform == "win32"

    async def copy_out(self, sandbox: SandboxHandle, source: str, dest: Path, *,
                       max_bytes: int) -> None:
        """Copy a current task's regular out/ file without following symlinks."""
        if not self.copy_through_docker:
            await copy_regular_out(sandbox.workspace, source, dest, max_bytes)
            return
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        path = "/workspace/out/" + "/".join(_source_parts(source))
        command = [str(self.settings.docker_binary), "--host", self.settings.docker_host,
                   "cp", f"{sandbox.container_id}:{path}", "-"]
        await finish_file_operation(_copy_through_docker, command, dest, max_bytes)

    async def stop(self, sandbox: SandboxHandle) -> None:
        """Stop the whole container; keep workspace/home and clear current controls."""
        await self._docker("rm", "-f", sandbox.container_id)
        _clear_control(sandbox.control)

    async def stop_recorded(self, scene: str, task_id: str, container: str) -> None:
        """Reconcile a stored task container after host interruption."""
        workspace = self.settings.workspace_root.resolve() / scene_directory(scene) / 'tasks' / task_id
        runtime = self.settings.runtime_root.resolve() / scene_directory(scene) / task_id
        control = runtime / 'control'
        found = await self._docker("ps", "-aq", "--no-trunc", "--filter", f"name=^/{container}$")
        if found:
            if self.settings.volume is None:
                mounts = await self._docker('inspect', '--type', 'container', '--format', '{{json .Mounts}}', found)
                require_task_mounts(mounts, workspace=workspace, home=runtime / 'home', control=control)
            else:
                # Only the configured mounts carry the volume subpath; .Mounts reports the whole volume.
                mounts = await self._docker('inspect', '--type', 'container', '--format',
                                            '{{json .HostConfig.Mounts}}', found)
                require_task_volume_mounts(mounts, self.settings.volume, workspace=workspace,
                                           home=runtime / 'home', control=control)
            await self._docker("rm", "-f", found)
        if control.exists():
            _clear_control(control)


def _clear_control(path: Path) -> None:
    shutil.rmtree(path)
