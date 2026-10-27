"""Historical wake classification for offline replay."""
import pytest

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

