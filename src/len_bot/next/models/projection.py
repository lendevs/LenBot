"""Request history policy for a verified transport, separate from response storage."""

import json
from math import ceil
import re
from string import Template
from typing import Literal

from ..prompt_files import read_prompt
from ..storage.codec import encode


HistoryPolicy = Literal['native', 'omit-reasoning']
FOLD_MIN_CHARS = 1200

_RECALL_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})｜")
_RECALL_LIST_HEADER = re.compile(r"^(\d{2}:\d{2}:\d{2}) (.+) \[([^\]]*record=\d+[^\]]*)\]$")
_RECALL_READ_HEADER = re.compile(r"^(\d{2}:\d{2}:\d{2}) (.+?)(?: \[([^\]]+)\])?$")
_RECALL_RECORD = re.compile(r"record=(\d+)")
_RECALL_MSG_ID = re.compile(r'id=("(?:\\.|[^"\\])*")')
_FORWARD_NODE = re.compile(r"^\s*\[\d+\]\s+\[([^\]]+)\]\s+(.+?)：\s*$")


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


def _preview(text: str, limit: int) -> str:
    compact = ' '.join(text.split())
    return compact if len(compact) <= limit else compact[:limit] + '…'


def _parse_json_object(raw: str) -> dict | None:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_arguments(raw: object) -> dict | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _parse_json_object(raw)


def _unwrap_template(content: str, template_name: str) -> str | None:
    template = read_prompt(template_name)
    before, sep, after = template.partition('$result')
    if not sep:
        return None
    if '$' not in before and '$' not in after:
        if content.startswith(before) and content.endswith(after):
            return content[len(before):len(content) - len(after) if after else len(content)]
        stripped = content.strip()
        p_strip, s_strip = before.lstrip(), after.rstrip()
        if stripped.startswith(p_strip) and stripped.endswith(s_strip):
            return stripped[len(p_strip):len(stripped) - len(s_strip) if s_strip else len(stripped)]
        return None
    lead = before.split('$', 1)[0].lstrip()
    tail = after.rstrip()
    text = content.strip()
    if not text.startswith(lead) or (tail and not text.endswith(tail)):
        return None
    if tail:
        text = text[:-len(tail)].rstrip()
    _, blank, body = text.partition('\n\n')
    return body if blank else None


def _extract_json(content: str, templates: tuple[str, ...]) -> dict | None:
    for name in templates:
        raw = _unwrap_template(content, name)
        if raw is not None:
            parsed = _parse_json_object(raw.strip())
            if parsed is not None:
                return parsed
    stripped = content.strip()
    if stripped.startswith('{'):
        return _parse_json_object(stripped)
    return None


def _fold_web_search(content: str, arguments: dict | None) -> str | None:
    data = _extract_json(content, ('next_web_search.md', 'next_replay_web_search.md'))
    if data is None or ('results' not in data and 'top_page' not in data):
        return None
    results_raw = data.get('results')
    if results_raw is not None and not isinstance(results_raw, list):
        return None
    summary: dict[str, object] = {}
    for key in ('provider', 'query', 'fetched_at', 'recording'):
        if key in data:
            summary[key] = data[key]
    if 'query' not in summary and arguments and 'query' in arguments:
        summary['query'] = arguments['query']
    if arguments and arguments.get('count') is not None:
        summary['count'] = arguments['count']
    if results_raw is not None:
        compact_results = []
        for item in results_raw:
            if not isinstance(item, dict):
                continue
            entry: dict[str, object] = {}
            for key in ('title', 'url', 'published_at', 'document', 'total_chars', 'next_offset'):
                if key in item and item[key] is not None:
                    entry[key] = item[key]
            snippet = item.get('snippet') if isinstance(item.get('snippet'), str) else item.get('summary')
            if isinstance(snippet, str) and snippet.strip():
                entry['snippet'] = _preview(snippet, 80)
            compact_results.append(entry)
        summary['results'] = compact_results
    top_page = data.get('top_page')
    if isinstance(top_page, dict):
        summary['top_page'] = {key: value for key, value in top_page.items() if key != 'text'}
    return (encode(summary)
            + '\n这是较早的搜索结果摘要；top_page 正文可用 web_read(document=...) 重读，或重新 web_search。')


def _recall_labels(bracket: str) -> tuple[int | None, str | None]:
    rec_match = _RECALL_RECORD.search(bracket)
    record = int(rec_match.group(1)) if rec_match else None
    id_match = _RECALL_MSG_ID.search(bracket)
    msg_id = None
    if id_match:
        try:
            parsed = json.loads(id_match.group(1))
            if isinstance(parsed, str):
                msg_id = parsed
        except ValueError:
            pass
    return record, msg_id


