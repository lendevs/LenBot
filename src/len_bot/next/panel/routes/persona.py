"""The role library and the files of its packages; a saved edit reaches the scenes running that role."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
import yaml

from .. import responses
from ...chat.tools import build_tools
from ...configuration.types import STRICT
from ...config import HostConfig, load_host_config
from ...learning.store import LearningStore
from ...runtime.network import NetworkRuntime
from ...tools.skills import select_skills
from ...plugins.manifest import scene_skill_catalog
from ...chat.context import character_material, expression_rule, style_text
from ...persona.profile import (EXPRESSION_FILES, Example, Persona, PersonaTarget, Style, load_persona,
                      parse_persona_files, read_persona_files, require_persona_target, save_persona_files,
                      select_examples, select_style)
from ...prompt_files import read_prompt
from ...persona.knowledge import parse_knowledge_document
from ...persona.packages import MAX_UPLOAD_BYTES, export_package
from ...runtime.logs import error_text
from ...runtime.personas import copy_role, create_role, delete_role, import_role


PersonaFilename = Literal["persona.yaml", "voice.md", "boundaries.md", "examples.yaml",
                          "response_choice.md", "expression_principles.md", "chat_examples.md"]


class PersonaFileChange(PersonaTarget):
    model_config = STRICT
    content: str


class PersonaProfile(BaseModel):
    """The parts of a role package an operator edits in the panel form; id, tools and skills stay as saved."""

    model_config = STRICT
    name: str
    brief: str
    behavior: str
    self_reference: list[str]
    aliases: list[str]
    styles: list[Style]
    example_tags: list[str]
    voice: str
    boundaries: str
    examples: list[Example]


class PersonaProfileChange(PersonaTarget):
    model_config = STRICT
    profile: PersonaProfile


PROFILE_METADATA = ('name', 'brief', 'behavior', 'self_reference', 'aliases', 'styles', 'example_tags')


def profile_files(files: dict[str, str], profile: PersonaProfile) -> dict[str, str]:
    """Rewrite the four role files from the form; other persona.yaml fields keep their saved values."""
    metadata = yaml.safe_load(files['persona.yaml'])
    if not isinstance(metadata, dict):
        raise ValueError('persona.yaml 不是 YAML 对象')
    values = profile.model_dump(exclude_none=True)
    metadata.update({key: values[key] for key in PROFILE_METADATA})
    examples = [{key: value for key, value in item.items() if key != 'tags' or value} for item in values['examples']]
    dump = lambda value: yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    return {'persona.yaml': dump(metadata), 'voice.md': profile.voice, 'boundaries.md': profile.boundaries,
            'examples.yaml': dump(examples)}


class ExpressionExample(PersonaTarget):
    """An operator-confirmed example taken from one adopted expression; text may be edited first."""

    model_config = STRICT
    expression_id: int
    context: str = Field(min_length=1)
    line: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("context", "line")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("样例的场景和台词不能只包含空白")
        return value

    @field_validator("tags")
    @classmethod
    def nonblank_tags(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError("标签不能为空白或重复")
        return values


async def finish_role_write[T](operation: Callable[..., T], *args: object) -> T:
    """Keep the caller's protected role-write lifetime until already-started filesystem work ends."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancelled:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            task.result()
        except BaseException as error:
            cancelled.add_note(f'Role write also failed: {type(error).__name__}: {error}')
            raise cancelled from error
        raise


class KnowledgeFilename(PersonaTarget):
    model_config = STRICT
    filename: str

    @field_validator('filename')
    @classmethod
    def relative_markdown(cls, value: str) -> str:
        if (not value.endswith('.md') or '\\' in value
                or any(part in {'', '.', '..'} or any(ord(char) < 32 for char in part)
                       for part in value.split('/'))):
            raise ValueError(f'知识文件须为 knowledge 目录内的相对 Markdown 路径：{value!r}')
        return value


class KnowledgeChange(KnowledgeFilename):
    content: str


