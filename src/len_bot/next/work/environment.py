"""The environment text a task's first request carries: facts plus one segment per capability it really has."""

from __future__ import annotations

import json
import re
from string import Template

from ..prompt_files import read_prompt

# Order and display names of the Python libraries a task environment can preinstall.
_LIBRARIES = (("pandas", "pandas"), ("openpyxl", "openpyxl"), ("matplotlib", "matplotlib"),
              ("python-docx", "python-docx"), ("pypdf", "pypdf"), ("pillow", "Pillow"))
_COMMANDS = (("ffmpeg", "ffmpeg"), ("ffprobe", "ffprobe"), ("pandoc", "pandoc"),
             ("pdftotext", "poppler（pdftotext、pdftoppm 等）"))


def environment_prompt(facts: dict, programs: frozenset[str]) -> str:
    """``facts`` is the JSON object shown to the task; ``programs`` the environment's inventory."""
    tools = []
    if "lenbot-render" in programs:
        tools.append(read_prompt("next_worker_render.md"))
    libraries = [label for name, label in _LIBRARIES if f"python:{name}" in programs]
    if libraries:
        tools.append(Template(read_prompt("next_worker_libraries.md")).substitute(libraries="、".join(libraries)))
    if "font:zh" in programs:
        tools.append(read_prompt("next_worker_font.md"))
    commands = [label for name, label in _COMMANDS if name in programs]
    if commands:
        tools.append(Template(read_prompt("next_worker_commands.md")).substitute(commands="、".join(commands)))
    browser = read_prompt("next_worker_browser.md") if facts["public_browser"] is not None else ""
    text = Template(read_prompt("next_worker_environment.md")).substitute(
        facts=json.dumps(facts, ensure_ascii=False, allow_nan=False),
        tools="\n\n".join(item.strip() for item in tools), browser=browser.strip())
    return re.sub(r"\n{3,}", "\n\n", text)