def _fold_recall_chat(content: str, arguments: dict | None) -> str | None:
    prefix, sep, _ = read_prompt('next_recall.md').partition('$summary')
    if sep and content.startswith(prefix):
        rest = content[len(prefix):]
        summary_line, blank, body = rest.partition('\n\n')
        if not blank:
            return None
        summary_text = summary_line.strip()
        items: list[dict[str, object]] = []
        current_date: str | None = None
        current: dict[str, object] | None = None
        body_lines: list[str] = []

        def flush() -> None:
            nonlocal current, body_lines
            if current is not None:
                current['preview'] = _preview('\n'.join(body_lines), 60)
                items.append(current)
                current = None
                body_lines = []

        for line in body.splitlines():
            if not line.startswith('  '):
                date_match = _RECALL_DATE.match(line)
                if date_match:
                    flush()
                    current_date = date_match.group(1)
                    continue
                header_match = _RECALL_LIST_HEADER.match(line)
                if header_match:
                    flush()
                    clock, sender, bracket = header_match.groups()
                    record, msg_id = _recall_labels(bracket)
                    current = {}
                    if record is not None:
                        current['record'] = record
                    if msg_id is not None:
                        current['platform_message_id'] = msg_id
                    current['sender'] = sender
                    current['time'] = f'{current_date} {clock}' if current_date else clock
                    continue
            if current is not None:
                body_lines.append(line.strip())
        flush()

        if not items:
            rec_match = _RECALL_RECORD.search(summary_text)
            record = int(rec_match.group(1)) if rec_match else (
                arguments.get('record') if arguments and isinstance(arguments.get('record'), int) else None
            )
            if record is None:
                return None
            lines = body.splitlines()
            item: dict[str, object] = {'record': record}
            if len(lines) >= 2 and '｜' in lines[0]:
                parts = lines[0].split('｜')
                date_str = parts[1] if len(parts) >= 2 else None
                read_hdr = _RECALL_READ_HEADER.match(lines[1])
                if read_hdr:
                    clock, sender, bracket = read_hdr.groups()
                    if bracket:
                        _, msg_id = _recall_labels(bracket)
                        if msg_id is not None:
                            item['platform_message_id'] = msg_id
                    item['sender'] = sender
                    item['time'] = f'{date_str} {clock}' if date_str else clock
                    item['preview'] = _preview('\n'.join(line.strip() for line in lines[2:]), 60)
                else:
                    item['preview'] = _preview(body, 60)
            else:
                item['preview'] = _preview(body, 60)
            items.append(item)

        result: dict[str, object] = {}
        if arguments:
            result['arguments'] = arguments
        result['summary'] = summary_text
        result['count'] = len(items)
        result['messages'] = items
        return (encode(result)
                + '\n这是较早的聊天记录查询摘要；可用 recall_chat 按 record 或条件重读完整原话。')

    stripped = content.strip()
    data = _parse_json_object(stripped) if stripped.startswith('{') else None
    if data is None:
        return None
    raw_items = data.get('messages') or data.get('records') or data.get('items')
    if isinstance(raw_items, list):
        items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            entry: dict[str, object] = {}
            for key in ('record', 'seq', 'platform_message_id', 'id', 'sender', 'sender_id', 'time'):
                if key in item and item[key] is not None:
                    entry[key] = item[key]
            text = item.get('text') if isinstance(item.get('text'), str) else item.get('content')
            if isinstance(text, str):
                entry['preview'] = _preview(text, 60)
            items.append(entry)
        result = {**({'arguments': arguments} if arguments else {}), 'count': len(items), 'messages': items}
        return (encode(result)
                + '\n这是较早的聊天记录查询摘要；可用 recall_chat 按 record 或条件重读完整原话。')
    if 'record' in data and isinstance(data.get('text'), str):
        entry = {key: value for key, value in data.items() if key != 'text'}
        entry['preview'] = _preview(data['text'], 60)
        result = {**({'arguments': arguments} if arguments else {}), 'count': 1, 'messages': [entry]}
        return (encode(result)
                + '\n这是较早的聊天记录查询摘要；可用 recall_chat 按 record 或条件重读完整原话。')
    return None


def _fold_knowledge(content: str, arguments: dict | None) -> str | None:
    data = _extract_json(content, ('next_knowledge.md',))
    if data is None:
        return None
    summary: dict[str, object] = {}
    if arguments:
        summary['arguments'] = arguments
    for key in ('action', 'scope', 'query', 'filename', 'offset', 'next_offset', 'total_chars'):
        if key in data and data[key] is not None:
            summary[key] = data[key]
    if isinstance(data.get('matches'), list):
        compact = []
        for hit in data['matches']:
            if not isinstance(hit, dict):
                continue
            entry: dict[str, object] = {}
            for key in ('scope', 'filename', 'section', 'heading', 'page', 'offset', 'matched'):
                if key in hit and hit[key] is not None:
                    entry[key] = hit[key]
            text = hit.get('text') if isinstance(hit.get('text'), str) else hit.get('content')
            if isinstance(text, str):
                entry['preview'] = _preview(text, 80)
            compact.append(entry)
        summary['count'] = len(compact)
        summary['matches'] = compact
    elif isinstance(data.get('files'), list):
        compact = [
            {key: item[key] for key in ('scope', 'filename', 'chars', 'pages', 'error')
             if key in item and item[key] is not None}
            for item in data['files'] if isinstance(item, dict)
        ]
        summary['count'] = len(compact)
        summary['files'] = compact
    elif isinstance(data.get('text'), str) or isinstance(data.get('content'), str):
        text = data['text'] if isinstance(data.get('text'), str) else data['content']
        for key in ('section', 'heading', 'page'):
            if key in data and data[key] is not None:
                summary[key] = data[key]
        summary['count'] = 1
        summary['preview'] = _preview(text, 80)
    else:
        return None
    return (encode(summary)
            + '\n这是较早的资料检索摘要；可用 knowledge 按 filename 与 offset 重读原文。')


