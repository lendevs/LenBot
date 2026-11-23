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
    with pytest.raises(ValidationError):
        SayArguments.model_validate({'content': '好', 'sticker': '   '})
    parsed = SayArguments.model_validate({'content': '好', 'sticker': '开心'})
    assert parsed.sticker is not None and parsed.sticker.query == '开心'


def _hashed_role(root: Path, count: int):
    config, _ = _instance(root)
    directory = root / 'role' / 'stickers'
    directory.mkdir()
    entries = []
    emotions = ['开心', '无语', '惊讶', '委屈', '得意', '赞叹']
    tags = ['猫猫', '点赞', '摸鱼', '吐槽']
    for index in range(count):
        # 64-hex-char filenames mimicking SHA256 asset names in large libraries.
        prefix = f'{index:04x}' + ('a' if index < 2 else f'{index % 16:x}') * 60
        if index < 2:
            # First two share an 8-char prefix to exercise ambiguous-prefix handling.
            prefix = 'deadbeef' + f'{index:02x}' + '0' * 54
        name = f'{prefix}.png'
        (directory / name).write_bytes(png(COLORS[index % len(COLORS)]))
        entries.append({
            'file': name,
            'description': f'测试表情{index:02d}',
            'emotions': [emotions[index % len(emotions)]],
            'tags': [tags[index % len(tags)]],
        })
    (directory / 'index.yaml').write_text(json.dumps(entries, ensure_ascii=False))
    return config, load_persona(root / 'role'), [entry['file'] for entry in entries]


@pytest.mark.asyncio
async def test_sticker_short_aliases_compact_catalog_and_string_coercion(tmp_path):
    from len_bot.next.chat.tools import build_tools

    # <= 30 stickers: compact s1..sN catalog without 64-char SHA256 filenames.
    small_config, small_persona, small_files = _hashed_role(tmp_path / 'small', 4)
    small_tools = {t['function']['name']: t['function'] for t in build_tools(small_config, small_persona, platform=True)}
    react_desc = small_tools['react']['description']
    assert 's1: 测试表情' in react_desc and 's4: 测试表情' in react_desc
    for filename in small_files:
        assert filename not in react_desc

    # > 30 stickers: overview + representatives instead of dumping all entries.
    large_config, large_persona, large_files = _hashed_role(tmp_path / 'large', 45)
    large_tools = {t['function']['name']: t['function'] for t in build_tools(large_config, large_persona, platform=True)}
    large_desc = large_tools['react']['description']
    assert '共有 45 张素材' in large_desc
    assert '常见情绪：' in large_desc and '常见标签：' in large_desc
    assert 'query' in large_tools['say']['description']
    assert len(large_desc) < 2500
    for filename in large_files:
        assert filename not in large_desc

    ordered = sorted(small_files)
    unique_file = next(name for name in ordered if not name.startswith('deadbeef'))
    with Store(small_config.database) as store:
        async with ChatModel(small_config.model_settings('mind')) as mind:
            chat = Chat(small_config, small_persona, store, mind)
            # Short alias in react.file and say.sticker.file resolves to real PersonaSticker.file.
            _, sent_alias, _ = await _call(chat, 'react', {'file': 's1'})
            assert sent_alias.sticker.file == ordered[0]
            _, said_alias, _ = await _call(chat, 'say', {'content': '来了', 'sticker': {'file': 'S2'}})
            assert said_alias.sticker.file == ordered[1]
            # Unique 8+ char prefix resolves to real file.
            _, sent_prefix, _ = await _call(chat, 'react', {'file': unique_file[:10]})
            assert sent_prefix.sticker.file == unique_file
            # String sticker in say: alias, full file, unique prefix, and fallback to query.
            _, said_str_alias, _ = await _call(chat, 'say', {'content': '好', 'sticker': 's3'})
            assert said_str_alias.sticker.file == ordered[2]
            _, said_str_full, _ = await _call(chat, 'say', {'content': '好', 'sticker': unique_file})
            assert said_str_full.sticker.file == unique_file
            _, said_str_prefix, _ = await _call(chat, 'say', {'content': '好', 'sticker': unique_file[:8]})
            assert said_str_prefix.sticker.file == unique_file
            _, said_str_query, _ = await _call(chat, 'say', {'content': '好', 'sticker': '测试表情02'})
            assert said_str_query.sticker.description == '测试表情02'
            # Ambiguous 8-char prefix is not resolved as a single file.
            with pytest.raises(ValueError, match='没有表情文件'):
                await _call(chat, 'react', {'file': 'deadbeef'})

            # Persona without react still refuses string sticker with permission error.
            no_react = small_persona.model_copy(update={'tools': ['say']})
            restricted = Chat(small_config, no_react, store, mind)
            with pytest.raises(ValueError, match='没有开放表情能力'):
                await _call(restricted, 'say', {'content': 'hi', 'sticker': 's1'})


