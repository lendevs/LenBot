"""Expose the running tool set and save the configured role's tool permissions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import os
from pathlib import Path
import tempfile
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import field_validator
import yaml

from .. import responses
from ...chat.tools import build_tools, tool_catalog, tool_unavailable_reasons
from ...configuration.types import STRICT
from ...config import load_host_config
from ...tools.discovery import DEFERRED_NAMES
from ...runtime.network import NetworkRuntime
from ...persona.profile import PersonaTarget, load_persona, require_persona_target
from ...tools.skills import Skill, select_skills
from ...plugins.manifest import scene_skill_catalog
from .persona import apply_saved


logger = logging.getLogger(__name__)


class RoleTools(PersonaTarget):
    model_config = STRICT
    tools: Literal["all"] | list[str]

    @field_validator("tools")
    @classmethod
    def distinct_names(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, list):
            if any(not name.strip() for name in value):
                raise ValueError("工具名称不能为空")
            if len(value) != len(set(value)):
                raise ValueError("工具名称不能重复")
        return value


class RoleSkills(PersonaTarget):
    model_config = STRICT
    skills: Literal["all"] | list[str]

    @field_validator("skills")
    @classmethod
    def distinct_names(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, list) and (any(not name.strip() for name in value)
                                      or len(value) != len(set(value))):
            raise ValueError("技能名称不能为空或重复")
        return value


def skill_info(skill: Skill) -> dict:
    return {"name": skill.name, "description": skill.description, "source": skill.source,
            "path": skill.container_path + "/SKILL.md",
            "model_invocation": not skill.disable_model_invocation}


def register_host_capabilities(app: FastAPI, *, root: Path, runtime: NetworkRuntime,
                               user: Callable[[Request], str], write_lock: asyncio.Lock) -> None:
    def chat_for(scene: str):
        if scene not in runtime.chats:
            raise HTTPException(404, "当前宿主未配置此场景")
        return runtime.chats[scene]

    def role_state(scene: str) -> dict:
        chat = chat_for(scene)
        saved = load_host_config(root)
        if scene not in saved.scenes:
            raise ValueError("此场景已从保存配置移除，不能读取或编辑保存的角色许可")
        path = saved.scenes[scene].persona
        persona = load_persona(path)
        return {
            "directory": str(path), "persona": {"id": persona.id, "name": persona.name},
            "saved": persona.tools, "running": chat.persona.tools,
            "restart_required": persona.tools != chat.persona.tools or path != chat.config.persona,
            "affected_scenes": [key for key, value in saved.scenes.items() if value.persona == path],
        }

    @app.get("/api/host/capabilities", response_model=responses.Capabilities, response_model_exclude_unset=True)
    async def capabilities(scene: str, _: str = Depends(user)):
        chat = chat_for(scene)
        try:
            async with write_lock:
                roles = await asyncio.to_thread(role_state, scene)
        except (ValueError, OSError) as error:
            logger.exception("读取角色工具设置失败：%s", error)
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f"{type(error).__name__}: {error}") from error
        tools = []
        for tool in tool_catalog(platform=chat.config.delivery == "onebot"):
            function = tool["function"]
            name = function["name"]
            tools.append({
                "name": name, "description": function["description"], "summary": function["description"],
                "parameters": function["parameters"], "instructions": None,
                "allowed": chat.persona.tools == "all" or name in chat.persona.tools,
                "registered": name in chat.toolset.allowed_tool_names,
                "discovered": name in chat.toolset.discovered_tools,
                "deferred": name in DEFERRED_NAMES,
                "reasons": tool_unavailable_reasons(chat.config, chat.persona, name,
                                                    host_management=chat.toolset.host_management is not None),
            })
        plugin_tools = [] if runtime.plugins is None else runtime.plugins.tool_previews(scene)
        mcp_tools = [] if runtime.mcp is None else [
            {**tool.discovery, "summary": tool.discovery["description"], "description": tool.description,
             "parameters": tool.definition["function"]["parameters"], "instructions": tool.instructions, "reasons": []}
            for tool in runtime.mcp.tools_for(scene)]
        for preview in plugin_tools + mcp_tools:
            name = preview["name"]
            allowed = chat.persona.tools == "all" or name in chat.persona.tools
            reasons = list(preview["reasons"])
            if not allowed:
                reasons.append("角色未允许此工具")
            if "tool_search" not in chat.toolset.allowed_tool_names:
                reasons.append("角色未允许 tool_search，无法发现插件工具")
            tools.append({**preview, "allowed": allowed,
                "registered": name in chat.toolset.allowed_tool_names,
                "discovered": name in chat.toolset.discovered_tools, "deferred": True, "reasons": reasons})
        return {
            "scene": scene,
            "scenes": [{"scene": key, "persona": {"id": value.persona.id, "name": value.persona.name}}
                       for key, value in runtime.chats.items()],
            "persona": {"id": chat.persona.id, "name": chat.persona.name,
                        "tools": chat.persona.tools, "skills": chat.persona.skills},
            "role_tools": roles, "tools": tools,
            "services": {"web_read": chat.config.web_read is not None,
                         "web_search": chat.config.web_search is not None,
                         "memory": chat.memory is not None,
                         "vision": (chat.config.models.roles.mind.image_input
                                    or chat.config.binding("vision").image_input),
                         "worker": chat.tasks is not None,
                         "worker_mcp": chat.tasks is not None and chat.tasks.settings.mcp,
                         "skills": (chat.tasks is not None
                                    and chat.tasks.settings.skills_directory is not None),
                         "public_browser": (chat.tasks is not None
                                            and chat.tasks.settings.public_browser),
                         "public_network": chat.tasks is not None and chat.tasks.settings.egress.enabled,
                         "file_upload": chat.config.delivery == "onebot" and chat.tasks is not None,
                         "schedules": chat.config.schedules.enabled},
            "not_implemented": [],
        }

    def skills_state(scene: str) -> dict:
        chat = chat_for(scene)
        saved = load_host_config(root)
        if scene not in saved.scenes:
            raise ValueError("此场景已从保存配置移除，不能读取或编辑保存的角色许可")
        path = saved.scenes[scene].persona
        persona = load_persona(path)
        directory = None if saved.worker is None else saved.worker.skills_directory
        catalog = scene_skill_catalog(saved, scene)
        selected = select_skills(catalog, persona.skills) if saved.worker is not None else ()
        running_directory = None if chat.tasks is None else chat.tasks.settings.skills_directory
        return {
            "scene": scene, "directory": None if directory is None else str(directory),
            "running_directory": None if running_directory is None else str(running_directory),
            "role_skills": {"directory": str(path), "persona": {"id": persona.id, "name": persona.name},
                            "saved": persona.skills, "running": chat.persona.skills,
                            "restart_required": persona.skills != chat.persona.skills or path != chat.config.persona,
                            "affected_scenes": [key for key, value in saved.scenes.items()
                                                if value.persona == path]},
            "catalog": [{**skill_info(skill), "selected": skill in selected} for skill in catalog],
            "running": [skill_info(skill) for skill in chat.skills],
        }

    @app.get("/api/host/skills", response_model=responses.Skills, response_model_exclude_unset=True)
    async def skills(scene: str, _: str = Depends(user)):
        chat_for(scene)
        try:
            async with write_lock:
                return await asyncio.to_thread(skills_state, scene)
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f"{type(error).__name__}: {error}") from error

    def write_role(saved, path: Path, directory: str, field: Literal["tools", "skills"],
                   value: str | list[str]) -> dict:
        require_persona_target(path, directory)
        persona = load_persona(path).model_copy(update={field: value})
        affected = [key for key, value in saved.scenes.items() if value.persona == path]
        # A role no group uses is still checked against one group, so unknown names are refused.
        for key in affected or list(saved.scenes)[:1]:
            build_tools(saved.scene_config(key), persona, platform=saved.delivery == "onebot", host_management=True)
            if saved.worker is not None:
                select_skills(scene_skill_catalog(saved, key), persona.skills)
        metadata = persona.model_dump(exclude={"voice", "boundaries", "examples", "knowledge"})
        descriptor, name = tempfile.mkstemp(prefix=".persona-", suffix=".yaml", dir=path)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                yaml.safe_dump(metadata, stream, allow_unicode=True, sort_keys=False)
            temporary.replace(path / "persona.yaml")
        finally:
            temporary.unlink(missing_ok=True)
        return {"directory": str(path), "persona": {"id": persona.id, "name": persona.name},
                "saved": value, "affected_scenes": affected}

    def reference_scene(path: Path, saved, scene: str | None) -> str:
        """The group whose configuration decides which tools and skills a role could use."""
        if scene is not None:
            chat_for(scene)
            return scene
        affected = [key for key, value in saved.scenes.items() if value.persona == path and key in runtime.chats]
        candidates = affected or list(runtime.chats)
        if not candidates:
            raise HTTPException(409, "尚无群聊，无法判断角色可用的工具")
        return candidates[0]

    def role_abilities(key: str, scene: str | None) -> dict:
        saved = load_host_config(root)
        path = runtime.personas.find(key, saved).path
        persona = load_persona(path)
        reference = reference_scene(path, saved, scene)
        chat = runtime.chats[reference]
        host_management = chat.toolset.host_management is not None
        tools = []
        for tool in tool_catalog(platform=chat.config.delivery == "onebot"):
            function = tool["function"]
            name = function["name"]
            tools.append({"name": name, "description": function["description"], "summary": function["description"],
                          "parameters": function["parameters"], "instructions": None, "source": None,
                          "deferred": name in DEFERRED_NAMES,
                          "reasons": [reason for reason in tool_unavailable_reasons(
                              chat.config, persona, name, host_management=host_management)
                              if reason != "角色未允许此工具"]})
        previews = [] if runtime.plugins is None else runtime.plugins.tool_previews(reference)
        previews += [] if runtime.mcp is None else [
            {**tool.discovery, "summary": tool.discovery["description"], "description": tool.description,
             "parameters": tool.definition["function"]["parameters"], "instructions": tool.instructions, "reasons": []}
            for tool in runtime.mcp.tools_for(reference)]
        for preview in previews:
            tools.append({**preview, "deferred": True, "reasons": list(preview["reasons"])})
        catalog = scene_skill_catalog(saved, reference)
        selected = select_skills(catalog, persona.skills) if saved.worker is not None else ()
        directory = None if saved.worker is None else saved.worker.skills_directory
        return {
            "key": key, "directory": str(path), "scene": reference,
            "affected_scenes": [name for name, value in saved.scenes.items() if value.persona == path],
            "tools": {"saved": persona.tools, "catalog": tools},
            "skills": {"saved": persona.skills, "directory": None if directory is None else str(directory),
                       "catalog": [{**skill_info(skill), "selected": skill in selected} for skill in catalog]},
        }

    @app.get("/api/host/personas/{key}/abilities", response_model=responses.RoleAbilities, response_model_exclude_unset=True)
    async def abilities(key: str, scene: str | None = None, _: str = Depends(user)):
        try:
            async with write_lock:
                return await asyncio.to_thread(role_abilities, key, scene)
        except LookupError as error:
            raise HTTPException(404, "角色库中不存在此角色") from error
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f"{type(error).__name__}: {error}") from error

    async def save_for_role(key: str, directory: str, field: Literal["tools", "skills"],
                            value: str | list[str]) -> dict:
        def write() -> dict:
            saved = load_host_config(root)
            return write_role(saved, runtime.personas.find(key, saved).path, directory, field, value)

        try:
            async with write_lock:
                result = await asyncio.to_thread(write)
        except LookupError as error:
            raise HTTPException(404, "角色库中不存在此角色") from error
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f"{type(error).__name__}: {error}") from error
        return {**result, **await apply_saved(runtime, Path(result["directory"]))}

    @app.put("/api/host/personas/{key}/tools", response_model=responses.RolePermission, response_model_exclude_unset=True)
    async def save_role_tools(key: str, changes: RoleTools, _: str = Depends(user)):
        return await save_for_role(key, changes.directory, "tools", changes.tools)

    @app.put("/api/host/personas/{key}/skills", response_model=responses.RolePermission, response_model_exclude_unset=True)
    async def save_role_skills(key: str, changes: RoleSkills, _: str = Depends(user)):
        return await save_for_role(key, changes.directory, "skills", changes.skills)
