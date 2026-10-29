"""react preview: numbered candidates of the role and this group, the sheet for the mind, sending by number."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import pytest
from PIL import Image

from len_bot.next.chat.session import Chat
from len_bot.next.models.client import ChatModel, ToolCall
from len_bot.next.persona.profile import load_persona
from len_bot.next.storage.store import Store
from test_native_tool_calls import _instance, _receive, _unused_wait

SCENE = 'onebot:group:80001'
OTHER = 'onebot:group:80002'
COLORS = ['red', 'orange', 'yellow', 'green', 'cyan', 'blue', 'purple', 'pink', 'gray', 'black', 'white']


def png(color: str) -> bytes:
    output = BytesIO()
    Image.new('RGB', (48, 48), color).save(output, format='PNG')
    return output.getvalue()


def _role(root: Path, count: int, *, image_input: bool = True):
    config, _ = _instance(root)
    directory = root / 'role' / 'stickers'
    directory.mkdir()
    entries = []
    for index in range(count):
        name = f'{index:02}.png'
        (directory / name).write_bytes(png(COLORS[index]))
        # Two stickers share the tag being searched; the others only share the emotion.
        entries.append({'file': name, 'description': f'{COLORS[index]} 的脸', 'emotions': ['开心'],
                        'tags': ['对勾'] if index in {3, 7} else []})
    (directory / 'index.yaml').write_text(json.dumps(entries, ensure_ascii=False))
    config.models.roles.mind.image_input = image_input
    return config, load_persona(root / 'role')


def _adopt(store: Store, scene: str, seq: int, color: str, description: str) -> int:
    """An adopted, annotated sticker of ``scene`` with its own original."""
    with store.db:
        media = store.db.execute(
            "INSERT INTO media(source_message_seq,source_image_index,mime_type,width,height,animated,data) "
            "VALUES (?,?,?,?,?,?,?)", (seq, 1, 'image/png', 48, 48, 0, png(color))).lastrowid
        return store.db.execute(
            "INSERT INTO sticker_candidates(scene,source_message_seq,image_index,media_id,status,review,"
            "description,text,emotions,tags,created,updated) VALUES (?,?,?,?,'complete','adopted',?,'',?,?,0,0)",
            (scene, seq, 1, media, description, json.dumps(['开心']), json.dumps([]))).lastrowid


async def _call(chat: Chat, name: str, arguments: dict):
    return await chat.toolset.execute('turn', ToolCall('call', name, arguments), _unused_wait)


@pytest.mark.asyncio
@pytest.mark.parametrize('image_input', [True, False])
async def test_preview_numbers_up_to_nine_matching_first_and_sends_the_numbered_original(tmp_path, image_input):
    config, persona = _role(tmp_path, 11, image_input=image_input)
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind:
            chat = Chat(config, persona, store, mind)
            content, expression, _ = await _call(chat, 'react', {'preview': True, 'query': '对勾'})
            assert expression is None
            result = json.loads(content.split('\n', 1)[0])
            files = [entry['file'] for entry in result['candidates']]
            assert [entry['number'] for entry in result['candidates']] == list(range(1, 10))
            assert files[:2] == ['03.png', '07.png'] and result['matched'] is True
            assert [chat.expression.sticker_candidates[n].file for n in range(9)] == files
            if image_input:
                label, sheet = chat.toolset.looked[-1]
                with Image.open(BytesIO(sheet)) as image:
                    assert (label, image.format, image.size) == ('表情候选', 'JPEG', (600, 600))
            else:
                assert chat.toolset.looked == []
            _, sent, _ = await _call(chat, 'react', {'candidate': 2, 'end_turn': True})
            assert sent.sticker.file == '07.png' and sent.sticker.data == png(COLORS[7])
            _, said, _ = await _call(chat, 'say', {'content': '好', 'sticker': {'candidate': 1}})
            assert said.sticker.file == '03.png'
            with pytest.raises(ValueError, match='没有编号 9'):
                chat.expression.sticker_candidates = chat.expression.sticker_candidates[:8]
                await _call(chat, 'react', {'candidate': 9})


@pytest.mark.asyncio
async def test_preview_adds_only_this_groups_adopted_stickers_and_the_described_path_is_unchanged(tmp_path):
    config, persona = _role(tmp_path, 2)
    from len_bot.next.configuration.learning import LearningSettings
    config.learning = LearningSettings(extract=False, collect_stickers=True)
    with Store(config.database) as store:
        _receive(store, 70002, 51000, '发了一张图')
        own = _adopt(store, SCENE, store.max_message_seq(SCENE), 'brown', '本群的棕色脸')
        _adopt(store, OTHER, 2, 'olive', '别的群的橄榄色脸')
        async with ChatModel(config.model_settings('mind')) as mind:
            chat = Chat(config, persona, store, mind)
            content, _, _ = await _call(chat, 'react', {'preview': True})
            result = json.loads(content.split('\n', 1)[0])
            assert 'matched' not in result
            assert [(entry['kind'], entry.get('file') or entry.get('id')) for entry in result['candidates']] == [
                ('persona', '00.png'), ('persona', '01.png'), ('group', own)]
            _, sent, _ = await _call(chat, 'react', {'candidate': 3})
            assert sent.sticker.candidate_id == own and sent.sticker.data == png('brown')
            assert '本群表情' in sent.message.segments[-1].data['summary']
            # Without a preview a number has nothing to refer to; file, emotion and query still send directly.
            chat.expression.sticker_candidates = []
            with pytest.raises(ValueError, match='没有编号 1'):
                await _call(chat, 'react', {'candidate': 1})
            _, direct, _ = await _call(chat, 'react', {'file': '01.png'})
            assert direct.sticker.file == '01.png'


def test_preview_rejects_a_file_or_number_and_say_has_no_preview():
    from pydantic import ValidationError
    from len_bot.next.chat.tools import ReactArguments, SayArguments

    for arguments in ({'preview': True, 'file': '00.png'}, {'preview': True, 'candidate': 1},
                      {'preview': True, 'emotion': '开心', 'query': '对勾'}):
        with pytest.raises(ValidationError):
            ReactArguments.model_validate(arguments)
    with pytest.raises(ValidationError):
        SayArguments.model_validate({'content': '好', 'sticker': {'preview': True}})