@pytest.mark.asyncio
async def test_deferred_direct_call_unlock_scene_control_core_and_multiword_search(tmp_path):
    from len_bot.next.tools.discovery import DEFERRED_NAMES, DISCOVERY_REQUIRED_NAMES, search_tools
    from len_bot.next.tools.external_tools import ExternalTool

    assert 'scene_control' not in DEFERRED_NAMES
    assert 'scene_control' not in DISCOVERY_REQUIRED_NAMES

    # Multi-word tool_search ranking and single-word compatibility.
    pool = [
        {'name': 'schedule', 'description': '创建定时提醒', 'source': '宿主'},
        {'name': 'schedule_list', 'description': '查看当前群的定时提醒列表', 'source': '宿主'},
        {'name': 'schedule_cancel', 'description': '取消已创建的定时提醒', 'source': '宿主'},
        {'name': 'member_info', 'description': '查询群成员的群名片与角色信息', 'source': '宿主'},
    ]
    descriptions = {item['name']: item['description'] for item in pool}
    assert [item['name'] for item in search_tools('schedule', pool, descriptions=descriptions)] == [
        'schedule', 'schedule_cancel', 'schedule_list']
    multi = [item['name'] for item in search_tools('定时 取消', pool, descriptions=descriptions)]
    assert multi[0] == 'schedule_cancel' and set(multi) == {'schedule_cancel', 'schedule', 'schedule_list'}
    assert [item['name'] for item in search_tools('群成员 名片', pool, descriptions=descriptions)] == ['member_info']

    config, persona = _instance(tmp_path)
    called = []

    async def run_ext(scene: str, arguments: dict) -> str:
        called.append((scene, arguments))
        return json.dumps({'ok': True})

    external = ExternalTool(
        name='demo_ext',
        description='示例插件工具',
        parameters={'type': 'object', 'properties': {}, 'additionalProperties': False},
        source='插件 demo',
        call=run_ext,
    )
    with Store(config.database) as store:
        async with ChatModel(config.model_settings('mind')) as mind:
            chat = Chat(config, persona, store, mind, external_tools=[external])
            chat.toolset.scene_control = lambda args: {'ok': True}
            chat.set_external_tools([external])
            # scene_control is a core tool without tool_search.
            assert 'scene_control' in chat.toolset.tool_names
            # Allowed deferred tools unlock on direct call and persist to mind_sessions.
            assert 'schedule_list' not in chat.toolset.tool_names
            assert 'demo_ext' not in chat.toolset.tool_names
            result, _, _ = await _call(chat, 'schedule_list', {})
            assert 'schedule_list' in chat.toolset.tool_names
            assert 'schedule_list' in store.load_discovered_tools(SCENE)
            assert result
            ext_result, _, _ = await _call(chat, 'demo_ext', {})
            assert json.loads(ext_result) == {'ok': True}
            assert called == [(SCENE, {})]
            assert {'demo_ext', 'schedule_list'} <= set(store.load_discovered_tools(SCENE))
            # Disallowed or nonexistent tools are still rejected.
            with pytest.raises(ValueError, match='未开放工具'):
                await _call(chat, 'nonexistent_tool', {})
            limited_persona = persona.model_copy(update={'tools': ['say', 'tool_search']})
            limited = Chat(config, limited_persona, store, mind, external_tools=[external])
            with pytest.raises(ValueError, match='未开放工具'):
                await _call(limited, 'demo_ext', {})
