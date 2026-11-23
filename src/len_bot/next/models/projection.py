"""Request history policy for a verified transport, separate from response storage."""

from typing import Literal
from ..prompt_files import read_prompt


HistoryPolicy = Literal['native', 'omit-reasoning']


def project_messages(messages: list[dict], policy: HistoryPolicy) -> list[dict]:
    if policy == 'native':
        return messages
    projected = []
    for message in messages:
        if message['role'] != 'assistant':
            projected.append(message)
            continue
        # This route reconstructs its own signed continuation. Opaque extensions
        # and native call IDs are retained; readable unsigned analysis is optional.
        item = {key: value for key, value in message.items() if key != 'reasoning_content'}
        if (set(item) <= {'role', 'content', 'tool_calls'} and not item['content']
                and not item.get('tool_calls')):
            continue
        projected.append(item)
    return projected


def project_old_results(entries: list[tuple[int, dict]], keep_recent_tokens: int) -> list[tuple[int, dict]]:
    """Keep recent results whole; older saved web pages remain readable by document ID."""
    import json
    from math import ceil
    from ..storage.codec import encode

    from string import Template

    prefix, _, suffix = Template(read_prompt('next_web_read.md')).substitute(result='\0').partition('\0')
    calls = {}
    pages = []
    for index, (_, message) in enumerate(entries):
        if message['role'] == 'assistant':
            for call in message.get('tool_calls') or []:
                calls[call['id']] = call['function']['name']
        if (message['role'] == 'tool'
                and calls.get(message['tool_call_id']) == 'web_read'
                and message['content'].startswith(prefix) and message['content'].endswith(suffix)):
            pages.append(index)
    if not pages:
        return entries
    if keep_recent_tokens > 0:
        offsets = [0]
        for _, message in entries:
            offsets.append(offsets[-1] + ceil(len(encode(message).encode('utf-8')) / 3))
        step = max(1, keep_recent_tokens // 2)
        cutoff = (offsets[-1] - keep_recent_tokens) // step * step
        pages = [index for index in pages if offsets[index] < cutoff]
    projected = entries.copy()
    for index in pages:
        seq, message = entries[index]
        page = json.loads(message['content'][len(prefix):len(message['content']) - len(suffix)])
        metadata = {key: value for key, value in page.items() if key != 'text'}
        projected[index] = (seq, {**message, 'content': encode(metadata) +
                                  '\n这是较早读过的网页位置；正文仍保存在该 document，可用 web_read(document, offset) 重读。'})
    return projected
