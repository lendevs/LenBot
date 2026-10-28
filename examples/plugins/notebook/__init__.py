"""Example memory plugin: notes taken from the chat, recalled by shared wording, kept with the memory tool.

Choose it for a group under Groups → Settings → Plugins → Long-term memory. Notes live in one SQLite file
in this plugin's data directory; the native memory files stay as they are.

A group is served from its first recall request on: upkeep starts at that moment, so messages from
before are not taken into notes. Each pass reports the last message it read, and retention keeps the
originals the plugin has not read yet.
"""

import asyncio
import json
import re
import sqlite3
from typing import Literal

from len_bot.plugin import (ChatMessage, Invocation, Plugin, PluginContext, RecallBlock, RecallRequest, background,
                            memory_tool, recall)

SCHEMA = '''CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY, scene TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL
)'''
EXTRACT = '''下面是一段群聊记录。列出以后聊天时值得记住的事实：约定、偏好、更正、身份和承诺，每条一句话，写清是谁。
已经被更正的旧说法不要列。只输出 JSON 字符串数组；没有值得记住的就输出 []。

{messages}'''
PAGE = 200


def text_of(message: ChatMessage) -> str:
    return ''.join(segment.data['text'] for segment in message.segments if segment.type == 'text').strip()


def trigrams(text: str) -> set[str]:
    folded = re.sub(r'\s+', '', text.casefold())
    return {folded[index:index + 3] for index in range(len(folded) - 2)}


def facts(reply: str) -> list[str]:
    """The JSON array in a model reply, tolerating a code fence around it."""
    match = re.search(r'\[.*\]', reply, re.S)
    if match is None:
        raise ValueError(f'整理结果不是 JSON 数组：{reply[:200]!r}')
    values = json.loads(match[0])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f'整理结果必须是字符串数组：{reply[:200]!r}')
    return [value.strip() for value in values if value.strip()]


class Notebook(Plugin):
    def __init__(self, ctx: PluginContext):
        super().__init__(ctx)
        self.db = sqlite3.connect(ctx.data_dir / 'notes.sqlite3', check_same_thread=False)
        self.db.execute(SCHEMA)
        self.db.commit()
        # Groups that asked this plugin to recall since it started: the ones it is the memory of.
        self.serving: set[str] = set()
        self.lock = asyncio.Lock()

    async def stop(self) -> None:
        self.db.close()

    def notes(self, scene: str) -> list[tuple[int, str]]:
        return self.db.execute('SELECT id,text FROM notes WHERE scene=? ORDER BY id', (scene,)).fetchall()

    def add(self, scene: str, text: str) -> int:
        with self.db:
            return self.db.execute('INSERT INTO notes(scene,text,created) VALUES (?,?,?)',
                                   (scene, text, self.ctx.now())).lastrowid

    @recall()
    async def remember(self, request: RecallRequest) -> list[RecallBlock]:
        if request.scene not in self.serving:
            self.serving.add(request.scene)
            if await self.ctx.get_kv(f'after:{request.scene}') is None:
                await self.ctx.set_kv(f'after:{request.scene}', request.observed_at)
        query = trigrams('\n'.join(text_of(message) for message in request.messages))
        scored = sorted(((len(query & trigrams(text)), id, text) for id, text in self.notes(request.scene)),
                        reverse=True)
        return [RecallBlock(f'笔记 #{id}', text) for score, id, text in scored[:self.ctx.config['recall_limit']]
                if score]

    @memory_tool('本群的笔记。action=search 用 query 按文字检索；write 用 text 新增一条，写清是谁、什么事；'
                 'delete 用 id 删除一条过时或错误的笔记；list 列出最近 20 条。')
    async def notes_tool(self, ctx: Invocation, action: Literal['search', 'write', 'delete', 'list'],
                         query: str = '', text: str = '', id: int = 0) -> list | dict:
        if action == 'write':
            if not text.strip():
                raise ValueError('write 需要 text')
            return {'id': self.add(ctx.scene, text.strip())}
        if action == 'delete':
            with self.db:
                removed = self.db.execute('DELETE FROM notes WHERE scene=? AND id=?', (ctx.scene, id)).rowcount
            if not removed:
                raise ValueError(f'本群没有笔记 #{id}')
            return {'deleted': id}
        notes = self.notes(ctx.scene)
        if action == 'search':
            if not query.strip():
                raise ValueError('search 需要 query')
            wanted = trigrams(query)
            notes = [note for note in notes if wanted & trigrams(note[1]) or query.strip() in note[1]]
        return [{'id': id, 'text': text} for id, text in notes[-20:]]

    @background('10m')
    async def upkeep(self, ctx: PluginContext) -> None:
        async with self.lock:
            for scene in sorted(self.serving & set(ctx.scenes)):
                await self.take_notes(scene)

    async def take_notes(self, scene: str) -> None:
        """Turn the messages since the last pass into notes once there are enough of them."""
        after = await self.ctx.get_kv(f'after:{scene}')
        before = self.ctx.now()
        if after >= before:
            return
        messages: list[ChatMessage] = []
        while True:
            page = self.ctx.messages_between(scene, after, before, offset=len(messages), limit=PAGE)
            messages.extend(page)
            if len(page) < PAGE:
                break
        said = [message for message in messages if text_of(message)]
        if len(said) < self.ctx.config['min_messages']:
            return
        lines = '\n'.join(f'{message.sender.card or message.sender.nickname or message.sender.uid}：{text_of(message)}'
                          for message in said)
        reply = await self.ctx.generate(scene, EXTRACT.format(messages=lines), role=self.ctx.config['model_role'])
        for fact in facts(reply):
            self.add(scene, fact)
        await self.ctx.report_memory_progress(scene, messages[-1].id)
        await self.ctx.set_kv(f'after:{scene}', before)
