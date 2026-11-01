"""Qualified account and scene identifiers at configuration boundaries."""

from urllib.parse import quote
import re
import sys


# Member accounts of each platform with an adapter; a private scene is named by the contact's account.
ACCOUNTS = {'onebot': r'[1-9][0-9]*', 'telegram': r'[1-9][0-9]*', 'feishu': r'ou_[A-Za-z0-9]+'}
GROUPS = {'onebot': r'[1-9][0-9]*', 'telegram': r'-[1-9][0-9]*', 'feishu': r'oc_[A-Za-z0-9]+'}
ACCOUNT_EXAMPLES = {'onebot': '70001', 'telegram': '70001', 'feishu': 'ou_7d8a6e'}
# Platforms whose groups can mention every member at once; Telegram has no such mention.
MENTION_ALL = frozenset({'onebot', 'feishu'})


def account_pattern(platform: str) -> str:
    """A regular expression for one member account of ``platform``, numeric for platforms without an adapter."""
    return f"{re.escape(platform)}:{ACCOUNTS.get(platform, r'[1-9][0-9]*')}"


def validate_scene(value: str) -> str:
    if re.fullmatch(r'[a-z][a-z0-9_-]*:(group|private):[^:\s/\\]+', value) is None:
        raise ValueError(f'must be platform:group:id or platform:private:id; raw={value!r}')
    platform, kind, identifier = value.split(':', 2)
    if platform == 'onebot' and re.fullmatch(r'[1-9][0-9]*', identifier) is None:
        raise ValueError(f'OneBot scene must be platform:group:id or platform:private:id with a positive account number; raw={value!r}')
    pattern = (GROUPS if kind == 'group' else ACCOUNTS).get(platform)
    if pattern is not None and re.fullmatch(pattern, identifier) is None:
        raise ValueError(f'{platform} {kind} scene must match {pattern}; raw={value!r}')
    return value


def scene_directory(scene: str) -> str:
    """Directory name for a scene's files; percent-encoded on Windows, where ``:`` cannot appear in a name."""
    return quote(scene, safe='') if sys.platform == 'win32' else scene
