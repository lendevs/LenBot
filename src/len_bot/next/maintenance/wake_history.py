"""Read wake markers retained in historical mind requests for offline upgrades and replay."""


# Opening markers written by chat/attention.py (wake_reason and batch reasons), chat/schedule.py,
# work/ (task notices) and plugin events, newest-last in the opening request. Historical data is
# best effort: "[群里在聊]" is written both for ambient talk without a score and for exploration,
# so it stays unknown; a turn without any retained marker is unknown too.
MARKERS = (
    ('[直接唤醒：', 'direct'), ('[点名：', 'named'), ('[对话继续]', 'focus'),
    ('[群里在聊；', 'ambient'), ('[群里在聊]', 'unknown'), ('[恢复未结束的对话]', 'resume'),
    ('[持续关注条件命中', 'attention'), ('[定时唤醒]', 'schedule'), ('[任务', 'task'),
    ('[插件 ', 'plugin'),
    # Reminders, task results and plugin events append their own message after this batch,
    # so a batch with this reason as the last input opened an audio-transcript turn.
    ('[此前未触发唤醒的消息]', 'audio'),
)


def request_wake(request: dict) -> tuple[str, str]:
    if 'snapshot_expired_at' in request:
        return 'unknown', ''
    for message in reversed(request['messages']):
        content = message.get('content')
        if message['role'] != 'user' or not isinstance(content, str):
            continue
        if content.startswith('<当前场景状态与参考>'):
            continue
        for marker, channel in MARKERS:
            if content.startswith(marker):
                return channel, content
        return 'unknown', content
    return 'unknown', ''
