"""OneBot audio retrieval and native WAV/URL response parsing."""

from __future__ import annotations

import asyncio
import base64
import binascii
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import wave

from ..models.asr import AudioSettings
from ..tools.http_read import fetch_public
from .platform_tools import PlatformCall


def _parse_wav(wav: bytes, settings: AudioSettings) -> tuple[bytes, float]:
    if len(wav) > settings.max_bytes:
        raise ValueError(f"record exceeds {settings.max_bytes} bytes")
    with wave.open(BytesIO(wav), "rb") as stream:
        frames, rate = stream.getnframes(), stream.getframerate()
        if frames <= 0 or rate <= 0:
            raise ValueError("WAV contains no audio frames or sample rate")
        duration = frames / rate
        if duration > settings.max_seconds:
            raise ValueError(f"record duration {duration:g}s exceeds {settings.max_seconds:g}s; not truncated")
        expected = frames * stream.getnchannels() * stream.getsampwidth()
        if expected > settings.max_bytes or len(stream.readframes(frames)) != expected:
            raise ValueError("WAV frames are truncated or exceed configured byte limit")
    return wav, duration


def _http_url(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("http://", "https://")):
            return stripped
    return None


def _local_path(value: str) -> Path | None:
    if value.startswith("file://"):
        return Path(unquote(urlsplit(value).path))
    if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
        return Path(value)
    return None


def _read_local_capped(path: Path, max_bytes: int) -> bytes:
    if path.stat().st_size > max_bytes:
        raise ValueError(f"record exceeds {max_bytes} bytes")
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"record exceeds {max_bytes} bytes")
    if not data:
        raise ValueError(f"record local file is empty: {path}")
    return data


def _source_duration(source: dict, settings: AudioSettings) -> float:
    raw = source.get("duration")
    seconds = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0 else 0.0
    if seconds > settings.max_seconds:
        raise ValueError(f"record duration {seconds:g}s exceeds {settings.max_seconds:g}s; not truncated")
    return seconds


async def _fetch_url_audio(url: str, source: dict, settings: AudioSettings, *,
                           fake_ip_networks: tuple, public_dns_url: str | None) -> tuple[bytes, float]:
    _, _, audio = await fetch_public(
        url, settings.timeout_seconds, lambda _type, _prefix: settings.max_bytes,
        fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
    )
    if not audio:
        raise ValueError("audio url returned empty body")
    if len(audio) > settings.max_bytes:
        raise ValueError(f"record exceeds {settings.max_bytes} bytes")
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return _parse_wav(audio, settings)
    return audio, _source_duration(source, settings)


def parse_record(raw: object, settings: AudioSettings) -> tuple[bytes, float]:
    """NapCat get_record(out_format=wav) returns converted bytes in data.base64."""
    try:
        if not isinstance(raw, dict) or raw.get("status") != "ok" or raw.get("retcode") != 0:
            raise ValueError("get_record did not return status=ok, retcode=0")
        encoded = raw["data"]["base64"]
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("get_record data.base64 must be nonempty text")
        if len(encoded) > 4 * ((settings.max_bytes + 2) // 3):
            raise ValueError(f"record exceeds {settings.max_bytes} bytes")
        wav = base64.b64decode(encoded, validate=True)
        return _parse_wav(wav, settings)
    except (KeyError, TypeError, ValueError, binascii.Error, wave.Error, EOFError) as error:
        # Do not echo megabytes of binary audio as a protocol error.
        fragment = repr(raw)[:500]
        raise ValueError(f"get_record audio parse failed: {error}; raw={fragment}") from error


async def fetch_record(call: PlatformCall, source: dict, settings: AudioSettings, *,
                       fake_ip_networks: tuple = (), public_dns_url: str | None = None) -> tuple[bytes, float]:
    file = source.get("file")
    has_file = isinstance(file, str) and bool(file.strip())
    segment_url = _http_url(source.get("url"))
    if not has_file:
        if segment_url is not None:
            async with asyncio.timeout(settings.timeout_seconds):
                return await _fetch_url_audio(
                    segment_url, source, settings,
                    fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
                )
        raise ValueError(f"Audio segment lacks its actual file locator: {source!r}")

    local = _local_path(file.strip())
    if local is not None and not local.is_file() and segment_url is not None:
        async with asyncio.timeout(settings.timeout_seconds):
            return await _fetch_url_audio(
                segment_url, source, settings,
                fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
            )

    async with asyncio.timeout(settings.timeout_seconds):
        raw = await call("get_record", {"file": file, "out_format": "wav"})
        if isinstance(raw, dict) and raw.get("status") == "ok" and raw.get("retcode") == 0:
            data = raw.get("data")
            if isinstance(data, dict) and not (isinstance(data.get("base64"), str) and data["base64"]):
                returned_file = data.get("file")
                if isinstance(returned_file, str) and returned_file.strip():
                    returned_local = _local_path(returned_file.strip()) or Path(returned_file.strip())
                    if returned_local.is_file():
                        wav = await asyncio.to_thread(_read_local_capped, returned_local, settings.max_bytes)
                        return _parse_wav(wav, settings)
                remote_url = _http_url(data.get("url")) or _http_url(returned_file) or segment_url
                if remote_url is not None:
                    return await _fetch_url_audio(
                        remote_url, source, settings,
                        fake_ip_networks=fake_ip_networks, public_dns_url=public_dns_url,
                    )
        return parse_record(raw, settings)