def knowledge_target(root: Path, filename: str) -> Path:
    directory = root / 'knowledge'
    target = directory.joinpath(*filename.split('/'))
    for ancestor in (directory, *target.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ValueError(f'角色资料编辑不穿越目录链接：{ancestor}')
    if target.is_symlink() or not target.resolve().is_relative_to(directory.resolve()):
        raise ValueError(f'角色资料编辑不能通过链接或离开 knowledge 目录：{target}')
    return target


def validate_dependencies(config: HostConfig, path: Path, candidate: Persona) -> list[str]:
    affected = [key for key, value in config.scenes.items() if value.persona == path]
    for key in affected:
        build_tools(config.scene_config(key), candidate, platform=config.delivery == 'onebot', host_management=True)
        if config.worker is not None:
            select_skills(scene_skill_catalog(config, key), candidate.skills)
    return affected


def append_example(content: str, example: dict) -> str:
    """Append one block item and keep the operator's existing text, comments and order."""
    try:
        current = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ValueError(f"examples.yaml 不是合法 YAML：{error}") from error
    if not isinstance(current, list):
        raise ValueError("examples.yaml 不是 YAML 列表")
    if any(isinstance(item, dict) and item.get("context") == example["context"] and item.get("line") == example["line"]
           for item in current):
        raise ValueError("examples.yaml 已有相同场景和台词的样例")
    block = yaml.safe_dump([example], allow_unicode=True, sort_keys=False)
    if current:
        updated = content + ("" if content.endswith("\n") else "\n") + block
    else:
        node = yaml.compose(content)
        # Replace only the empty sequence, retaining surrounding comments/document markers.
        updated = content[:node.start_mark.index] + "\n" + block.rstrip("\n") + content[node.end_mark.index:]
    not_block = "examples.yaml 不是可在末尾追加的块状列表；请在角色文件编辑器中手动添加"
    try:
        appended = yaml.safe_load(updated)
    except yaml.YAMLError as error:
        raise ValueError(not_block) from error
    if appended != [*current, example]:
        raise ValueError(not_block)
    return updated


class RoleCreate(BaseModel):
    model_config = STRICT
    folder: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)


class RoleScenes(BaseModel):
    model_config = STRICT
    scenes: list[str] = Field(min_length=1)


