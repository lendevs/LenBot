"""Compare local recall on a small, inspectable synthetic corpus, without model calls.

Run the same script with each checkout on PYTHONPATH. JSON includes the actual recalled
text, evidence coverage, character count and latency; it does not grade generated answers.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import time

from len_bot.next.memory.jobs import MemoryJobs
from len_bot.next.memory.local import LocalMemory, LocalMemorySettings
from len_bot.next.memory.service import LocalMemoryConfig, MemoryService
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store


SCENE = 'onebot:group:80001'
DOCUMENTS = {
    'events/week.md': (
        '# 本周安排\n\n## 读书会\n'
        + '读书会先读完上一章，再交流各自标记的段落。' * 18
        + '\n读书会最终地点是图书馆二楼，时间为周六下午三点。\n\n'
        '## 出游\n出游集合点是南门，周日上午九点出发。\n'
    ),
    'people/accounts.md': (
        '# 同名群友\n\n## 小林 onebot:70001\n'
        '小林 onebot:70001 的饮料偏好是无糖豆浆。\n\n'
        '## 小林 onebot:70002\n小林 onebot:70002 的饮料偏好是热红茶。\n'
    ),
    'events/report.md': (
        '# 报告\n\n## 当前约定\n'
        + '报告原定周五提交。大家讨论了排版、附录和数据来源。' * 14
        + '\n报告最新更正为周六中午提交，覆盖之前的周五约定。\n'
    ),
    'topics/strasse.md': '# Straße\n\nStraße 的集合地址是东侧咖啡店。\n',
}
CASES = [
    ('long-section', ['读书会最终地点和时间是什么？'], ['图书馆二楼', '周六下午三点']),
    ('latest-correction', ['报告最新什么时候交？'], ['最新更正为周六中午提交']),
    ('same-name-first', ['onebot:70001 的饮料偏好'], ['无糖豆浆']),
    ('same-name-second', ['onebot:70002 的饮料偏好'], ['热红茶']),
    ('follow-up', ['读书会的安排', '接着说地点和时间'], ['图书馆二楼']),
    ('case-fold', ['STRASSE 集合地址'], ['东侧咖啡店']),
    ('no-evidence', ['火星飞船什么时候起飞？'], []),
    ('forgotten', ['南门出游集合'], []),
]


async def compare() -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        settings = LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=root / 'memory'),
                                     recall_limit=5, recall_budget_chars=1800)
        backend = LocalMemory(settings.local)
        for path, content in DOCUMENTS.items():
            await backend.write(SCENE, path, content, '人工可核对的合成对照样本')
        await backend.write('onebot:group:80002', 'secret.md', '本群独有暗号海蓝石，读书会。', '隔离样本')
        await backend.write(SCENE, 'bot/other/profile.md', '其他角色独有暗号紫云石，读书会。', '角色隔离样本')
        await backend.write(SCENE, 'legacy-import/pending.md', '待采用暗号金砂石，读书会。', '待采用样本')
        rows = []
        with Store(root / 'chat.db') as store, MemoryJobs(root / 'jobs.db') as jobs:
            service = MemoryService(settings, backend, jobs=jobs, store=store, active_personas={SCENE: 'current'})
            for name, texts, expected in CASES:
                if name == 'forgotten':
                    await backend.forget(SCENE, 'events/week.md')
                messages = [parse_message({
                    'post_type': 'message', 'message_type': 'group', 'group_id': 80001,
                    'user_id': 90001, 'self_id': 80000, 'message_id': index, 'time': 1791060000,
                    'sender': {'nickname': '提问者', 'role': 'member'},
                    'message': [{'type': 'text', 'data': {'text': text}}]}, own_message_ids=set())
                    for index, text in enumerate(texts, 1)]
                started = time.perf_counter()
                result = await service.recall(SCENE, messages)
                elapsed = (time.perf_counter() - started) * 1000
                content = '\n'.join(item['content'] for item in result['items'])
                rows.append({'case': name, 'query': texts, 'expected_evidence': expected,
                             'covered': [part for part in expected if part in content],
                             'chars': result['content_chars'], 'elapsed_ms': round(elapsed, 3),
                             'excluded_scope_leaked': any(word in content for word in ['海蓝石', '紫云石', '金砂石']),
                             'items': result['items']})
        return {'mode': 'text-only; no embedding or answer model', 'budget_chars': 1800, 'cases': rows}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(compare()), ensure_ascii=False, indent=2))
