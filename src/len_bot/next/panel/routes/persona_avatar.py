"""Authenticated avatar editing of one role in the library; a saved change reaches the scenes running it."""

import asyncio
from collections.abc import Callable
import os
from pathlib import Path
import tempfile

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, UploadFile

from .. import responses
from ...config import HostConfig, load_host_config
from .persona import apply_saved, finish_role_write
from ....image_assets import MAX_IMAGE_BYTES, OriginalImage
from ...runtime.network import NetworkRuntime
from ...persona.avatar import avatar_file, load_avatar, parse_avatar
from ...persona.profile import PersonaTarget, require_persona_target


def image_info(image: OriginalImage | None) -> dict | None:
    if image is None:
        return None
    return {'mime_type': image.mime_type, 'bytes': len(image.data), 'width': image.width,
            'height': image.height, 'animated': image.animated}


def register_host_persona_avatar(app: FastAPI, *, root: Path, runtime: NetworkRuntime,
                                user: Callable[[Request], str], write_lock: asyncio.Lock) -> None:
    def configured(key: str) -> tuple[HostConfig, Path]:
        config = load_host_config(root)
        return config, runtime.personas.find(key, config).path

    def describe(config: HostConfig, path: Path, saved: OriginalImage | None) -> dict:
        return {'directory': str(path), 'saved': {'directory': str(path), 'path': str(path / 'avatar.png'),
                                                  'image': image_info(saved)},
                'affected_scenes': [key for key, value in config.scenes.items() if value.persona == path]}

    def state(key: str) -> dict:
        config, path = configured(key)
        return describe(config, path, load_avatar(path))

    def selected(key: str, directory: str) -> tuple[HostConfig, Path]:
        config, path = configured(key)
        require_persona_target(path, directory)
        return config, path

    def save(key: str, directory: str, data: bytes) -> dict:
        config, path = selected(key, directory)
        image = parse_avatar(data)
        target = avatar_file(path)
        descriptor, name = tempfile.mkstemp(prefix='.persona-avatar-', dir=path)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(image.data)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return describe(config, path, image)

    def delete(key: str, directory: str) -> dict:
        config, path = selected(key, directory)
        avatar_file(path).unlink()
        return describe(config, path, None)

    def read(key: str, directory: str) -> dict:
        _, path = selected(key, directory)
        image = load_avatar(path)
        if image is None:
            raise FileNotFoundError('这个角色没有头像')
        return {'data': image.data}

    async def operation(function: Callable[..., dict], *args: object, writing: bool = False) -> dict:
        try:
            async with write_lock:
                return await finish_role_write(function, *args) if writing else await asyncio.to_thread(function, *args)
        except LookupError as error:
            raise HTTPException(404, '角色库里没有这个角色') from error
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, OSError) as error:
            raise HTTPException(422 if isinstance(error, ValueError) else 500,
                                f'{type(error).__name__}: {error}') from error

    @app.get('/api/host/personas/{key}/avatar', response_model=responses.RoleAvatar, response_model_exclude_unset=True)
    async def metadata(key: str, response: Response, _: str = Depends(user)):
        response.headers['Cache-Control'] = 'no-store'
        return await operation(state, key)

    @app.get('/api/host/personas/{key}/avatar/image')
    async def preview(key: str, directory: str, _: str = Depends(user)):
        value = await operation(read, key, directory)
        return Response(value['data'], media_type='image/png', headers={'Cache-Control': 'no-store'})

    @app.put('/api/host/personas/{key}/avatar', response_model=responses.RoleAvatar, response_model_exclude_unset=True)
    async def upload(key: str, file: UploadFile, directory: str = Form(min_length=1), _: str = Depends(user)):
        try:
            data = await file.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(413, f'角色头像超过{MAX_IMAGE_BYTES}字节')
            result = await operation(save, key, directory, data, writing=True)
        finally:
            await file.close()
        return {**result, **await apply_saved(runtime, Path(result['directory']))}

    @app.delete('/api/host/personas/{key}/avatar', response_model=responses.RoleAvatar, response_model_exclude_unset=True)
    async def remove(key: str, item: PersonaTarget, _: str = Depends(user)):
        result = await operation(delete, key, item.directory, writing=True)
        return {**result, **await apply_saved(runtime, Path(result['directory']))}