def role_failure(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(404, '角色库中不存在此角色')
    if isinstance(error, FileExistsError):
        return HTTPException(409, str(error))
    if isinstance(error, FileNotFoundError):
        return HTTPException(404, str(error))
    return HTTPException(422 if isinstance(error, ValueError) else 500, f'{type(error).__name__}: {error}')


async def apply_saved(runtime: NetworkRuntime, path: Path) -> dict:
    """Hand a saved role edit to the scenes running it; one busy in a turn takes it afterwards."""
    try:
        done, _ = await runtime.personas.settle(runtime.personas.reload(path))
    except Exception as error:
        return {'applied': False, 'apply_error': f'已保存，但未能应用到运行中的群：{error_text(error)}'}
    return {'applied': done, 'apply_error': None}


def register_host_persona(app: FastAPI, *, root: Path, runtime: NetworkRuntime,
                          user: Callable[[Request], str], write_lock: asyncio.Lock) -> None:
    personas = runtime.personas

    def require_scene(scene: str) -> None:
        if scene not in runtime.chats:
            raise HTTPException(404, "当前宿主未配置此场景")

    def located(key: str) -> tuple[HostConfig, Path]:
        config = load_host_config(root)
        return config, personas.find(key, config).path

    def running_persona(path: Path) -> Persona | None:
        return next((chat.persona for chat in runtime.chats.values() if chat.config.persona == path), None)

    def affected(config: HostConfig, path: Path) -> list[str]:
        return [key for key, value in config.scenes.items() if value.persona == path]

    def describe(key: str) -> dict:
        saved = load_host_config(root)
        listing = personas.library(saved)
        role = next((item for item in listing if item.key == key), None)
        if role is None:
            raise KeyError(key)
        return personas.describe(role, saved, listing)

    @app.get('/api/host/personas', response_model=responses.RoleLibrary, response_model_exclude_unset=True)
    async def library(response: Response, _: str = Depends(user)):
        response.headers['Cache-Control'] = 'no-store'

        def read() -> dict:
            saved = load_host_config(root)
            listing = personas.library(saved)
            return {'roles': [personas.describe(role, saved, listing) for role in listing]}

        try:
            async with write_lock:
                return await asyncio.to_thread(read)
        except (ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.post('/api/host/personas', response_model=responses.Role, response_model_exclude_unset=True)
    async def create(item: RoleCreate, _: str = Depends(user)):
        try:
            async with write_lock:
                await finish_role_write(lambda: create_role(root, load_host_config(root), item.folder, item.name))
                return await asyncio.to_thread(describe, item.folder)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.post('/api/host/personas/{key}/copy', response_model=responses.Role, response_model_exclude_unset=True)
    async def copy(key: str, item: RoleCreate, _: str = Depends(user)):
        def write() -> None:
            saved = load_host_config(root)
            copy_role(root, saved, personas.find(key, saved), item.folder, item.name)

        try:
            async with write_lock:
                await finish_role_write(write)
                return await asyncio.to_thread(describe, item.folder)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.delete('/api/host/personas/{key}', response_model=responses.RoleDeleted, response_model_exclude_unset=True)
    async def delete(key: str, _: str = Depends(user)):
        def remove() -> dict:
            saved = load_host_config(root)
            role = personas.find(key, saved)
            running = {chat.config.persona for chat in runtime.chats.values()}
            return {'moved_to': str(delete_role(root, saved, role, running))}

        try:
            async with write_lock:
                return await finish_role_write(remove)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.post('/api/host/personas/{key}/scenes', response_model=responses.RoleScenes, response_model_exclude_unset=True)
    async def use_in(key: str, item: RoleScenes, _: str = Depends(user)):
        for scene in item.scenes:
            require_scene(scene)

        async def one(scene: str) -> dict:
            try:
                done, result = await personas.settle(personas.switch(scene, key))
            except LookupError:
                return {'scene': scene, 'status': 'failed', 'error': '角色库中不存在此角色'}
            except Exception as error:
                return {'scene': scene, 'status': 'failed', 'error': error_text(error)}
            return result if done else {'scene': scene, 'status': 'pending'}

        return {'results': list(await asyncio.gather(*(one(scene) for scene in dict.fromkeys(item.scenes))))}

    @app.get('/api/host/personas/{key}/package')
    async def download_package(key: str, _: str = Depends(user)):
        try:
            async with write_lock:
                data = await asyncio.to_thread(lambda: export_package(located(key)[1]))
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error
        return Response(data, media_type='application/zip', headers={
            'Content-Disposition': f'attachment; filename="persona-{key}.zip"', 'Cache-Control': 'no-store'})

    @app.post('/api/host/personas/import', response_model=responses.RoleImported, response_model_exclude_unset=True)
    async def upload_package(file: UploadFile, name: str = Form(min_length=1, max_length=64),
                             _: str = Depends(user)):
        try:
            data = await file.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, '角色 ZIP 上传超过 64 MiB')
            async with write_lock:
                return await finish_role_write(lambda: import_role(root, load_host_config(root), name, data))
        except FileExistsError as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f'{type(error).__name__}: {error}') from error
        finally:
            await file.close()

    @app.get('/api/host/scenes/{scene}/persona-location', response_model=responses.RoleLocation, response_model_exclude_unset=True)
    async def location(scene: str, response: Response, _: str = Depends(user)):
        require_scene(scene)
        response.headers['Cache-Control'] = 'no-store'
        def read() -> dict:
            saved = load_host_config(root)
            if scene not in saved.scenes:
                raise ValueError('场景已从保存配置移除，不能读取其角色位置')
            path = saved.scenes[scene].persona
            return {'saved_path': str(path), 'running_path': str(runtime.chats[scene].config.persona),
                    'affected_scenes': affected(saved, path)}
        try:
            async with write_lock:
                return await asyncio.to_thread(read)
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500, f'{type(error).__name__}: {error}') from error

    def files_state(key: str, edit: tuple[str, str, str] | None = None, *, path: Path | None = None) -> dict:
        config, located_path = located(key) if path is None else (load_host_config(root), path)
        path = located_path
        if edit is not None:
            require_persona_target(path, edit[2])
        files = read_persona_files(path)
        expression = {name: (path / name).read_text(encoding="utf-8") if (path / name).is_file() else ""
                      for name in EXPRESSION_FILES}
        if edit is not None:
            (expression if edit[0] in EXPRESSION_FILES else files)[edit[0]] = edit[1]
        candidate = parse_persona_files(path, files)
        current = running_persona(path)
        if edit is not None and current is not None and candidate.id != current.id:
            raise ValueError('有群正在使用此角色，不能修改角色 ID；需要新 ID 时请复制角色')
        scenes = validate_dependencies(config, path, candidate)
        if edit is not None and edit[0] in EXPRESSION_FILES and not edit[1].strip():
            # A blank expression file means the framework version, so none is kept.
            (path / edit[0]).unlink(missing_ok=True)
            expression[edit[0]] = ""
        elif edit is not None:
            descriptor, name = tempfile.mkstemp(prefix=".persona-", dir=path)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(edit[1])
                temporary.replace(path / edit[0])
            finally:
                temporary.unlink(missing_ok=True)
        return {"saved": {**files, **expression}, "running": None if current is None else current.model_dump(),
                'saved_path': str(path), "affected_scenes": scenes,
                "defaults": {name: read_prompt(bundled) for name, bundled in EXPRESSION_FILES.items()}}

    def knowledge_state(key: str, change: KnowledgeChange | KnowledgeFilename | None = None,
                        action: Literal['create', 'write', 'delete'] | None = None) -> dict:
        config, path = located(key)
        if change is not None:
            require_persona_target(path, change.directory)
        candidate = load_persona(path)
        if change is not None:
            target = knowledge_target(path, change.filename)
            if action == 'create':
                if target.exists():
                    raise FileExistsError(f'角色资料已存在，请更换文件名：{target}')
            elif change.filename not in candidate.knowledge:
                raise FileNotFoundError(f'角色包没有此知识文件：{target}')
            documents = dict(candidate.knowledge)
            if isinstance(change, KnowledgeChange):
                documents[change.filename] = parse_knowledge_document(target, change.content)
            else:
                del documents[change.filename]
            candidate = candidate.model_copy(update={'knowledge': documents})
        scenes = validate_dependencies(config, path, candidate)
        if change is not None:
            if isinstance(change, KnowledgeChange):
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(prefix='.persona-knowledge-', dir=target.parent)
                temporary = Path(name)
                try:
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(change.content.encode('utf-8'))
                    if action == 'create':
                        os.link(temporary, target)
                    else:
                        temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                target.unlink()
        current_document = None
        if isinstance(change, KnowledgeChange):
            saved_document = candidate.knowledge[change.filename]
            current_document = {'filename': change.filename, 'saved_path': str(path), 'content': saved_document.content,
                                'tags': saved_document.tags}
        return {'key': key, 'saved_path': str(path),
                'saved_persona': {'id': candidate.id, 'name': candidate.name},
                'affected_scenes': scenes,
                'document': current_document,
                'files': [{'filename': filename, 'tags': document.tags, 'chars': len(document.content)}
                          for filename, document in sorted(candidate.knowledge.items())]}

    @app.get('/api/host/personas/{key}/knowledge', response_model=responses.RoleKnowledge, response_model_exclude_unset=True)
    async def knowledge_listing(key: str, response: Response, _: str = Depends(user)):
        response.headers['Cache-Control'] = 'no-store'
        try:
            async with write_lock:
                return await asyncio.to_thread(knowledge_state, key)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.get('/api/host/personas/{key}/knowledge/document', response_model=responses.KnowledgeDocument, response_model_exclude_unset=True)
    async def knowledge_document(key: str, response: Response,
                                 item: Annotated[KnowledgeFilename, Query()], _: str = Depends(user)):
        response.headers['Cache-Control'] = 'no-store'

        def read() -> dict:
            _, path = located(key)
            require_persona_target(path, item.directory)
            candidate = load_persona(path)
            if item.filename not in candidate.knowledge:
                raise FileNotFoundError(f'保存角色包没有此资料：{item.filename!r}')
            saved = candidate.knowledge[item.filename]
            return {'filename': item.filename, 'saved_path': str(path), 'content': saved.content, 'tags': saved.tags}

        try:
            async with write_lock:
                return await asyncio.to_thread(read)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    async def write_knowledge(key: str, item: KnowledgeChange | KnowledgeFilename,
                              action: Literal['create', 'write', 'delete']):
        try:
            async with write_lock:
                result = await finish_role_write(knowledge_state, key, item, action)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error
        return {**result, **await apply_saved(runtime, Path(result['saved_path']))}

    @app.post('/api/host/personas/{key}/knowledge/document', response_model=responses.RoleKnowledge, response_model_exclude_unset=True)
    async def knowledge_create(key: str, item: KnowledgeChange, _: str = Depends(user)):
        return await write_knowledge(key, item, 'create')

    @app.put('/api/host/personas/{key}/knowledge/document', response_model=responses.RoleKnowledge, response_model_exclude_unset=True)
    async def knowledge_write(key: str, item: KnowledgeChange, _: str = Depends(user)):
        return await write_knowledge(key, item, 'write')

    @app.delete('/api/host/personas/{key}/knowledge/document', response_model=responses.RoleKnowledge, response_model_exclude_unset=True)
    async def knowledge_delete(key: str, item: KnowledgeFilename, _: str = Depends(user)):
        return await write_knowledge(key, item, 'delete')

    @app.post("/api/host/scenes/{scene}/persona-examples", response_model=responses.RoleFiles, response_model_exclude_unset=True)
    async def add_example(scene: str, item: ExpressionExample, _: str = Depends(user)):
        require_scene(scene)
        expression = LearningStore(runtime.store).expression(scene, item.expression_id)
        if expression is None:
            raise HTTPException(404, "当前场景不存在此表达候选")
        if expression["status"] != "adopted":
            raise HTTPException(409, "只有已采用的表达可以转成角色样例")
        example = {"context": item.context, "line": item.line, **({"tags": item.tags} if item.tags else {})}

        def write() -> dict:
            saved = load_host_config(root)
            if scene not in saved.scenes:
                raise ValueError("此场景已从保存配置移除，不能追加角色样例")
            path = saved.scenes[scene].persona
            require_persona_target(path, item.directory)
            content = append_example(read_persona_files(path)["examples.yaml"], example)
            return {**files_state('', ("examples.yaml", content, item.directory), path=path), "appended": example}

        try:
            async with write_lock:
                result = await finish_role_write(write)
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f"{type(error).__name__}: {error}") from error
        return {**result, **await apply_saved(runtime, Path(result['saved_path']))}

    def profile_state(key: str, change: PersonaProfileChange | None = None) -> dict:
        config, path = located(key)
        files = read_persona_files(path)
        if change is not None:
            require_persona_target(path, change.directory)
            files = profile_files(files, change.profile)
            validate_dependencies(config, path, parse_persona_files(path, files))
            save_persona_files(path, files)
        persona = parse_persona_files(path, files)
        return {'directory': str(path), 'id': persona.id,
                'profile': PersonaProfile.model_validate(persona.model_dump(include={*PROFILE_METADATA, 'voice', 'boundaries', 'examples'})).model_dump(),
                'affected_scenes': affected(config, path)}

    @app.get('/api/host/personas/{key}/profile', response_model=responses.RoleProfile, response_model_exclude_unset=True)
    async def profile(key: str, _: str = Depends(user)):
        try:
            async with write_lock:
                return await asyncio.to_thread(profile_state, key)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.put('/api/host/personas/{key}/profile', response_model=responses.RoleProfile, response_model_exclude_unset=True)
    async def save_profile(key: str, change: PersonaProfileChange, _: str = Depends(user)):
        try:
            async with write_lock:
                result = await finish_role_write(profile_state, key, change)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error
        return {**result, **await apply_saved(runtime, Path(result['directory']))}

    def draft_files(key: str, change: PersonaProfileChange) -> dict:
        _, path = located(key)
        require_persona_target(path, change.directory)
        files = profile_files(read_persona_files(path), change.profile)
        parse_persona_files(path, files)
        return {'directory': str(path), 'files': files, 'profile': change.profile.model_dump()}

    @app.post('/api/host/personas/{key}/profile/draft', response_model=responses.RoleDraft, response_model_exclude_unset=True)
    async def profile_draft(key: str, change: PersonaProfileChange, _: str = Depends(user)):
        """Return normalized form and role files for import/export or trial; nothing is saved."""
        try:
            async with write_lock:
                return await asyncio.to_thread(draft_files, key, change)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    def preview_state(key: str, scene: str | None) -> dict:
        config, path = located(key)
        if scene is not None and scene not in config.scenes:
            raise ValueError(f'未接入此群：{scene}')
        persona = load_persona(path)
        style = select_style(persona)
        return {
            'scene': scene,
            'sections': [{'name': 'character', 'own': True,
                          'text': character_material(None if scene is None else config.scene_config(scene), persona)},
                         *({'name': name, 'own': name in persona.expression, 'text': expression_rule(persona, name)}
                           for name in EXPRESSION_FILES)],
            'examples': len(select_examples(persona)),
            'styles': [style.model_dump() for style in persona.styles],
            'style': None if style is None else style_text(style),
        }

    @app.get('/api/host/personas/{key}/preview', response_model=responses.RolePreview, response_model_exclude_unset=True)
    async def preview(key: str, response: Response, scene: str | None = Query(None, max_length=256),
                      _: str = Depends(user)):
        # Each read draws the style again.
        response.headers['Cache-Control'] = 'no-store'
        try:
            return await asyncio.to_thread(preview_state, key, scene)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.get("/api/host/personas/{key}/files", response_model=responses.RoleFiles, response_model_exclude_unset=True)
    async def files(key: str, _: str = Depends(user)):
        try:
            async with write_lock:
                return await asyncio.to_thread(files_state, key)
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error

    @app.put("/api/host/personas/{key}/files/{filename}", response_model=responses.RoleFiles, response_model_exclude_unset=True)
    async def save(key: str, filename: PersonaFilename, item: PersonaFileChange,
                   _: str = Depends(user)):
        try:
            async with write_lock:
                result = await finish_role_write(files_state, key, (filename, item.content, item.directory))
        except (LookupError, ValueError, OSError) as error:
            raise role_failure(error) from error
        return {**result, **await apply_saved(runtime, Path(result['saved_path']))}
