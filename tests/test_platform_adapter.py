"""The runtime reaches its chat platform only through the adapter interface."""

from len_bot.next.config import load_host_config
from len_bot.next.platform.adapter import PlatformAdapter, PlatformCallError, open_platform
from len_bot.next.platform.messages import ChatMessage
from len_bot.next.platform.onebot import OneBot, OneBotCallError
from test_scene_commands_protocol import MESSAGE, write_config


def test_onebot_is_opened_behind_the_adapter_and_parses_its_own_events(tmp_path):
    write_config(tmp_path, onebot={'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'})
    config = load_host_config(tmp_path)
    adapter = open_platform(config, on_event=lambda raw: None, on_error=lambda text: None)
    assert isinstance(adapter, OneBot) and isinstance(adapter, PlatformAdapter) and adapter.name == 'onebot'
    message = adapter.parse(MESSAGE)
    assert isinstance(message, ChatMessage) and message.scene == 'onebot:group:80001'
    assert adapter.parse({'post_type': 'meta_event', 'meta_event_type': 'heartbeat'}) is None
    assert issubclass(OneBotCallError, PlatformCallError)


def test_no_platform_for_stdin_and_panel_only_hosts(tmp_path):
    write_config(tmp_path, onebot=None, delivery='simulated')
    assert open_platform(load_host_config(tmp_path), on_event=lambda raw: None, on_error=lambda text: None) is None
