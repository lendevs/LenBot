"""Image validation and pixel preparation for model input."""

import base64
import io
import math

from PIL import Image, ImageDraw, ImageFont, ImageOps


FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
LONG_ASPECT_RATIO = 3.0
MAX_LONG_DIMENSION = 3200
SHEET_BORDER = 4
SHEET_BACKGROUND = (220, 220, 220)


def validate_image(data: bytes, *, max_bytes: int, max_pixels: int):
    if not data or len(data) > max_bytes:
        raise ValueError(f"图片为空或超过 {max_bytes} 字节上限")
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in FORMATS:
            raise ValueError("仅支持PNG、JPEG、WEBP和GIF")
        if image.width * image.height > max_pixels:
            raise ValueError("图片像素超过上限")
        mime_type = FORMATS[image.format]
        image.verify()
    return mime_type


def _target_size(width: int, height: int, *, max_dimension: int, max_pixels: int) -> tuple[int, int]:
    long_side = max(width, height)
    short_side = max(1, min(width, height))
    if long_side / short_side >= LONG_ASPECT_RATIO:
        limit = max(max_dimension, min(max_dimension * 2, MAX_LONG_DIMENSION))
    else:
        limit = max_dimension
    scale = min(1.0, limit / long_side)
    scaled_w = max(1, round(width * scale))
    scaled_h = max(1, round(height * scale))
    if scaled_w * scaled_h > max_pixels:
        pixel_scale = math.sqrt(max_pixels / (scaled_w * scaled_h))
        scaled_w = max(1, int(scaled_w * pixel_scale))
        scaled_h = max(1, int(scaled_h * pixel_scale))
    return scaled_w, scaled_h


def _sample_frame_indices(n_frames: int, max_frames: int) -> list[int]:
    count = min(n_frames, max_frames)
    if count <= 1:
        return [0]
    return list(dict.fromkeys(round(i * (n_frames - 1) / (count - 1)) for i in range(count)))


def _flatten_frame(image: Image.Image) -> Image.Image:
    rgba = ImageOps.exif_transpose(image).convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _grid_shape(count: int, frame_w: int, frame_h: int) -> tuple[int, int]:
    if count == 2:
        return (1, 2) if frame_w > frame_h * 2 else (2, 1)
    if count == 3:
        return (1, 3) if frame_w > frame_h * 2 else (3, 1)
    if count == 4:
        return (2, 2)
    if count <= 6:
        return (3, 2)
    cols = math.ceil(math.sqrt(count))
    return cols, math.ceil(count / cols)


def _compose_contact_sheet(frames: list[Image.Image], *, max_dimension: int, max_pixels: int) -> Image.Image:
    count = len(frames)
    frame_w, frame_h = frames[0].size
    cols, rows = _grid_shape(count, frame_w, frame_h)
    border = SHEET_BORDER
    avail_w = max(1, (max_dimension - border * (cols + 1)) // cols)
    avail_h = max(1, (max_dimension - border * (rows + 1)) // rows)
    scale = min(1.0, avail_w / frame_w, avail_h / frame_h)
    tile_w = max(1, round(frame_w * scale))
    tile_h = max(1, round(frame_h * scale))
    sheet_w = cols * tile_w + (cols + 1) * border
    sheet_h = rows * tile_h + (rows + 1) * border
    if sheet_w * sheet_h > max_pixels:
        pixel_scale = math.sqrt(max_pixels / (sheet_w * sheet_h))
        tile_w = max(1, int(tile_w * pixel_scale))
        tile_h = max(1, int(tile_h * pixel_scale))
        sheet_w = cols * tile_w + (cols + 1) * border
        sheet_h = rows * tile_h + (rows + 1) * border

    sheet = Image.new("RGB", (sheet_w, sheet_h), SHEET_BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, frame in enumerate(frames):
        tile = frame if frame.size == (tile_w, tile_h) else frame.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        row, col = divmod(index, cols)
        x = border + col * (tile_w + border)
        y = border + row * (tile_h + border)
        sheet.paste(tile, (x, y))
        if tile_w >= 24 and tile_h >= 24:
            label = str(index + 1)
            left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
            text_w, text_h = right - left, bottom - top
            box = (x + 2, y + 2, x + 2 + text_w + 6, y + 2 + text_h + 4)
            draw.rectangle(box, fill=(24, 24, 24))
            draw.text((x + 5 - left, y + 4 - top), label, fill=(255, 255, 255), font=font)
    return sheet


def prepare_image_frames(data: bytes, *, max_bytes: int, max_pixels: int, max_dimension: int,
                         max_frames: int = 1) -> tuple[bytes, bool, int, int, int]:
    if max_frames < 1:
        raise ValueError("max_frames must be at least 1")
    validate_image(data, max_bytes=max_bytes, max_pixels=max_pixels)
    with Image.open(io.BytesIO(data)) as image:
        n_frames = getattr(image, "n_frames", 1)
        animated = n_frames > 1
        if animated and max_frames > 1:
            kept: list[Image.Image] = []
            previous_bytes: bytes | None = None
            previous_size: tuple[int, int] | None = None
            for index in _sample_frame_indices(n_frames, max_frames):
                image.seek(index)
                frame = _flatten_frame(image)
                raw = frame.tobytes()
                if previous_bytes is not None and frame.size == previous_size and raw == previous_bytes:
                    continue
                kept.append(frame)
                previous_bytes = raw
                previous_size = frame.size
            if len(kept) > 1:
                result_image = _compose_contact_sheet(kept, max_dimension=max_dimension, max_pixels=max_pixels)
                used_frames = len(kept)
            else:
                single = kept[0]
                target = _target_size(single.width, single.height, max_dimension=max_dimension, max_pixels=max_pixels)
                result_image = (single if single.size == target
                                else single.resize(target, Image.Resampling.LANCZOS))
                used_frames = 1
        else:
            image.seek(0)
            single = _flatten_frame(image)
            target = _target_size(single.width, single.height, max_dimension=max_dimension, max_pixels=max_pixels)
            result_image = (single if single.size == target
                            else single.resize(target, Image.Resampling.LANCZOS))
            used_frames = 1
        output = io.BytesIO()
        # The frame is already composited onto white and flattened to RGB, so a
        # lossless encoding preserves nothing an alpha channel would have kept.
        # It only inflates the request body: measured on real group images, six
        # pictures reach 13.6 MB at p90 and 37 MB at worst as PNG, which is what
        # the relay drops mid-upload.
        result_image.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue(), animated, result_image.width, result_image.height, used_frames


def prepare_image(data: bytes, *, max_bytes: int, max_pixels: int, max_dimension: int, max_frames: int = 1):
    jpeg, animated, width, height, _ = prepare_image_frames(
        data, max_bytes=max_bytes, max_pixels=max_pixels, max_dimension=max_dimension, max_frames=max_frames,
    )
    return jpeg, animated, width, height


def image_block(data: bytes):
    return {"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64," + base64.b64encode(data).decode(), "detail": "high"}}
