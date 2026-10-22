"""Saved role sticker index and raw assets; running images are immutable snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
from pathlib import Path
import stat
import tempfile
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import field_validator

from .. import responses
from ...configuration.types import STRICT
from ...config import HostConfig, load_host_config
from .persona import PersonaFileChange, apply_saved, finish_role_write, validate_dependencies
from ....image_assets import MAX_IMAGE_BYTES, inspect_image
from ...runtime.network import NetworkRuntime
from ...persona.profile import PersonaTarget, parse_persona_files, read_persona_files, require_persona_target
from ...persona.stickers import StickerEntry, parse_sticker_index, sticker_entries
import yaml


class StickerAssetName(PersonaTarget):
    model_config = STRICT
    file: str

    @field_validator('file')
    @classmethod
    def relative_asset(cls, value: str) -> str:
        if (value == 'index.yaml' or '\\' in value
                or any(part in {'', '.', '..'} or any(ord(char) < 32 for char in part)
                       for part in value.split('/'))):
            raise ValueError(f'表情原件须为stickers内的相对文件，不能是index.yaml：{value!r}')
        return value


class StickerEntries(PersonaTarget):
    """The sticker index as the panel form edits it; saved as stickers/index.yaml."""
    model_config = STRICT
    entries: list[StickerEntry]


def asset_target(persona: Path, name: str) -> Path:
    root = persona / 'stickers'
    target = root.joinpath(*name.split('/'))
    for path in (root, *target.parents):
        if path == persona:
            break
        if path.is_symlink():
            raise ValueError(f'表情原件不能穿越目录链接：{path}')
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'表情原件不能通过链接或离开stickers：{target}')
    return target


def source_index(persona: Path) -> str | None:
    path = asset_target(persona, 'index.yaml')
    if not path.exists():
        return None
    if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
        raise ValueError(f'表情索引不是常规文件：{path}')
    raw = path.read_bytes()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError(f'{path}: invalid UTF-8: {error}; raw={raw[error.start:error.end + 30]!r}') from error


def atomic_file(target: Path, content: bytes, *, create: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.persona-sticker-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
        if create:
            os.link(temporary, target)
        else:
            temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def register_host_persona_stickers(app: FastAPI, *, root: Path, runtime: NetworkRuntime,
                                   user: Callable[[Request], str], write_lock: asyncio.Lock) -> None:
    def configured(key: str) -> tuple[HostConfig, Path]:
        config = load_host_config(root)
        return config, runtime.personas.find(key, config).path

    def selected(key: str, directory: str) -> tuple[HostConfig, Path]:
        config, path = configured(key)
        require_persona_target(path, directory)
        return config, path

    def state(key: str) -> dict:
        config, persona = configured(key)
        index = source_index(persona)
        files = []
        directory = persona / 'stickers'

        def listing_error(error: OSError) -> None:
            raise error

        if directory.exists():
            if not directory.is_dir():
                raise ValueError(f'表情资源路径不是目录：{directory}')
            for folder, directories, filenames in os.walk(directory, followlinks=False, onerror=listing_error):
                for name in (*directories, *filenames):
                    actual = Path(folder) / name
                    relative = actual.relative_to(directory).as_posix()
                    asset_target(persona, relative)
                    mode = actual.stat(follow_symlinks=False).st_mode
                    if stat.S_ISDIR(mode):
                        continue
                    if not stat.S_ISREG(mode):
                        raise ValueError(f'表情资源不是常规文件：{actual}')
                    if relative != 'index.yaml':
                        files.append({'file': relative, 'bytes': actual.stat().st_size})
        return {'key': key, 'saved_path': str(persona),
                'index_content': index, 'files': sorted(files, key=lambda item: item['file']),
                'entries': None if index is None else [entry.model_dump() for entry in
                                                       sticker_entries(directory / 'index.yaml', index)],
                'affected_scenes': [scene for scene, value in config.scenes.items() if value.persona == persona]}

    def save_index(key: str, directory: str, content: str) -> dict:
        config, persona = selected(key, directory)
        images = parse_sticker_index(persona, content)
        candidate = parse_persona_files(persona, read_persona_files(persona), stickers=images)
        validate_dependencies(config, persona, candidate)
        target = asset_target(persona, 'index.yaml')
        atomic_file(target, content.encode('utf-8'), create=not target.exists())
        return state(key)

    def upload(key: str, item: StickerAssetName, data: bytes) -> dict:
        _, persona = selected(key, item.directory)
        index = source_index(persona)
        if index is None:
            raise ValueError('尚无stickers/index.yaml；先明确保存索引（可为[]），再上传原件')
        sticker_entries(persona / 'stickers' / 'index.yaml', index)
        target = asset_target(persona, item.file)
        if target.exists():
            raise FileExistsError(f'文件已存在，请换一个文件名：{target}')
        mime, width, height, animated = inspect_image(data)
        atomic_file(target, data, create=True)
        return {'file': item.file, 'bytes': len(data), 'mime_type': mime, 'width': width,
                'height': height, 'animated': animated, 'registered_automatically': False,
                'notice': '原件已存到角色包，请编辑并保存表情索引。'}

    def delete(key: str, item: StickerAssetName) -> dict:
        _, persona = selected(key, item.directory)
        index = source_index(persona)
        if index is None:
            raise ValueError('无表情索引，不能确认原件是否被引用；先明确建立索引')
        if any(entry.file == item.file for entry in sticker_entries(persona / 'stickers' / 'index.yaml', index)):
            raise ValueError('原件仍被保存索引引用；先明确删除索引项并保存，再删除原件')
        target = asset_target(persona, item.file)
        if not stat.S_ISREG(target.stat(follow_symlinks=False).st_mode):
            raise ValueError(f'只删除常规表情原件，不删除目录：{target}')
        target.unlink()
        return {'file': item.file, 'deleted': True, 'notice': '未引用原件已删除。'}

    async def operation(function: Callable[..., dict], *args: object, writing: bool = False) -> dict:
        try:
            async with write_lock:
                return await finish_role_write(function, *args) if writing else await asyncio.to_thread(function, *args)
        except LookupError as error:
            raise HTTPException(404, '角色库里没有这个角色') from error
        except FileExistsError as error:
            raise HTTPException(409, str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f'{type(error).__name__}: {error}') from error

    @app.get('/api/host/personas/{key}/sticker-files', response_model=responses.RoleStickers, response_model_exclude_unset=True)
    async def listing(key: str, response: Response, _: str = Depends(user)):
        response.headers['Cache-Control'] = 'no-store'
        return await operation(state, key)

    @app.put('/api/host/personas/{key}/sticker-files/index', response_model=responses.RoleStickers, response_model_exclude_unset=True)
    async def index_write(key: str, item: PersonaFileChange, _: str = Depends(user)):
        result = await operation(save_index, key, item.directory, item.content, writing=True)
        return {**result, **await apply_saved(runtime, Path(result['saved_path']))}

    @app.put('/api/host/personas/{key}/sticker-files/entries', response_model=responses.RoleStickers, response_model_exclude_unset=True)
    async def entries_write(key: str, item: StickerEntries, _: str = Depends(user)):
        content = yaml.safe_dump([entry.model_dump() for entry in item.entries], allow_unicode=True, sort_keys=False)
        result = await operation(save_index, key, item.directory, content, writing=True)
        return {**result, **await apply_saved(runtime, Path(result['saved_path']))}

    @app.post('/api/host/personas/{key}/sticker-files/image')
    async def image_upload(key: str, file: UploadFile, name: str = Form(), directory: str = Form(min_length=1), _: str = Depends(user)):
        try:
            data = await file.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(413, f'表情原件超过{MAX_IMAGE_BYTES}字节')
            try:
                item = StickerAssetName.model_validate({'file': name, 'directory': directory})
            except ValueError as error:
                raise HTTPException(422, f'{error}; raw file={name!r}') from error
            return await operation(upload, key, item, data, writing=True)
        finally:
            await file.close()

    @app.delete('/api/host/personas/{key}/sticker-files/image')
    async def image_delete(key: str, item: StickerAssetName, _: str = Depends(user)):
        return await operation(delete, key, item, writing=True)

    @app.get('/api/host/personas/{key}/sticker-files/image')
    async def image_read(key: str, item: Annotated[StickerAssetName, Query()], _: str = Depends(user)):
        def read() -> dict:
            _, persona = selected(key, item.directory)
            target = asset_target(persona, item.file)
            if not stat.S_ISREG(target.stat(follow_symlinks=False).st_mode):
                raise ValueError(f'表情原件不是常规文件：{target}')
            with target.open('rb') as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
            mime, _, _, _ = inspect_image(data)
            return {'data': data, 'mime': mime}

        result = await operation(read)
        return Response(result['data'], media_type=result['mime'], headers={'Cache-Control': 'no-store'})
