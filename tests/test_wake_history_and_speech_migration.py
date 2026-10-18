"""Historical wake classification and the speech window after upgrading (audit D-1, D-2)."""
import json
import sqlite3

import pytest

from len_bot.next.maintenance.migrate import _speech_records
from len_bot.next.maintenance.wake_history import request_wake


def _request(*contents):
    return {'messages': [{'role': 'system', 'content': 's'},
                         *({'role': 'user', 'content': text} for text in contents),
                         {'role': 'user', 'content': '<当前场景状态与参考>…'}]}


@pytest.mark.parametrize('content,channel', [
    ('[直接唤醒：被 @、被回复或私聊]\n…', 'direct'),
    ('[点名：小然]\n…', 'named'),
    ('[对话继续]\n…', 'focus'),
    ('[群里在聊；参与分 0.812]\n…', 'ambient'),
    # Without the score the same text is used for exploration: do not guess.
    ('[群里在聊]\n…', 'unknown'),
    ('[恢复未结束的对话]\n…', 'resume'),
    ('[持续关注条件命中：请判断是否已完成，未完成则继续保留]\n…', 'attention'),
    ('[定时唤醒] #3；已交付当前会话，尚未发送提醒\n…', 'schedule'),
    ('[任务执行结束] #7；请求人 onebot:1；整理\n{}', 'task'),
    ('[任务进度] #7；整理\n…', 'task'),
    ('[任务提问] #7；…', 'task'),
    ('[插件 clock 发来的场景事件 · 2026-10-15T12:00:00+08:00]\n…', 'plugin'),
    ('[此前未触发唤醒的消息]\nonebot:group:80001｜…', 'audio'),
    ('随便什么', 'unknown'),
])
def test_opening_markers_map_to_runtime_wake_channels(content, channel):
    assert request_wake(_request('older', content))[0] == channel


def test_reminder_after_a_queued_batch_is_a_schedule_not_audio():
    assert request_wake(_request('[此前未触发唤醒的消息]\n…', '[定时唤醒] #1；…'))[0] == 'schedule'


def _db(rows):
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE messages (seq INTEGER PRIMARY KEY, scene TEXT NOT NULL, platform_id TEXT, '
               'body TEXT NOT NULL, raw TEXT, received_at REAL, persona_id TEXT)')
    for scene, at, is_self, status, raw in rows:
        db.execute('INSERT INTO messages(scene,body,raw) VALUES (?,?,?)',
                   (scene, json.dumps({'time': at, 'is_self': is_self, 'send_status': status}), raw))
    return db


def test_upgrade_seeds_the_last_hour_of_own_group_messages():
    now = 1790618400.
    group, other = 'onebot:group:80001', 'onebot:group:80002'
    db = _db([(group, now - 4000, True, 'sent', None),        # outside the window
              (group, now - 1800, True, 'sent', None),
              (group, now - 900, True, 'simulated', None),
              (group, now - 600, True, 'unconfirmed', None),
              (group, now - 300, True, 'failed', None),        # never delivered
              (group, now - 200, False, 'received', '{}'),     # a member's message
              (group, now - 150, True, 'sent', '{}'),          # own part paired with its echo
              (group, now - 120, True, 'received', '{}'),      # own part reported by the platform
              (other, now - 100, True, 'sent', None),
              ('onebot:private:70001', now - 100, True, 'sent', None)])
    _speech_records(db, now=now)
    rows = db.execute('SELECT scene,time FROM speech ORDER BY time').fetchall()
    assert rows == [(group, now - 1800), (group, now - 900), (group, now - 600),
                    (group, now - 150), (group, now - 120), (other, now - 100)]
    _speech_records(db, now=now)  # idempotent: a retried step does not seed twice
    assert db.execute('SELECT COUNT(*) FROM speech').fetchone()[0] == 6
