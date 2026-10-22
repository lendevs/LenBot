"""Expression selection and duplicate checks by shared character pairs, for scenes without embeddings."""

from __future__ import annotations

import re

# Han runs become overlapping pairs; Latin letters and digits stay whole words.
_HAN = re.compile(r"[㐀-鿿豈-﫿]+")
_WORD = re.compile(r"[A-Za-z0-9]+")


def grams(text: str) -> set[str]:
    found = {word.lower() for word in _WORD.findall(text)}
    for run in _HAN.findall(text):
        if len(run) == 1:
            found.add(run)
        else:
            found.update(run[index:index + 2] for index in range(len(run) - 1))
    return found


def coverage(part: str, whole: str) -> float:
    """Share of ``part``'s grams that also occur in ``whole``."""
    needle = grams(part)
    return len(needle & grams(whole)) / len(needle) if needle else 0.0


def overlap(first: str, second: str) -> float:
    """Shared grams over the union of both texts."""
    left, right = grams(first), grams(second)
    return len(left & right) / len(left | right) if left | right else 0.0


def select_by_words(adopted: list[dict], query: str, limit: int = 5, minimum: float = 0.25) -> list[dict]:
    """Rank adopted expressions by how much of their situation the recent chat mentions."""
    text = grams(query)
    ranked = []
    for item in adopted:
        needle = grams(item["situation"])
        if not needle:
            continue
        score = len(needle & text) / len(needle)
        if score >= minimum:
            ranked.append({"id": item["id"], "situation": item["situation"], "style": item["style"],
                           "similarity": score})
    ranked.sort(key=lambda item: (-item["similarity"], item["id"]))
    return ranked[:limit]
