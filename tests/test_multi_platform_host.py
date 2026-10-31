"""One host serving a OneBot group and a Telegram group at the same time."""

import asyncio
import time
from io import BytesIO

import httpx
import pytest
from websockets.asyncio.server import serve

from len_bot.next.chat.tools import build_tools, tool_unavailable_reasons
from len_bot.next.config import load_host_config
from len_bot.next.configuration.chat import ImageSettings
from len_bot.next.media.images import LookArguments, load_look_image
from len_bot.next.models.client import ChatModel
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform import telegram
from len_bot.next.platform.adapter import PlatformGroup, adapter_for, open_platform
from len_bot.next.platform.identity import validate_scene
from len_bot.next.platform.telegram import parse_update
from len_bot.next.platform.onebot import OneBot
from len_bot.next.platform.telegram import Telegram
from len_bot.next.runtime.network import NetworkRuntime
from len_bot.next.storage.store import Store
from test_scene_commands_protocol import MEMBER, SCENE, Peer, until, write_config
from test_telegram_adapter import BOT, GROUP, TOKEN, BotAPI, _message

TELEGRAM_SCENE = f'telegram:group:{GROUP}'
SCENE_SETTINGS = {'persona': 'persona', 'attention': {'only_direct': True}}


def test_several_platforms_open_as_a_group_and_one_as_its_adapter(tmp_path):
    write_config(tmp_path, onebot={'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
                 telegram={'bot_id': f'telegram:{BOT}', 'bot_token': TOKEN},
                 scenes={SCENE: SCENE_SETTINGS, TELEGRAM_SCENE: SCENE_SETTINGS})
    group = open_platform(load_host_config(tmp_path), on_event=lambda raw: None, on_error=lambda text: None)
    assert isinstance(group, PlatformGroup) and group.name == 'onebot+telegram'
    assert isinstance(adapter_for(group, TELEGRAM_SCENE), Telegram) and isinstance(adapter_for(group, SCENE), OneBot)
    assert adapter_for(group, 'feishu:group:oc_room') is None
    single = tmp_path / 'single'
    single.mkdir()
    write_config(single, onebot=None, telegram={'bot_id': f'telegram:{BOT}', 'bot_token': TOKEN}, bot_id=f'telegram:{BOT}',
                 owners=['telegram:501'], scenes={TELEGRAM_SCENE: SCENE_SETTINGS})
    adapter = open_platform(load_host_config(single), on_event=lambda raw: None, on_error=lambda text: None)
    assert isinstance(adapter, Telegram) and adapter_for(adapter, TELEGRAM_SCENE) is adapter


@pytest.mark.asyncio
async def test_each_scene_is_answered_on_its_own_platform_by_its_own_bot(tmp_path, monkeypatch):
    api = BotAPI()
    monkeypatch.setattr(telegram, '_transport', lambda proxy: httpx.MockTransport(api.handle))
    peer = Peer()
    async with serve(peer.serve, '127.0.0.1', 0) as server:
        write_config(tmp_path, onebot={'mode': 'forward_ws', 'request_timeout_seconds': 1,
                                       'ws_url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'},
                     telegram={'bot_id': f'telegram:{BOT}', 'bot_token': TOKEN},
                     scenes={SCENE: SCENE_SETTINGS, TELEGRAM_SCENE: SCENE_SETTINGS})
        config = load_host_config(tmp_path)
        persona = load_persona(tmp_path / 'persona')
        with Store(config.database) as store:
            async with ChatModel(config.model_settings('mind')) as model:
                runtime = NetworkRuntime(config, [(config.scene_config(scene), persona) for scene in config.scenes],
                                         store, model)
                running = asyncio.create_task(runtime.run(manage_signals=False))
                await until(lambda: runtime.status == 'running')
                try:
                    api.push(_message('/id', message_id=5))
                    await until(lambda: any(method == 'sendMessage' for method, _ in api.calls))
                    sent = next(params for method, params in api.calls if method == 'sendMessage')
                    assert sent['text'] == (f'场景：{TELEGRAM_SCENE}\n发送者账号：telegram:501\n'
                                            f'Bot 账号：telegram:{BOT}')
                    assert sent['chat_id'] == GROUP and sent['reply_parameters']['message_id'] == 5
                    await peer.say('/id')
                    await until(lambda: peer.sends)
                    assert peer.texts() == [f'场景：{SCENE}\n发送者账号：onebot:{MEMBER}\nBot 账号：onebot:90001']
                    assert [method for method, _ in api.calls].count('sendMessage') == 1
                    stored = store.find_message(TELEGRAM_SCENE, '5')
                    assert stored.platform == 'telegram' and stored.sender.uid == 'telegram:501'
                finally:
                    runtime.stop()
                    await asyncio.wait_for(running, 3)


def test_tools_follow_the_platform_of_the_scene(tmp_path):
    write_config(tmp_path, onebot={'mode': 'forward_ws', 'ws_url': 'ws://127.0.0.1:9'},
                 telegram={'bot_id': f'telegram:{BOT}', 'bot_token': TOKEN},
                 scenes={SCENE: SCENE_SETTINGS, TELEGRAM_SCENE: SCENE_SETTINGS})
    role = tmp_path / 'persona' / 'persona.yaml'
    role.write_text(role.read_text().replace('tools: []', 'tools: [say]'))
    config, persona = load_host_config(tmp_path), load_persona(tmp_path / 'persona')
    for name in ('member_info', 'group_files', 'open_forward', 'message_reaction', 'transcribe'):
        assert '只支持 OneBot 平台' in tool_unavailable_reasons(config.scene_config(TELEGRAM_SCENE), persona, name)
        assert '只支持 OneBot 平台' not in tool_unavailable_reasons(config.scene_config(SCENE), persona, name)
    say = next(tool['function'] for tool in build_tools(config.scene_config(TELEGRAM_SCENE), persona, platform=True)
               if tool['function']['name'] == 'say')
    mention = say['parameters']['properties']['mention']
    assert mention['anyOf'][0]['pattern'] == '^telegram:[1-9][0-9]*$' and 'telegram:70001' in mention['description']
    assert config.scene_config(TELEGRAM_SCENE).bot_id == f'telegram:{BOT}'


@pytest.mark.parametrize('scene,valid', [
    ('telegram:group:-1001234', True), ('telegram:private:501', True), ('telegram:group:1001234', False),
    ('feishu:group:oc_room', True), ('feishu:private:ou_ann', True), ('feishu:group:ou_ann', False),
    ('feishu:private:oc_room', False)])
def test_scene_identifiers_follow_each_platform(scene, valid):
    if valid:
        assert validate_scene(scene) == scene
    else:
        with pytest.raises(ValueError, match='scene must match'):
            validate_scene(scene)


@pytest.mark.asyncio
async def test_look_downloads_an_image_a_platform_names_by_reference(tmp_path):
    from PIL import Image
    picture = BytesIO()
    Image.new('RGB', (40, 30), 'red').save(picture, format='PNG')
    update = {'update_id': 1, 'message': _message(message_id=8, photo=[
        {'file_id': 'AgAC-photo', 'file_unique_id': 'p', 'width': 40, 'height': 30}])}
    requested = []

    async def fetch_media(data: dict, max_bytes: int) -> bytes:
        requested.append((data['file_id'], max_bytes))
        return picture.getvalue()

    with Store(tmp_path / 'chat.sqlite3') as store:
        store.enqueue(parse_update(update, bot=BOT, username='len_bot'), update, time.time())
        asset, reused, source = await load_look_image(
            store, TELEGRAM_SCENE, LookArguments(message='8'), ImageSettings(), fake_ip_networks=(),
            fetch_media=fetch_media)
        assert (asset.width, asset.height, reused, source) == (40, 30, False, 'platform_download')
        assert requested == [('AgAC-photo', ImageSettings().max_bytes)]
        again = await load_look_image(store, TELEGRAM_SCENE, LookArguments(message='8'), ImageSettings(),
                                      fake_ip_networks=(), fetch_media=fetch_media)
        assert again[1:] == (True, 'cache') and len(requested) == 1
