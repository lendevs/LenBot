"""Repeat what the persona material itself says not to do, next to the turn's generation.

Only sentences the persona wrote are repeated, word for word; the framework adds none of its own.
The persona text sits at the start of a long system message, and its prohibitions are the part a
model loses first, so they are read once more at the end of each turn's reference material.
"""

from __future__ import annotations

import re
from string import Template

from ..persona.profile import Persona
from ..prompt_files import read_prompt

SENTENCE = re.compile(r"[^。！!？?；;\n]+[。！!？?；;]*")
CLAUSE = re.compile(r"[，,、：:（）()\s]+")
# A prohibition written anywhere in a sentence.
FORBIDDING = re.compile(r"不要|不准|不许|禁止|避免|切勿")
# A clause opening with a negated verb, such as 不接、不评价、别提: after its subject, if any.
OPENING_NEGATION = re.compile(r"^(?:别(?!的|人|处)|不(?!是|知道|必|用|一定|过|少|同|管|如|然|太|会吧|算))")
SUBJECTS = ("她", "他", "你", "我", "它")


def _opens_with_negation(clause: str, subjects: tuple[str, ...]) -> bool:
    for subject in sorted(subjects, key=len, reverse=True):
        if subject and clause.startswith(subject):
            clause = clause[len(subject):]
            break
    clause = re.sub(r"^(?:也|都|就|从来|从|绝对|一律|永远)", "", clause)
    return OPENING_NEGATION.match(clause) is not None


def avoidances(persona: Persona) -> list[str]:
    """The persona's own sentences that say not to do something, in the order written."""
    subjects = (*SUBJECTS, persona.name, *persona.self_reference, *persona.aliases)
    found: list[str] = []
    for material in (persona.behavior, persona.voice, persona.boundaries):
        for line in material.splitlines():
            line = re.sub(r"^\s*(?:[-*+]|\d+[.、)])\s*", "", line)
            for match in SENTENCE.finditer(line):
                sentence = match.group(0).strip()
                if not sentence or sentence.startswith("#") or sentence in found:
                    continue
                clauses = [clause for clause in CLAUSE.split(sentence) if clause]
                if FORBIDDING.search(sentence) or any(_opens_with_negation(clause, subjects) for clause in clauses):
                    found.append(sentence)
    return found


def avoidance_text(persona: Persona) -> str | None:
    found = avoidances(persona)
    if not found:
        return None
    return Template(read_prompt("next_persona_avoid.md")).substitute(
        items="\n".join(f"- {sentence}" for sentence in found))
