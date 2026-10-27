"""Markdown retrieval units; offsets always refer to the unchanged source text."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3


_ATX = re.compile(r'^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$')
_SETEXT = re.compile(r'^ {0,3}(=+|-+)[ \t]*$')
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')

SECTION_STATEMENTS = (
    '''CREATE TABLE memory_sections (
        id INTEGER PRIMARY KEY,
        scope TEXT NOT NULL,
        path TEXT NOT NULL,
        heading TEXT NOT NULL,
        start_char INTEGER NOT NULL,
        end_char INTEGER NOT NULL,
        source_version TEXT NOT NULL,
        content TEXT NOT NULL,
        UNIQUE(scope, path, start_char)
    )''',
    '''CREATE VIRTUAL TABLE memory_fts USING fts5(
        content, content='memory_sections', content_rowid='id',
        tokenize='trigram case_sensitive 1'
    )''',
    "INSERT INTO memory_fts(memory_fts, rank) VALUES('secure-delete', 1)",
)


@dataclass(frozen=True, slots=True)
class Section:
    heading: tuple[str, ...]
    start_char: int
    end_char: int

    def text(self, content: str) -> str:
        return content[self.start_char:self.end_char]

    def embedding_text(self, content: str) -> str:
        return '\n'.join((*self.heading[:-1], self.text(content)))


def split_sections(content: str) -> list[Section]:
    """ATX/Setext sections with heading ancestry; fenced code is never a boundary.

    A document without headings remains one complete event. Heading-only parents
    become ancestry, rather than standalone retrieval results.
    """
    lines = content.splitlines(keepends=True)
    headings: list[tuple[int, int, int, str]] = []
    offset = 0
    fence: tuple[str, int] | None = None
    previous: tuple[int, str] | None = None
    for line in lines:
        text = line.rstrip('\r\n')
        marker = _FENCE.fullmatch(text)
        if fence is not None:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            previous = None
        elif marker:
            fence = marker[1][0], len(marker[1])
            previous = None
        elif match := _ATX.fullmatch(text):
            title = re.sub(r'[ \t]+#+[ \t]*$', '', match[2] or '').strip()
            headings.append((offset, offset + len(line), len(match[1]), title))
            previous = None
        elif (match := _SETEXT.fullmatch(text)) and previous is not None:
            headings.append((previous[0], offset + len(line), 1 if match[1][0] == '=' else 2,
                             previous[1].strip()))
            previous = None
        else:
            previous = (offset, text) if text.strip() and not text.startswith(('    ', '\t')) else None
        offset += len(line)

    sections = []
    stack: list[tuple[int, str]] = []
    start, body, ancestry = 0, 0, ()
    for position, after_heading, level, title in headings:
        if content[body:position].strip():
            sections.append(Section(ancestry, start, position))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        start, body, ancestry = position, after_heading, tuple(title for _, title in stack)
    if content[body:].strip():
        sections.append(Section(ancestry, start, len(content)))
    return sections


def put_sections(db: sqlite3.Connection, scope: str, path: str, content: str) -> list[int]:
    version = hashlib.sha256(content.encode('utf-8')).hexdigest()
    ids = []
    for section in split_sections(content):
        folded = section.embedding_text(content).casefold()
        rowid = db.execute(
            'INSERT INTO memory_sections(scope,path,heading,start_char,end_char,source_version,content) '
            'VALUES(?,?,?,?,?,?,?)',
            (scope, path, json.dumps(section.heading, ensure_ascii=False), section.start_char,
             section.end_char, version, folded)).lastrowid
        db.execute('INSERT INTO memory_fts(rowid,content) VALUES(?,?)', (rowid, folded))
        ids.append(rowid)
    return ids


_SENTENCE = re.compile(r'[^。！？!?；;\n]*(?:[。！？!?；;]+\n?|\n|$)')
GAP = '\n…\n'


def query_terms(query: str) -> tuple[list[str], list[str]]:
    """The distinct three-character fragments within each line of ``query``, and its one- or two-character
    lines, case-folded. A fragment never spans a line break or starts or ends with a space, so two
    messages joined into one query do not match a heading followed by a line."""
    terms: dict[str, None] = {}
    short: dict[str, None] = {}
    for line in query.casefold().splitlines():
        line = line.strip()
        if 0 < len(line) < 3:
            short[line] = None
        for index in range(len(line) - 2):
            term = line[index:index + 3]
            if term.strip() == term:
                terms[term] = None
    return list(terms), list(short)


def evidence(text: str, query: str) -> int:
    """How many of the query's fragments and short lines ``text`` contains."""
    folded = text.casefold()
    return sum(part in folded for part in (part for parts in query_terms(query) for part in parts))


def excerpt(text: str, query: str, limit: int) -> str:
    """The part of ``text`` that best answers ``query`` within ``limit`` characters.

    Leading heading lines stay in front. The body is cut at sentence ends and the window holding the most
    distinct query trigrams wins; among equal windows the one ending later wins, since a correction is
    written after what it corrects, then the one starting earlier, for more context. A section found by
    meaning alone shares no trigram, so its latest part is shown.
    """
    if len(text) <= limit:
        return text
    lines = text.splitlines(keepends=True)
    head = ''
    for line in lines:
        if line.strip() and not line.lstrip().startswith('#'):
            break
        if len(head) + len(line) > limit // 4:
            break
        head += line
    body = text[len(head):]
    room = limit - len(head) - 2 * len(GAP)
    terms = {term for term in query_terms(query)[0] if term in body.casefold()}
    if room <= 0:
        return text[:limit]
    units: list[str] = []
    for sentence in _SENTENCE.findall(body):
        units.extend(sentence[offset:offset + room] for offset in range(0, len(sentence), room))
    units = [unit for unit in units if unit]
    best: tuple[int, int, int] = (-1, 0, 0)
    end, length = 0, 0
    for start in range(len(units)):
        if end < start:
            end, length = start, 0
        while end < len(units) and length + len(units[end]) <= room:
            length += len(units[end])
            end += 1
        window = ''.join(units[start:end]).casefold()
        best = max(best, (sum(term in window for term in terms), end, -start))
        length -= len(units[start])
    _, end, start = best
    start = -start
    prefix = (head.rstrip('\n') + (GAP if start else '\n')) if head else (GAP.lstrip('\n') if start else '')
    suffix = GAP.rstrip('\n') if end < len(units) else ''
    return prefix + ''.join(units[start:end]).strip('\n') + suffix