def _fold_open_forward(content: str, arguments: dict | None) -> str | None:
    data = _extract_json(content, ('next_forward.md',))
    if data is None or not isinstance(data.get('text'), str):
        return None
    nodes: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current, body_lines
        if current is not None:
            current['preview'] = _preview('\n'.join(body_lines), 60)
            nodes.append(current)
            current = None
            body_lines = []

    for line in data['text'].splitlines():
        match = _FORWARD_NODE.match(line)
        if match:
            flush()
            current = {'time': match.group(1), 'sender': match.group(2)}
            continue
        if current is not None:
            body_lines.append(line.strip())
    flush()

    summary: dict[str, object] = {}
    for key in ('message', 'forward', 'forward_id', 'top_level_items', 'offset', 'total_chars', 'next_offset'):
        if key in data and data[key] is not None:
            summary[key] = data[key]
    if 'message' not in summary and arguments and 'message' in arguments:
        summary['message'] = arguments['message']
    summary['item_count'] = data['top_level_items'] if isinstance(data.get('top_level_items'), int) else len(nodes)
    if nodes:
        summary['senders'] = list(dict.fromkeys(node['sender'] for node in nodes))
        summary['time_range'] = {'start': nodes[0]['time'], 'end': nodes[-1]['time']}
        summary['previews'] = nodes[:3]
    else:
        summary['preview'] = _preview(data['text'], 120)
    return (encode(summary)
            + '\n这是较早展开的合并转发摘要；需要细节时可再次调用 open_forward。')


_FOLDABLE_TOOLS = {
    'web_search': _fold_web_search,
    'recall_chat': _fold_recall_chat,
    'knowledge': _fold_knowledge,
    'open_forward': _fold_open_forward,
}


def project_old_results(entries: list[tuple[int, dict]], keep_recent_tokens: int) -> list[tuple[int, dict]]:
    """Keep recent results whole; older saved web pages and large read-only results fold to compact summaries."""
    prefix, _, suffix = Template(read_prompt('next_web_read.md')).substitute(result='\0').partition('\0')
    calls: dict[str, tuple[str, object]] = {}
    candidates: list[tuple[int, str, object]] = []
    for index, (_, message) in enumerate(entries):
        if message['role'] == 'assistant':
            for call in message.get('tool_calls') or []:
                fn = call['function']
                calls[call['id']] = (fn['name'], fn.get('arguments'))
        if message['role'] != 'tool' or not isinstance(message.get('content'), str):
            continue
        paired = calls.get(message['tool_call_id'])
        if paired is None:
            continue
        name, raw_args = paired
        content = message['content']
        if name == 'web_read' and content.startswith(prefix) and content.endswith(suffix):
            candidates.append((index, name, raw_args))
        elif name in _FOLDABLE_TOOLS and len(content) > FOLD_MIN_CHARS:
            candidates.append((index, name, raw_args))
    if not candidates:
        return entries
    if keep_recent_tokens > 0:
        offsets = [0]
        for _, message in entries:
            offsets.append(offsets[-1] + ceil(len(encode(message).encode('utf-8')) / 3))
        step = max(1, keep_recent_tokens // 2)
        cutoff = (offsets[-1] - keep_recent_tokens) // step * step
        candidates = [item for item in candidates if offsets[item[0]] < cutoff]
    if not candidates:
        return entries
    projected = entries.copy()
    changed = False
    for index, name, raw_args in candidates:
        seq, message = entries[index]
        content = message['content']
        if name == 'web_read':
            try:
                page = json.loads(content[len(prefix):len(content) - len(suffix)])
            except ValueError:
                continue
            if not isinstance(page, dict):
                continue
            metadata = {key: value for key, value in page.items() if key != 'text'}
            folded = (encode(metadata) +
                      '\n这是较早读过的网页位置；正文仍保存在该 document，可用 web_read(document, offset) 重读。')
        else:
            folded = _FOLDABLE_TOOLS[name](content, _parse_arguments(raw_args))
            if folded is None:
                continue
        projected[index] = (seq, {**message, 'content': folded})
        changed = True
    return projected if changed else entries
