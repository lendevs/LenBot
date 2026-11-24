"""Read one saved OneBot image position and cache its prepared pixels and description."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..configuration.chat import ImageSettings
from ..tools.http_read import fetch_public
from ..storage.store import ImageAsset, Store
from ..trials.replay_images import RecordedImages


class LookArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1)
    image: int = Field(default=1, gt=0)
    refresh: bool = False

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must be a nonblank platform message ID")
        return value


LOOK_TOOL = {"type": "function", "function": {
    "name": "look",
    "description": "查看当前场景已保存消息里的第几张图片。message 是原平台消息 ID，image 从1开始按原段顺序计数；"
                   "refresh 用已保存的图片重新生成视觉描述。",
    "parameters": LookArguments.model_json_schema(),
}}


# Downloads an inbound file named by a platform reference (Telegram file_id, Feishu file key, OneBot file) up to a byte limit.
MediaFetch = Callable[[dict, int], Awaitable[bytes]]
ONEBOT_URL_TTL_SECONDS = 1800
LOOK_MAX_FRAMES = 6


def _has_url(data: dict[str, object]) -> bool:
    url = data.get("url")
    return isinstance(url, str) and bool(url.strip())


def _has_platform_id(data: dict[str, object]) -> bool:
    return any(
        isinstance(data.get(key), str) and bool(data[key].strip())
        for key in ("file_id", "image_key", "file_key", "file")
    )


def platform_reference(data: dict[str, object]) -> bool:
    """Whether a segment names its file by a platform reference rather than a public URL."""
    return not _has_url(data) and _has_platform_id(data)


def _needs_platform_fetch(data: dict[str, object], *, message_time: float, now: float) -> bool:
    if platform_reference(data):
        return True
    file = data.get("file")
    return isinstance(file, str) and bool(file.strip()) and (now - message_time) > ONEBOT_URL_TTL_SECONDS


def image_url(data: dict[str, object]) -> str:
    url = data.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"image has no readable HTTP(S) url; original data={repr(data)[:300]}")
    return url


async def _prepare_pixels(data: bytes, settings: ImageSettings, *, max_frames: int) -> tuple[bytes, bool, int, int, int]:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", __name__, "prepare",
        str(settings.max_bytes), str(settings.max_pixels), str(settings.max_dimension), str(max_frames),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate(data)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError(f"image preparation failed: {stderr.decode(errors='replace')[-500:]}")
    header, jpeg = stdout.split(b"\n", 1)
    metadata = json.loads(header)
    return jpeg, metadata["animated"], metadata["width"], metadata["height"], metadata.get("frames", 1)


async def prepare_pixels(data: bytes, settings: ImageSettings) -> tuple[bytes, bool, int, int]:
    jpeg, animated, width, height, _ = await _prepare_pixels(data, settings, max_frames=1)
    return jpeg, animated, width, height


def _animated_fields(asset: ImageAsset) -> dict[str, object]:
    if asset.animated and asset.frames > 1:
        return {"animated_first_frame_only": False, "animated_frames": asset.frames}
    return {"animated_first_frame_only": asset.animated}


def _display(scene: str, arguments: LookArguments, asset: ImageAsset, *,
             pixels_reused: bool, description_reused: bool, pixels_source: str) -> str:
    result = {
        "scene": scene, "platform_message_id": arguments.message, "image": arguments.image,
        "jpeg_bytes": len(asset.jpeg), "width": asset.width, "height": asset.height,
        **_animated_fields(asset),
        "fetched_at": datetime.fromtimestamp(asset.fetched_at, timezone.utc).isoformat(),
        "description": asset.description, "description_model": asset.description_model,
        "described_at": (None if asset.described_at is None else
                         datetime.fromtimestamp(asset.described_at, timezone.utc).isoformat()),
        "pixels_reused": pixels_reused, "description_reused": description_reused,
        "pixels_source": pixels_source,
    }
    if asset.animated and asset.frames > 1:
        note = f"\n描述来自准备后的 JPEG；动图已提取 {asset.frames} 个关键帧拼图。"
    elif asset.animated:
        note = "\n描述来自准备后的 JPEG；动图只有第一帧。"
    else:
        note = "\n描述来自准备后的 JPEG。"
    return json.dumps(result, ensure_ascii=False) + note


async def load_look_image(store: Store, scene: str, arguments: LookArguments, settings: ImageSettings, *,
                          recording: RecordedImages | None = None, fake_ip_networks: tuple,
                          public_dns_url: str | None = None,
                          fetch_media: MediaFetch | None = None) -> tuple[ImageAsset, bool, str]:
    """The prepared pixels of one saved image, whether they were cached, and where they came from."""
    message = store.find_message(scene, arguments.message)
    if message is None:
        raise ValueError(f"当前场景没有平台消息 {arguments.message}")
    pictures = [segment for segment in message.segments if segment.type == "image"]
    if arguments.image > len(pictures):
        raise ValueError(f"消息 {arguments.message} 只有 {len(pictures)} 张图片，不能读取第 {arguments.image} 张")
    asset = store.image(scene, arguments.message, arguments.image)
    pixels_reused = asset is not None
    pixels_source = 'cache'
    if asset is None:
        if arguments.refresh:
            raise ValueError("该图片尚未保存像素；先用 refresh=false 读取，再重新描述")
        original = store.platform_image(scene, arguments.message, arguments.image)
        picture_data = pictures[arguments.image - 1].data
        deadline = asyncio.timeout(settings.timeout_seconds)
        try:
            async with deadline:
                if original is not None:
                    body = original[1]
                    fetched_at = store.now()
                    pixels_source = 'saved_platform_original'
                elif recording is not None:
                    body, fetched_at = recording.image(arguments.message, arguments.image)
                    pixels_source = 'frozen_original'
                elif fetch_media is not None and _needs_platform_fetch(
                    picture_data, message_time=message.time, now=store.now()
                ):
                    try:
                        body = await fetch_media(picture_data, settings.max_bytes)
                        pixels_source = 'platform_download'
                    except Exception:
                        if deadline.expired() or not _has_url(picture_data):
                            raise
                        _, _, body = await fetch_public(
                            image_url(picture_data), settings.timeout_seconds,
                            lambda _type, _prefix: settings.max_bytes,
                            fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
                        )
                        pixels_source = 'http_response'
                    fetched_at = store.now()
                else:
                    try:
                        _, _, body = await fetch_public(
                            image_url(picture_data), settings.timeout_seconds,
                            lambda _type, _prefix: settings.max_bytes,
                            fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
                        )
                        pixels_source = 'http_response'
                    except Exception:
                        if deadline.expired() or fetch_media is None or not _has_platform_id(picture_data):
                            raise
                        body = await fetch_media(picture_data, settings.max_bytes)
                        pixels_source = 'platform_download'
                    fetched_at = store.now()
                jpeg, animated, width, height, frames = await _prepare_pixels(
                    body, settings, max_frames=LOOK_MAX_FRAMES
                )
                asset = ImageAsset(jpeg=jpeg, width=width, height=height, animated=animated,
                                   fetched_at=fetched_at, frames=frames)
                store.save_image(scene, arguments.message, arguments.image, asset)
        except TimeoutError as error:
            if deadline.expired():
                raise TimeoutError(f"look image loading and preparation exceeded {settings.timeout_seconds} seconds") from error
            raise
    return asset, pixels_reused, pixels_source


async def execute_look(store: Store, scene: str, arguments: LookArguments,
                       settings: ImageSettings, *, model_name: str,
                       describe: Callable[[ImageAsset], Awaitable[str]],
                       recording: RecordedImages | None = None, fake_ip_networks: tuple, public_dns_url: str | None = None,
                       fetch_media: MediaFetch | None = None) -> str:
    asset, pixels_reused, pixels_source = await load_look_image(
        store, scene, arguments, settings, recording=recording, fake_ip_networks=fake_ip_networks,
        public_dns_url=public_dns_url, fetch_media=fetch_media)
    description_reused = asset.description is not None and not arguments.refresh
    if not description_reused:
        description = await describe(asset)
        described_at = store.now()
        store.save_image_description(scene, arguments.message, arguments.image,
                                     description, model_name, described_at)
        asset = store.image(scene, arguments.message, arguments.image)
    return _display(scene, arguments, asset, pixels_reused=pixels_reused,
                    description_reused=description_reused, pixels_source=pixels_source)


def shown_image(scene: str, arguments: LookArguments, asset: ImageAsset, *,
                pixels_reused: bool, pixels_source: str) -> str:
    """The look result when the mind model receives the pixels itself."""
    result = {
        "scene": scene, "platform_message_id": arguments.message, "image": arguments.image,
        "jpeg_bytes": len(asset.jpeg), "width": asset.width, "height": asset.height,
        **_animated_fields(asset),
        "fetched_at": datetime.fromtimestamp(asset.fetched_at, timezone.utc).isoformat(),
        "pixels_reused": pixels_reused, "pixels_source": pixels_source,
    }
    if asset.animated and asset.frames > 1:
        note = f"\n图片附在本轮接下来的请求里；动图已提取 {asset.frames} 个关键帧拼图。"
    elif asset.animated:
        note = "\n图片附在本轮接下来的请求里；动图只有第一帧。"
    else:
        note = "\n图片附在本轮接下来的请求里。"
    return json.dumps(result, ensure_ascii=False) + note


def _worker() -> None:
    from len_bot.media.images import prepare_image_frames

    max_bytes, max_pixels, max_dimension = map(int, sys.argv[2:5])
    max_frames = int(sys.argv[5]) if len(sys.argv) == 6 else 1
    jpeg, animated, width, height, frames = prepare_image_frames(
        sys.stdin.buffer.read(max_bytes + 1),
        max_bytes=max_bytes, max_pixels=max_pixels, max_dimension=max_dimension, max_frames=max_frames,
    )
    metadata = {"animated": animated, "width": width, "height": height, "frames": frames}
    sys.stdout.buffer.write(json.dumps(metadata).encode("ascii") + b"\n" + jpeg)


if __name__ == "__main__":
    if len(sys.argv) not in {5, 6} or sys.argv[1] != "prepare":
        raise SystemExit("look image worker expects prepare and three or four limits")
    try:
        _worker()
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
