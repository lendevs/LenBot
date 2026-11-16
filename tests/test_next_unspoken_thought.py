"""A plain-text assistant turn is an unspoken thought, not a sample reply to imitate."""

from __future__ import annotations

from len_bot.next.chat.context import ChatContext


def test_plain_text_assistant_turn_is_relabelled_as_an_unspoken_note():
    message = {'role': 'assistant', 'content': '  先看看他们在聊什么  '}
    projected = ChatContext._unspoken_thought(message)
    assert projected['role'] == 'user'
    assert projected['content'].startswith('[上一轮未发出的内部想法')
    assert projected['content'].endswith('先看看他们在聊什么')


def test_assistant_turn_with_tool_calls_keeps_its_role_and_content():
    message = {'role': 'assistant', 'content': '',
               'tool_calls': [{'id': 'call_1', 'type': 'function',
                               'function': {'name': 'say', 'arguments': '{}'}}]}
    assert ChatContext._unspoken_thought(message) is message


def test_everything_else_passes_through_untouched():
    for message in ({'role': 'tool', 'content': 'ok'},
                    {'role': 'user', 'content': '在吗'},
                    {'role': 'assistant', 'content': '   '},
                    {'role': 'assistant', 'content': None}):
        assert ChatContext._unspoken_thought(message) is message
