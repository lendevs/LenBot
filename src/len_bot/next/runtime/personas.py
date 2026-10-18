"""The role library, and switching or reloading a scene's role while the host keeps running."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import tempfile
import time
from collections.abc import Coroutine
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..chat.tools import task_data_tools
from ..config import HostConfig, _read_root
from ..configuration.chat import SceneSettings
from ..configuration.editing import _read_saved, save_config
from ..persona.packages import import_package
from ..persona.profile import Persona, load_persona, read_persona_files, save_persona_files
from ..storage.files import sync_directory
from ..tools.skills import load_catalog, select_skills
from .logs import error_text, log_event

if TYPE_CHECKING:
    from .network import NetworkRuntime

logger = logging.getLogger(__name__)

# A new role's folder name is also its id, which names its memory directory bot/<id>/.
ROLE_FOLDER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# How long a panel request waits for a scene's current turn before answering "pending".
WAIT_SECONDS = 3.0
_EMPTY_SCENE_ROLE = {"persona_aliases": [], "relationships": {}, "behavior_addendum": None}
_SCENE_ROLE_FIELDS = ("persona", *_EMPTY_SCENE_ROLE, "inactive_personas")


@dataclass(frozen=True)
class Role:
    key: str
    path: Path
    # What a scene's ``persona`` records for this package.
    config_path: str
    id: str | None
    name: str | None
    brief: str | None
    aliases: tuple[str, ...]
    error: str | None


def _metadata(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = yaml.safe_load((path / "persona.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        return None, error_text(error)
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("name"), str):
        return None, "persona.yaml 缺少 id 或 name"
    return data, None


def roles(root: Path, saved: HostConfig) -> list[Role]:
    """Packages under ``personas/`` plus any other directory a scene is bound to."""
    root = root.resolve()
    collection = root / "personas"
    found: dict[Path, tuple[str, str]] = {}
    if collection.is_dir() and not collection.is_symlink():
        for entry in sorted(collection.iterdir(), key=lambda item: item.name):
            if entry.name.startswith(".") or entry.is_symlink() or not (entry / "persona.yaml").is_file():
                continue
            found[entry.resolve()] = (entry.name, f"personas/{entry.name}")
    for settings in saved.scenes.values():
        if settings.persona not in found:
            digest = hashlib.sha256(str(settings.persona).encode()).hexdigest()[:12]
            found[settings.persona] = (f"ext-{digest}", str(settings.persona))
    result = []
    for path, (key, written) in found.items():
        data, error = _metadata(path)
        aliases = data.get("aliases") if data is not None else None
        result.append(Role(key, path, written, None if data is None else data["id"],
                           None if data is None else data["name"],
                           None if data is None or not isinstance(data.get("brief"), str) else data["brief"],
                           tuple(item for item in aliases if isinstance(item, str)) if isinstance(aliases, list) else (),
                           error))
    return result


def _publish(root: Path, folder: str, fill: Any) -> Path:
    """Build a new package in a temporary directory and move it into ``personas/`` once it loads."""
    if ROLE_FOLDER.fullmatch(folder) is None or len(folder) > 64:
        raise ValueError(f"文件夹名只能用小写字母、数字和 -，不能以 - 开头或结尾：{folder!r}")
    collection = root / "personas"
    if collection.is_symlink():
        raise ValueError(f"角色目录不能是符号链接：{collection}")
    collection.mkdir(mode=0o700, exist_ok=True)
    destination = collection / folder
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"已经有叫 {folder} 的角色文件夹")
    with tempfile.TemporaryDirectory(prefix=".persona-new-", dir=collection) as temporary:
        package = Path(temporary) / "package"
        fill(package)
        load_persona(package)
        package.rename(destination)
    sync_directory(collection)
    return destination


def _rewrite_identity(path: Path, *, id: str, name: str | None = None) -> None:
    files = read_persona_files(path)
    metadata = yaml.safe_load(files["persona.yaml"])
    metadata["id"] = id
    if name is not None:
        metadata["name"] = name
    save_persona_files(path, {**files, "persona.yaml": yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)})


def _require_new(root: Path, saved: HostConfig, folder: str) -> None:
    destination = root / "personas" / folder
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"已经有叫 {folder} 的角色文件夹")
    if any(role.id == folder for role in roles(root, saved)):
        raise ValueError(f"角色 ID {folder} 已被别的角色使用，换一个文件夹名")


def create_role(root: Path, saved: HostConfig, folder: str, name: str) -> Path:
    if not name.strip():
        raise ValueError("角色名字不能为空")
    _require_new(root, saved, folder)

    def fill(package: Path) -> None:
        package.mkdir(mode=0o700)
        metadata = {"id": folder, "name": name.strip(), "brief": "", "behavior": "", "self_reference": ["我"],
                    "aliases": [], "tools": "all", "skills": "all", "styles": []}
        (package / "persona.yaml").write_text(yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False),
                                              encoding="utf-8")
        for filename, content in (("voice.md", ""), ("boundaries.md", ""), ("examples.yaml", "[]\n")):
            (package / filename).write_text(content, encoding="utf-8")

    return _publish(root, folder, fill)


def copy_role(root: Path, saved: HostConfig, source: Role, folder: str, name: str) -> Path:
    if not name.strip():
        raise ValueError("角色名字不能为空")
    _require_new(root, saved, folder)
    read_persona_files(source.path)

    def fill(package: Path) -> None:
        shutil.copytree(source.path, package, symlinks=False,
                        ignore=lambda _, names: [item for item in names if item.startswith(".persona-")])
        _rewrite_identity(package, id=folder, name=name.strip())

    return _publish(root, folder, fill)


def import_role(root: Path, saved: HostConfig, folder: str, data: bytes) -> dict:
    """Import a ZIP; a role id another package already uses becomes the folder name."""
    taken = {role.id for role in roles(root, saved)}
    result = import_package(root, folder, data)
    if result["persona"]["id"] in taken:
        _rewrite_identity(Path(result["path"]), id=folder)
        result["renamed_id"] = {"from": result["persona"]["id"], "to": folder}
        result["persona"]["id"] = folder
    return result


def delete_role(root: Path, saved: HostConfig, role: Role, running: set[Path]) -> Path:
    """Move an unused package aside under ``.runtime/deleted-personas/``; its memory stays."""
    root = root.resolve()
    if role.path.parent != root / "personas":
        raise ValueError("这个角色不在实例的 personas 目录里，面板不删除它")
    if role.path in running or any(settings.persona == role.path for settings in saved.scenes.values()):
        raise ValueError("还有群在用这个角色，先给这些群换别的角色")
    trash = root / ".runtime" / "deleted-personas"
    trash.mkdir(parents=True, exist_ok=True)
    destination = trash / f"{role.path.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    role.path.rename(destination)
    sync_directory(role.path.parent)
    return destination


class PersonaService:
    """Changes a running scene's role between turns; the saved root config is changed first."""

    def __init__(self, root: Path, runtime: NetworkRuntime):
        self.root = root.resolve()
        self.runtime = runtime
        self.background: set[asyncio.Task] = set()

    def library(self, saved: HostConfig | None = None) -> list[Role]:
        return roles(self.root, _read_saved(self.root) if saved is None else saved)

    def find(self, key: str, saved: HostConfig | None = None) -> Role:
        for role in self.library(saved):
            if role.key == key:
                return role
        raise KeyError(key)

    def running_scenes(self, path: Path) -> list[str]:
        return [scene for scene, chat in self.runtime.chats.items() if chat.config.persona == path]

    def describe(self, role: Role, saved: HostConfig, library: list[Role]) -> dict:
        return {"key": role.key, "path": str(role.path), "config_path": role.config_path, "id": role.id,
                "name": role.name, "brief": role.brief, "aliases": list(role.aliases), "error": role.error,
                "avatar": (role.path / "avatar.png").is_file(),
                "duplicate_id": role.id is not None and sum(item.id == role.id for item in library) > 1,
                "scenes": [scene for scene, settings in saved.scenes.items() if settings.persona == role.path],
                "running_scenes": self.running_scenes(role.path)}

    def spawn(self, coroutine: Coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self.background.add(task)

        def finished(task: asyncio.Task) -> None:
            self.background.discard(task)
            if not task.cancelled() and task.exception() is not None:
                log_event(logger, "persona_background", level=logging.ERROR, error=task.exception())

        task.add_done_callback(finished)
        return task

    async def settle(self, coroutine: Coroutine) -> tuple[bool, Any]:
        """Wait briefly for work that runs after the scene's current turn; it continues if not done."""
        task = self.spawn(coroutine)
        done, _ = await asyncio.wait({task}, timeout=WAIT_SECONDS)
        return (True, task.result()) if task in done else (False, None)

    def _target(self, scene: str, key: str) -> tuple[HostConfig, Role, Persona, str]:
        saved = _read_saved(self.root)
        if scene not in saved.scenes:
            raise ValueError(f"保存配置里没有群 {scene}")
        library = self.library(saved)
        role = next((item for item in library if item.key == key), None)
        if role is None:
            raise KeyError(key)
        persona = load_persona(role.path)
        if sum(item.id == persona.id for item in library) > 1:
            raise ValueError(f"有多个角色用同一个 ID {persona.id}，先改掉重复的 ID 再换")
        data, _ = _metadata(saved.scenes[scene].persona)
        previous = self.runtime.chats[scene].persona.id if data is None else data["id"]
        return saved, role, persona, previous

    @staticmethod
    def _bind(source: dict, saved: HostConfig, scene: str, role: Role, persona: Persona, previous: str) -> None:
        if scene not in saved.scenes:
            raise ValueError(f"保存配置里没有群 {scene}")
        local = source["scenes"][scene]
        parked = dict(local.get("inactive_personas") or {})
        if previous != persona.id:
            current = {field: local.get(field, empty) for field, empty in _EMPTY_SCENE_ROLE.items()}
            if current != _EMPTY_SCENE_ROLE:
                parked[previous] = current
            else:
                parked.pop(previous, None)
            restored = parked.pop(persona.id, _EMPTY_SCENE_ROLE)
            for field, empty in _EMPTY_SCENE_ROLE.items():
                if restored.get(field, empty) == empty:
                    local.pop(field, None)
                else:
                    local[field] = restored[field]
        local["persona"] = role.config_path
        if parked:
            local["inactive_personas"] = parked
        else:
            local.pop("inactive_personas", None)

    def _apply(self, scene: str, persona: Persona, settings: SceneSettings | None) -> None:
        """Hand the loaded role to every running part of the scene; caller owns the scene lock."""
        runtime = self.runtime
        chat = runtime.chats[scene]
        targets = (runtime.config.scenes[scene], chat.config)
        before = [{field: getattr(target, field) for field in _SCENE_ROLE_FIELDS} for target in targets]
        if settings is not None:
            for target in targets:
                for field in _SCENE_ROLE_FIELDS:
                    setattr(target, field, deepcopy(getattr(settings, field)))
        try:
            skills = ()
            if runtime.tasks is not None:
                worker = runtime.config.worker
                catalog = load_catalog(worker.skills_directory, scene, public_browser=worker.public_browser) + (
                    () if runtime.plugins is None else runtime.plugins.skills_for(scene))
                skills = select_skills(catalog, persona.skills)
            external = (([] if runtime.plugins is None else
                         runtime.plugins.tools_for(scene, preparing=runtime.status != "running"))
                        + ([] if runtime.mcp is None else runtime.mcp.tools_for(scene)))
            data_tools = (None if runtime.tasks is None else task_data_tools(
                chat.config, persona, platform=runtime.config.delivery == "onebot", memory=runtime.memory))
            runtime.runners[scene].adopt_persona(persona, skills, external)
        except Exception:
            for target, values in zip(targets, before):
                for field, value in values.items():
                    setattr(target, field, value)
            chat.context.refresh_tools()
            raise
        if runtime.tasks is not None:
            runtime.tasks.skills[scene] = skills
            runtime.tasks.skill_permissions[scene] = persona.skills
            runtime.tasks.tool_permissions[scene] = persona.tools
            runtime.tasks.data_tools[scene] = data_tools
        if runtime.memory is not None:
            runtime.memory.active_personas[scene] = persona.id
            runtime.memory.jobs.remember_personas(scene, {persona.id})
        runtime.notify()

    async def switch(self, scene: str, key: str, *, source: str = "panel") -> dict:
        """Bind the scene to the role; waits for the current turn, writes the handover, then applies."""
        runtime = self.runtime
        if scene not in runtime.runners:
            raise KeyError(scene)
        runner = runtime.runners[scene]
        chat = runner.chat
        async with runner.execution:
            async with runtime.config_write_lock:
                saved, role, persona, previous_id = await asyncio.to_thread(self._target, scene, key)
                previous = chat.persona
                if (role.path == chat.config.persona == saved.scenes[scene].persona
                        and persona.id == previous.id):
                    return {"scene": scene, "status": "unchanged", "persona": {"id": persona.id, "name": persona.name}}
                original = (await asyncio.to_thread(_read_root, self.root))[1]['scenes'][scene]
                previous_binding = {field: deepcopy(original[field]) for field in _SCENE_ROLE_FIELDS if field in original}
                saved = await asyncio.to_thread(save_config, self.root, runtime.config, lambda original, current:
                                                self._bind(original, current, scene, role, persona, previous_id))
            handover, error = "skipped", None
            if previous.id != persona.id:
                try:
                    handover = await chat.hand_over(previous.name, persona.name)
                except Exception as failure:
                    handover, error = "failed", error_text(failure)
                    log_event(logger, "persona_handover", level=logging.WARNING, scene=scene, error=failure)
            try:
                self._apply(scene, persona, saved.scenes[scene])
            except Exception as failure:
                def restore_binding(original: dict, current: HostConfig) -> None:
                    local = original['scenes'][scene]
                    for field in _SCENE_ROLE_FIELDS:
                        local.pop(field, None)
                    local.update(previous_binding)
                async with runtime.config_write_lock:
                    await asyncio.to_thread(save_config, self.root, runtime.config, restore_binding)
                raise RuntimeError(f"角色装配失败，已恢复原绑定：{error_text(failure)}") from failure
            if previous.id != persona.id:
                chat.context.host_state = (
                    f"本群角色已从「{previous.name}」换成「{persona.name}」。"
                    + (f"较早群聊回想里「{previous.name}」的话和承诺属于「{previous.name}」。" if handover == "done" else
                       f"当前会话里此前 assistant 的发言和承诺属于「{previous.name}」，不是你说的。"))
        log_event(logger, "persona_switch", scene=scene, persona=persona.id, previous=previous.id,
                  handover=handover, source=source)
        return {"scene": scene, "status": "switched", "persona": {"id": persona.id, "name": persona.name},
                "previous": {"id": previous.id, "name": previous.name}, "handover": handover, "error": error}

    async def reload(self, path: Path) -> list[str]:
        """Apply a saved edit of the role to every scene running it, each after its current turn."""
        async def one(scene: str) -> str:
            runner = self.runtime.runners[scene]
            async with runner.execution:
                if runner.chat.config.persona != path:
                    return scene
                persona = await asyncio.to_thread(load_persona, path)
                if persona.id != runner.chat.persona.id:
                    raise ValueError(f"角色 ID 从 {runner.chat.persona.id} 改成了 {persona.id}；换 ID 请复制一份角色")
                self._apply(scene, persona, None)
            return scene

        return list(await asyncio.gather(*(one(scene) for scene in self.running_scenes(path))))

    async def command_reply(self, scene: str, argument: str) -> str:
        """The one fixed line answering an owner's ``/角色``; a valid name switches the scene first."""
        chat = self.runtime.chats[scene]
        try:
            library = [role for role in await asyncio.to_thread(self.library) if role.error is None]
            names = "、".join(role.name for role in library)
            wanted = argument.casefold()
            matches = [role for role in library if wanted in {
                role.name.casefold(), role.key.casefold(), role.id.casefold(),
                *(alias.casefold() for alias in role.aliases)}]
            if not argument:
                text = f"现在是 {chat.persona.name}。可以换：{names}"
            elif not matches:
                text = f"没有叫 {argument} 的角色。可以换：{names}"
            elif len(matches) > 1:
                text = (f"有好几个叫 {argument} 的：" + "、".join(f"{role.name}（目录 {role.key}）" for role in matches)
                        + "，发目录名再试")
            elif matches[0].path == chat.config.persona:
                text = f"现在就是 {chat.persona.name}"
            else:
                result = await self.switch(scene, matches[0].key, source="command")
                text = f"已换成 {result['persona']['name']}"
        except Exception as error:
            log_event(logger, "persona_command", level=logging.WARNING, scene=scene, error=error)
            text = f"没换成：{error_text(error)[:200]}"
        return text
