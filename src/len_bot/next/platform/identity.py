"""Qualified account and scene identifiers at configuration boundaries."""

from urllib.parse import quote
import re
import sys


def validate_scene(value: str) -> str:
    if re.fullmatch(r'[a-z][a-z0-9_-]*:(group|private):[^:\s/\\]+', value) is None:
        raise ValueError(f'must be platform:group:id or platform:private:id; raw={value!r}')
    platform, kind, identifier = value.split(':', 2)
    if platform == 'onebot' and re.fullmatch(r'[1-9][0-9]*', identifier) is None:
        raise ValueError(f'OneBot scene must be platform:group:id or platform:private:id with a positive account number; raw={value!r}')
    return value


def scene_directory(scene: str) -> str:
    """Directory name for a scene's files; percent-encoded on Windows, where ``:`` cannot appear in a name."""
    return quote(scene, safe='') if sys.platform == 'win32' else scene
