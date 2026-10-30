"""Root-file task capacity, sandbox, and scene permission settings."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from importlib.metadata import PackageNotFoundError, distribution, version as installed_version
from pathlib import Path, PurePosixPath
import shutil
import sys
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .storage_pool import StoragePool


STRICT = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
TaskRole = Literal["owner", "admin", "group_manager", "whitelist", "member"]


EgressMode = Literal["off", "allowlist", "public"]
# Offered as one preset in the task settings; package installs also need the redirect hosts below.
PACKAGE_HOSTS = ("pypi.org", "files.pythonhosted.org", "registry.npmjs.org")
_HOST_PATTERN = re.compile(r"(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?")


class EgressSettings(BaseModel):
    model_config = STRICT

    mode: EgressMode = Field(default="off", description=(
        "任务联网方式：off 只能经宿主调用模型；allowlist 只连 allowed_hosts 中的域名；public 可连公网地址。"))
    allowed_hosts: list[str] = Field(default_factory=list, description=(
        "allowlist 模式可连接的域名；*.example.com 匹配它的所有子域名，不含 example.com 本身。"))
    max_task_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0, strict=True,
                                       description="单任务经出网上传的字节上限。")
    max_task_bytes: int = Field(default=500 * 1024 * 1024, gt=0, strict=True)
    max_scene_daily_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0, strict=True)
    max_connections: int = Field(default=16, gt=0, strict=True)
    bytes_per_second: int = Field(default=8 * 1024 * 1024, gt=0, strict=True)
    connect_timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    header_timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)

    @field_validator("allowed_hosts")
    @classmethod
    def host_patterns(cls, values: list[str]) -> list[str]:
        for value in values:
            if _HOST_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{value!r} must be a lowercase domain name or *.domain, without scheme, port or path")
        if len(values) != len(set(values)):
            raise ValueError("allowed_hosts must not repeat")
        return values

    @property
    def enabled(self) -> bool:
        """Whether tasks get the egress proxy at all."""
        return self.mode != "off"


_NAMED_PIPE = re.compile(r"npipe:////\./pipe/[A-Za-z0-9_.-]+\Z")
DOCKER_DESKTOP_PIPE = "npipe:////./pipe/docker_engine"
WORKER_IMAGE_USER = 10000


def local_docker_endpoint(value: str) -> str:
    """A local Docker endpoint: ``unix:///absolute/socket`` or a Windows named pipe ``npipe:////./pipe/name``."""
    if _NAMED_PIPE.fullmatch(value):
        return value
    endpoint = urlsplit(value)
    if (not value.startswith("unix:///") or endpoint.scheme != "unix" or endpoint.netloc
            or not PurePosixPath(endpoint.path).is_absolute() or endpoint.query or endpoint.fragment):
        raise ValueError("docker_host must be a local unix:///absolute/socket path or npipe:////./pipe/name")
    return value


class TaskVolume(BaseModel):
    """The Docker volume that holds the task directories when the host itself runs in a container."""
    model_config = STRICT

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description="数据卷名称。")
    root: Path = Field(description="宿主容器内该数据卷的挂载路径；任务工作目录和运行目录须在其下。")

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("task_volume.root must be an explicit absolute path")
        return value


