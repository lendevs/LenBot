"""Image validation and pixel preparation for model input."""

import base64
import io
import math

from PIL import Image, ImageOps


FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}

# An animated image reaches the model as a single picture. Sampling several frames into
# a grid keeps the motion: the first frame alone is often a blurred transitional one.
GRID_MAX_FRAMES = 6
GRID_CELL_MAX = 640
GRID_GAP = 6


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


def _frame_indices(count: int, limit: int) -> list[int]:
    """Evenly spaced frame positions, always including the first and the last one."""
    if count <= limit:
        return list(range(count))
    step = (count - 1) / (limit - 1)
    return sorted({round(index * step) for index in range(limit)})


def _flatten(image, max_dimension: int):
    frame = ImageOps.exif_transpose(image).convert("RGBA")
    frame.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    background = Image.new("RGBA", frame.size, "white")
    background.alpha_composite(frame)
    return background.convert("RGB")


def _contact_sheet(image, indices: list[int], *, max_dimension: int, max_pixels: int):
    """Frames left to right, top to bottom, on one white sheet."""
    frames = []
    for index in indices:
        image.seek(index)
        frames.append(_flatten(image, GRID_CELL_MAX))
    columns = 2 if len(frames) <= 2 else (3 if len(frames) <= 9 else 4)
    rows = math.ceil(len(frames) / columns)
    cell_width = max(frame.width for frame in frames)
    cell_height = max(frame.height for frame in frames)
    sheet = Image.new("RGB", (columns * cell_width + GRID_GAP * (columns - 1),
                              rows * cell_height + GRID_GAP * (rows - 1)), "white")
    for position, frame in enumerate(frames):
        column, row = position % columns, position // columns
        left = column * (cell_width + GRID_GAP) + (cell_width - frame.width) // 2
        top = row * (cell_height + GRID_GAP) + (cell_height - frame.height) // 2
        sheet.paste(frame, (left, top))
    width, height = sheet.size
    scale = min(1.0, max_dimension / max(width, height), math.sqrt(max_pixels / (width * height)))
    if scale < 1:
        sheet = sheet.resize((max(1, round(width * scale)), max(1, round(height * scale))),
                             Image.Resampling.LANCZOS)
    return sheet


def prepare_image(data: bytes, *, max_bytes: int, max_pixels: int, max_dimension: int,
                  frames: int = GRID_MAX_FRAMES):
    """``frames`` is how many frames an animated image may contribute; 1 keeps the first only."""
    validate_image(data, max_bytes=max_bytes, max_pixels=max_pixels)
    with Image.open(io.BytesIO(data)) as image:
        frame_count = getattr(image, "n_frames", 1)
        animated = frame_count > 1
        if animated and frames > 1:
            sheet = _contact_sheet(image, _frame_indices(frame_count, min(frames, GRID_MAX_FRAMES)),
                                   max_dimension=max_dimension, max_pixels=max_pixels)
        else:
            image.seek(0)
            sheet = _flatten(image, max_dimension)
        output = io.BytesIO()
        # The frame is already composited onto white and flattened to RGB, so a
        # lossless encoding preserves nothing an alpha channel would have kept.
        # It only inflates the request body: measured on real group images, six
        # pictures reach 13.6 MB at p90 and 37 MB at worst as PNG, which is what
        # the relay drops mid-upload.
        sheet.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue(), animated, sheet.width, sheet.height


def image_block(data: bytes):
    return {"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64," + base64.b64encode(data).decode(), "detail": "high"}}
