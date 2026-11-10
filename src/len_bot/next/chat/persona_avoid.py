"""Repeat the persona material's own negated sentences next to the turn's generation.

Only sentences the persona wrote are repeated, word for word; the framework adds none of its own.
The persona text sits at the start of a long system message, and the things it says not to do are
the part a model loses first, so they are read once more at the end of each turn's reference
material. Picking them out is a heuristic, so the section presents them as original sentences to
follow as written, not as a list of prohibitions.
"""

from __future__ import annotations

import re
from string import Template

from ..persona.profile import Persona
from ..prompt_files import read_prompt

# Quoted text is the persona's sample speech; it is left out when judging a sentence.
QUOTED_SPAN = r"「[^」\n]*」|『[^』\n]*』|“[^”\n]*”|\"[^\"\n]*\"|‘[^’\n]*’"
QUOTED = re.compile(QUOTED_SPAN)
# A quoted span ending in 。！？ stays inside its sentence.
SENTENCE = re.compile(rf"(?:{QUOTED_SPAN}|[^。！!？?；;\n])+[。！!？?；;]*")
CLAUSE = re.compile(r"[，,、：:（）()\s]+")
# A prohibition written anywhere in a sentence.
FORBIDDING = re.compile(r"不要|不准|不许|禁止|避免|切勿")
SUBJECTS = ("她", "他", "你", "我", "它")
ADVERBS = re.compile(r"^(?:也|都|就|从来|从|绝对|一律|永远)")
# Words that start with 不 or 别 without negating an action.
WORDS = (
    "不是", "不开心", "不高兴", "不好意思", "不仅", "不但", "不只", "不光", "不小心", "不久", "不错",
    "不得不", "不愧", "不少", "不论", "不管", "不如", "不然", "不过", "不同", "不必", "不一定",
    "不知道", "不知不觉", "不一会", "不太", "不算", "不会的", "不禁", "不由得", "不妨", "不停", "不断", "不止",
    "别扭", "别致", "别的", "别人", "别处",
)
# A 不 clause that goes on like this is the condition of the sentence, as in 不同意就直说 or
# 不开心的时候会撒娇; a time phrase before the negated action itself, as in 不在人难过时开玩笑, is not.
# A 别 clause is an imperative and is never a condition.
CONDITION = re.compile(r"(?:的时候|时|的话)(?:$|会|就|也|都|要|总|还|才|先|再|可以)|就|起来")
# Words containing 时 or 就 that do not mark a condition; removed before looking for one.
NOT_CONDITION = re.compile(
    r"时间|时刻|时常|时事|时政|时期|时代|时机|时光|时髦|时尚|时不时|按时|及时|准时|同时|平时|随时|当时|临时|暂时|小时"
    r"|成就|就业|就算|将就|迁就|造就")


def _negates_an_action(clause: str, subjects: tuple[str, ...]) -> bool:
    for subject in sorted(subjects, key=len, reverse=True):
        if subject and clause.startswith(subject):
            clause = clause[len(subject):]
            break
    clause = ADVERBS.sub("", clause)
    if not clause.startswith(("不", "别")) or clause.startswith(WORDS):
        return False
    return clause.startswith("别") or CONDITION.search(NOT_CONDITION.sub("", clause), 1) is None


def _counts(sentence: str, subjects: tuple[str, ...]) -> bool:
    unquoted = QUOTED.sub("，", sentence)
    if FORBIDDING.search(unquoted):
        return True
    return any(_negates_an_action(clause, subjects) for clause in CLAUSE.split(unquoted) if clause)


def avoidances(persona: Persona) -> list[str]:
    """The persona's own sentences with a negated action or a prohibition, in the order written."""
    subjects = (*SUBJECTS, persona.name, *persona.self_reference, *persona.aliases)
    found: list[str] = []
    for material in (persona.behavior, persona.voice, persona.boundaries):
        for line in material.splitlines():
            line = re.sub(r"^\s*(?:[-*+]|\d+[.、)])\s*", "", line)
            for match in SENTENCE.finditer(line):
                sentence = match.group(0).strip()
                if not sentence or sentence.startswith("#") or sentence in found:
                    continue
                if _counts(sentence, subjects):
                    found.append(sentence)
    return found


def avoidance_text(persona: Persona) -> str | None:
    found = avoidances(persona)
    if not found:
        return None
    return Template(read_prompt("next_persona_avoid.md")).substitute(
        items="\n".join(f"- {sentence}" for sentence in found))
