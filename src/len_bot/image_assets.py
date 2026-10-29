"""Verified original images and the resized copies sent as stickers."""
from dataclasses import dataclass, field
from io import BytesIO
from PIL import Image, ImageSequence

MAX_IMAGE_BYTES = 10_000_000
MAX_IMAGE_PIXELS = 25_000_000
MIME_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
STICKER_MAX_DIMENSION = 320


def sticker_bytes(data: bytes) -> bytes:
    """Fit a sent sticker copy to one canvas limit, preserving animation and originals."""
    with Image.open(BytesIO(data)) as image:
        if max(image.size) <= STICKER_MAX_DIMENSION:
            return data
        preview = image.copy()
        preview.thumbnail((STICKER_MAX_DIMENSION, STICKER_MAX_DIMENSION), Image.Resampling.LANCZOS)
        size, format = preview.size, image.format
        frames, durations = [], []
        for frame in ImageSequence.Iterator(image):
            mode = 'RGB' if format == 'JPEG' else 'RGBA'
            frames.append(frame.convert(mode).resize(size, Image.Resampling.LANCZOS))
            durations.append(frame.info.get('duration', 0))
        options = {}
        if len(frames) > 1:
            options.update(save_all=True, append_images=frames[1:], duration=durations)
            if 'loop' in image.info:
                options['loop'] = image.info['loop']
            if format == 'GIF':
                options['disposal'] = 2
        output = BytesIO()
        frames[0].save(output, format=format, **options)
        return output.getvalue()

@dataclass(frozen=True, slots=True)
class OriginalImage:
    data: bytes = field(repr=False)
    mime_type: str
    width: int
    height: int
    animated: bool


def inspect_image(data: bytes) -> tuple[str, int, int, bool]:
    """Validate the actual original without decoding every animated frame."""
    try:
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError(f"image asset must contain 1..{MAX_IMAGE_BYTES} bytes")
        with Image.open(BytesIO(data)) as image:
            if image.format not in MIME_TYPES:
                raise ValueError(f"unsupported image format: {image.format!r}")
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(f"image canvas exceeds {MAX_IMAGE_PIXELS} pixels")
            mime_type = MIME_TYPES[image.format]
            animated = getattr(image, "n_frames", 1) > 1
            image.verify()
        return mime_type, width, height, animated
    except (OSError, ValueError, EOFError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError(f"invalid image asset: {error}; original prefix={data[:32]!r}") from error


SHEET_CELL = 200


def sticker_sheet(images: list[bytes], *, columns: int = 3) -> bytes:
    """One JPEG with each sticker's first frame on white, numbered from 1 in reading order."""
    from PIL import ImageDraw, ImageFont

    rows = -(-len(images) // columns)
    sheet = Image.new('RGB', (columns * SHEET_CELL, rows * SHEET_CELL), 'white')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(28)
    for index, data in enumerate(images):
        left, top = index % columns * SHEET_CELL, index // columns * SHEET_CELL
        with Image.open(BytesIO(data)) as image:
            frame = image.convert('RGBA')
        frame.thumbnail((SHEET_CELL - 24, SHEET_CELL - 24), Image.Resampling.LANCZOS)
        sheet.paste(frame, (left + (SHEET_CELL - frame.width) // 2, top + (SHEET_CELL - frame.height) // 2), frame)
        draw.rectangle((left, top, left + SHEET_CELL - 1, top + SHEET_CELL - 1), outline='#c8c8c8')
        label = str(index + 1)
        box = draw.textbbox((0, 0), label, font=font)
        draw.rectangle((left, top, left + box[2] + 12, top + box[3] + 8), fill='black')
        draw.text((left + 6, top + 2), label, fill='white', font=font)
    output = BytesIO()
    sheet.save(output, format='JPEG', quality=85)
    return output.getvalue()