class WorkerSettings(BaseModel):
    model_config = STRICT

    sandbox: Literal["docker", "bwrap"] = Field(
        default="docker", description="任务运行方式：docker 为任务容器，bwrap 为 Linux 本机沙箱。")
    docker_binary: Path | None = None
    docker_host: str | None = None
    image: str | None = None
    bwrap_binary: Path | None = None
    task_runtime: Path | None = Field(
        default=None, description="本机沙箱的任务运行时目录，含 Node、Pi 和任务工具，挂载到沙箱的 /opt/lenbot。")
    workspace_root: Path
    runtime_root: Path
    delivery_root: Path
    task_volume: TaskVolume | None = Field(
        default=None, description="Docker 部署时任务目录所在的数据卷；任务容器以子目录方式挂载，需要 Docker Engine 26 及以上。")
    storage_pool: StoragePool | None = None
    skills_directory: Path | None = None
    uid: int | None = Field(default=None, gt=0, strict=True)
    gid: int | None = Field(default=None, gt=0, strict=True)
    cpus: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    memory: str = Field(default="2g", pattern=r"^[1-9][0-9]*[kmgKMG]$")
    tmpfs_size: str = Field(default="256m", pattern=r"^[1-9][0-9]*[kmgKMG]$")
    pids_limit: int = Field(default=512, gt=0, strict=True)
    command_timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    max_running: int = Field(default=4, gt=0, strict=True)
    max_containers: int = Field(default=8, gt=0, strict=True)
    max_scene_containers: int = Field(default=4, gt=0, strict=True)
    max_calls: int = Field(default=40, gt=0, strict=True, description="每次执行的模型调用上限；续接时开始新一次执行，token 仍按任务累计。")
    max_request_bytes: int = Field(default=8 * 1024 * 1024, gt=0, strict=True)
    max_response_bytes: int = Field(default=64 * 1024 * 1024, gt=0, strict=True)
    max_tokens: int | None = Field(default=None, gt=0, strict=True,
                                   description="整个任务累计的输入加输出 token 上限；续接不清零。")
    compaction_reserve_tokens: int = Field(default=16384, gt=0, strict=True)
    compaction_keep_recent_tokens: int = Field(default=20000, gt=0, strict=True)
    active_timeout_seconds: float = Field(default=1800.0, gt=0, allow_inf_nan=False)
    input_timeout_seconds: float = Field(default=1800.0, ge=0.001, le=4294967.295, allow_inf_nan=False)
    max_file_bytes: int = Field(default=25 * 1024 * 1024, gt=0, strict=True)
    max_delivery_bytes: int = Field(default=500 * 1024 * 1024, gt=0, strict=True)
    max_workspace_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0, strict=True,
                                     description="单任务工作区与运行目录的合计上限，超过时停止任务；本机沙箱另用作单个文件的硬上限。")
    disk_reserve_bytes: int = Field(default=5 * 1024 * 1024 * 1024, gt=0, strict=True,
                                    description="任务目录所在磁盘剩余空间低于此值时不接新任务，已排队的任务等空间恢复。")
    disk_stop_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0, strict=True,
                                 description="剩余空间低于此值时停止运行中的任务。")
    workspace_retention_days: float = Field(default=14.0, gt=0, allow_inf_nan=False,
                                            description="任务结束后保留工作区与运行目录的天数，到期删除；交付文件保留。")
    storage_check_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False,
                                         description="检查任务目录大小、磁盘余量和到期工作区的间隔。")
    input_support: Literal["text", "text-image"] = "text"
    model_reasoning: bool
    egress: EgressSettings = Field(default_factory=EgressSettings)
    mcp: bool = False

    def missing_programs(self) -> frozenset[str]:
        """Programs built-in skills need that this task environment lacks.

        The worker image has them all. The local sandbox sees the system's /usr and the task runtime's bin/.
        """
        if self.sandbox == "docker":
            return frozenset()
        missing = set()
        for name in ("ffmpeg",):
            found = shutil.which(name, path="/usr/local/bin:/usr/bin:/bin")
            if found is None:
                missing.add(name)
        for name in ("lenbot-render", "lenbot-browser"):
            if self.task_runtime is None or not (self.task_runtime / "bin" / name).exists():
                missing.add(name)
        return frozenset(missing)

    @property
    def public_browser(self) -> bool:
        """The browser reaches websites only through the egress proxy, so it follows the network mode."""
        return self.egress.enabled

    @model_validator(mode="after")
    def disk_thresholds(self) -> WorkerSettings:
        if self.disk_stop_bytes >= self.disk_reserve_bytes:
            raise ValueError("worker.disk_stop_bytes must be below worker.disk_reserve_bytes")
        return self

    @model_validator(mode="after")
    def volume_holds_task_trees(self) -> WorkerSettings:
        if self.task_volume is not None:
            if self.sandbox != "docker":
                raise ValueError("worker.task_volume applies only to the docker sandbox")
            for name in ("workspace_root", "runtime_root"):
                if not getattr(self, name).is_relative_to(self.task_volume.root):
                    raise ValueError(f"worker.{name} must be inside worker.task_volume.root")
        return self

    @model_validator(mode="after")
    def sandbox_settings(self) -> WorkerSettings:
        required = {"docker": ("docker_binary", "docker_host", "image", "uid", "gid"),
                    "bwrap": ("bwrap_binary", "task_runtime")}[self.sandbox]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"worker.sandbox={self.sandbox} requires {', '.join('worker.' + name for name in missing)}")
        return self

    @field_validator("docker_binary", "bwrap_binary", "task_runtime")
    @classmethod
    def absolute_binary(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("must be an explicit absolute path")
        return value

    @field_validator("workspace_root", "runtime_root", "delivery_root")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("must be an explicit absolute path")
        return value.resolve()

    @field_validator("docker_host")
    @classmethod
    def local_docker_host(cls, value: str | None) -> str | None:
        return None if value is None else local_docker_endpoint(value)

    @field_validator("image")
    @classmethod
    def named_image(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("image must not be blank")
        return value

    @field_validator("skills_directory")
    @classmethod
    def absolute_skills_directory(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("skills_directory must be an explicit absolute path")
        return value

    @model_validator(mode="after")
    def separate_task_trees(self) -> WorkerSettings:
        roots = {
            "workspace_root": self.workspace_root,
            "runtime_root": self.runtime_root,
            "delivery_root": self.delivery_root,
        }
        if self.skills_directory is not None:
            roots["skills_directory"] = self.skills_directory
        for first_name, first in roots.items():
            for second_name, second in roots.items():
                if first_name != second_name and first.is_relative_to(second):
                    raise ValueError(f"worker.{first_name} must not be inside worker.{second_name}")
        if self.storage_pool is not None:
            mount = self.storage_pool.mount
            for path in (self.workspace_root, self.runtime_root):
                if path == mount or not path.is_relative_to(mount):
                    raise ValueError('worker workspace/runtime roots must be separate directories below storage_pool.mount')
            if self.delivery_root.is_relative_to(mount):
                raise ValueError('worker.delivery_root stays outside the task storage pool')
        return self


class TaskSettings(BaseModel):
    model_config = STRICT

    enabled: bool = False
    owner: str | None = None
    admins: list[str] = Field(default_factory=list)
    whitelist: list[str] = Field(default_factory=list)
    delegate_roles: list[TaskRole] = Field(default_factory=lambda: ["owner", "admin", "whitelist"])
    long_running_roles: list[TaskRole] = Field(default_factory=lambda: ["owner", "whitelist"])
    manage_roles: list[TaskRole] = Field(default_factory=lambda: ["owner", "admin"])
    max_running: int = Field(default=2, gt=0, strict=True)
    max_daily_tasks: int = Field(default=5, gt=0, strict=True)
    egress_max_task_bytes: int | None = Field(default=None, gt=0, strict=True)
    egress_max_daily_bytes: int | None = Field(default=None, gt=0, strict=True)
    egress_bytes_per_second: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("owner")
    @classmethod
    def valid_owner(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[a-z][a-z0-9_-]*:[^:\s/\\]+", value) is None:
            raise ValueError("owner must be a platform:account identity")
        return value

    @field_validator("admins", "whitelist")
    @classmethod
    def valid_identities(cls, values: list[str]) -> list[str]:
        if any(re.fullmatch(r"[a-z][a-z0-9_-]*:[^:\s/\\]+", value) is None for value in values):
            raise ValueError("must contain platform:account identities")
        return values

    @field_validator("delegate_roles", "manage_roles", "long_running_roles")
    @classmethod
    def unique_roles(cls, values: list[TaskRole]) -> list[TaskRole]:
        if len(values) != len(set(values)):
            raise ValueError("task roles must not repeat")
        return values


WORKER_IMAGE = "lenbot-worker:local"
OFFICIAL_WORKER = "ghcr.io/lendevs/lenbot-worker"


def release_installation() -> bool:
    """Installed from a release wheel (deployment package or image); a source checkout is an editable install."""
    try:
        direct = distribution("len-bot").read_text("direct_url.json")
    except PackageNotFoundError:
        return False
    return not (direct and json.loads(direct).get("dir_info", {}).get("editable"))


def _instance_volume(root: Path, suggestion: dict) -> tuple[str, str] | None:
    """The named volume holding the instance root when this host runs in a container, and its mount point."""
    if not Path("/.dockerenv").exists() or "docker_binary" not in suggestion or "docker_host" not in suggestion:
        return None
    try:
        result = subprocess.run(
            [suggestion["docker_binary"], "--host", suggestion["docker_host"], "inspect", "--type", "container",
             "--format", "{{json .Mounts}}", socket.gethostname()], capture_output=True, text=True, timeout=10)
        mounts = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return next(((mount["Name"], mount["Destination"]) for mount in mounts
                 if mount.get("Type") == "volume" and mount.get("Name") and mount.get("Destination")
                 and root.is_relative_to(mount["Destination"])), None)


def suggested_worker(root: Path) -> dict:
    """Task settings this host can fill in when tasks are first switched on.

    In a Docker deployment the directories sit in the instance volume, which task containers mount by subpath.
    """
    # A release installation (deployment package or Docker) follows the same-version official image,
    # as the updater does; a source checkout builds lenbot-worker:local.
    managed = (root / ".runtime" / "update-control.json").exists() or release_installation()
    suggestion: dict = {"image": f"{OFFICIAL_WORKER}:{installed_version('len-bot')}" if managed else WORKER_IMAGE}
    for name, folder in (("workspace_root", "task-workspaces"), ("runtime_root", "task-runtime"),
                         ("delivery_root", "deliveries")):
        suggestion[name] = str(root / folder)
    binary = shutil.which("docker")
    if binary is not None:
        suggestion["docker_binary"] = binary
    host, desktop = os.environ.get("DOCKER_HOST", ""), Path.home() / ".docker/run/docker.sock"
    if host.startswith(("unix:///", "npipe:")):
        suggestion["docker_host"] = host
    elif sys.platform == "win32":
        suggestion["docker_host"] = DOCKER_DESKTOP_PIPE
    elif desktop.exists():
        suggestion["docker_host"] = f"unix://{desktop}"
    elif Path("/var/run/docker.sock").exists():
        # Docker Engine, and the socket a Docker deployment binds into the host container.
        suggestion["docker_host"] = "unix:///var/run/docker.sock"
    if hasattr(os, "getuid") and os.getuid() > 0 and os.getgid() > 0:
        suggestion["uid"], suggestion["gid"] = os.getuid(), os.getgid()
    elif sys.platform == "win32":
        # Docker Desktop bind mounts do not map Windows owners; run as the image's agent user.
        suggestion["uid"] = suggestion["gid"] = WORKER_IMAGE_USER
    if (volume := _instance_volume(root, suggestion)) is not None:
        suggestion["task_volume"] = {"name": volume[0], "root": volume[1]}
    # Linux hosts with bwrap run tasks in the local sandbox; a Docker deployment's host container has none.
    bwrap = shutil.which("bwrap") if sys.platform == "linux" else None
    suggestion["sandbox"] = "docker" if bwrap is None else "bwrap"
    if bwrap is not None:
        suggestion["bwrap_binary"] = bwrap
    return suggestion
