"""Send only registered task deliverables, carrying their content in the OneBot upload request."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from .messages import UploadResult
from ..configuration.tasks import WorkerSettings
from ..work.resources import ResourceFileRef, TaskResources
from ..work.store import TaskStore

# NapCat caps one WebSocket message at 50 MiB; base64 adds a third, the request JSON a little more.
MAX_UPLOAD_BYTES = 36 * 1024 * 1024


class SendFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    task_id: int = Field(gt=0, strict=True)
    file_id: int = Field(gt=0, strict=True)


SEND_FILE_TOOL = {"type": "function", "function": {
    "name": "send_file",
    "description": "把当前场景任务已登记的交付文件上传到本场景 QQ 群或私聊，单个文件最大 36MiB。"
    "只接受 task_id 和 file_id；上传成功时返回平台 file_id，结果未知时用 task status 查看已保存的回执。",
    "parameters": SendFileArguments.model_json_schema(),
}}


def read_delivery(settings: WorkerSettings, records: TaskStore, scene: str, args: SendFileArguments) -> bytes:
    """Read the registered delivery copy whole; its size must still match the registration."""
    file = records.get_file(scene, args.task_id, args.file_id)
    if file.size > MAX_UPLOAD_BYTES:
        raise ValueError(f"交付文件 {file.name} 有 {file.size} 字节，超过单次上传上限 {MAX_UPLOAD_BYTES} 字节")
    opened = TaskResources(settings, records).open(scene, ResourceFileRef(
        scope='deliveries', task_id=args.task_id, file_id=args.file_id))
    with opened.stream as source:
        data = source.read(MAX_UPLOAD_BYTES + 1)
    if len(data) != file.size:
        raise ValueError(f"Registered task file size changed: {file.path}; "
                         f"registered={file.size}, actual={len(data)}")
    return data


async def execute_send_file(
    records: TaskStore,
    scene: str,
    args: SendFileArguments,
    *,
    settings: WorkerSettings,
    upload: Callable[[str, str, str], Awaitable[UploadResult]],
    on_update: Callable[[], None],
) -> str:
    """Record the full receipt; return only actionable file and delivery facts to the model."""
    file = records.get_file(scene, args.task_id, args.file_id)
    data = await asyncio.to_thread(read_delivery, settings, records, scene, args)

    event_id = records.start_file_upload(file, hashlib.sha256(data).hexdigest())
    on_update()
    try:
        result = await upload(scene, "base64://" + base64.b64encode(data).decode("ascii"), file.name)
    except asyncio.CancelledError as error:
        records.finish_file_upload(scene, file.task_id, event_id, UploadResult(
            "unconfirmed", None, f"{type(error).__name__}: {error}", None,
        ))
        on_update()
        raise
    except Exception as error:
        result = UploadResult(
            "unconfirmed", None, f"{type(error).__name__}: {error}", None,
        )
    event = records.finish_file_upload(scene, file.task_id, event_id, result)
    on_update()
    return json.dumps({"task_id": file.task_id, "event_id": event_id,
                       **{key: event[key] for key in ('file_id', 'name', 'size', 'status',
                                                     'platform_file_id', 'error')}},
                      ensure_ascii=False, allow_nan=False, separators=(',', ':'))
