"""Section retrieval across embedding HTTP, source edits and offline index upgrades."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import sqlite3

import pytest

from len_bot.next.memory.embeddings import EmbeddingBinding, EmbeddingClient, EmbeddingSettings
from len_bot.next.memory.local import LocalMemory, LocalMemorySettings
from len_bot.next.memory.jobs import MemoryJobs
from len_bot.next.memory.sections import evidence, query_terms
from len_bot.next.memory.service import LocalMemoryConfig, MemoryService, recall_cues
from len_bot.next.platform.onebot_messages import parse_message
from len_bot.next.storage.store import Store
from test_host_stream import panel, login


SCENE = 'onebot:group:80001'


@asynccontextmanager
async def embeddings():
    """Synthetic protocol peer with a visible three-topic mapping, not a model-quality test."""
    requests = []

    async def peer(reader, writer):
        head = (await reader.readuntil(b'\r\n\r\n')).decode()
        fields = {key.lower(): value.strip() for line in head.split('\r\n') if ':' in line
                  for key, value in [line.split(':', 1)]}
        body = json.loads(await reader.readexactly(int(fields['content-length'])))
        requests.append(body)
        data = []
        for index, text in enumerate(body['input']):
            vector = ([1., 0., 0.] if any(word in text for word in ['图书馆', '借阅空间']) else
                      [0., 1., 0.] if '预算' in text else [0., 0., 1.])
            data.append({'index': index, 'embedding': vector})
        payload = json.dumps({'data': data}).encode()
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
                     + str(len(payload)).encode() + b'\r\nConnection: close\r\n\r\n' + payload)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(peer, '127.0.0.1', 0)
    async with server:
        settings = EmbeddingSettings(provider='sample', model='three-topics', dimensions=3,
                                    base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
                                    api_key='synthetic')
        async with EmbeddingClient(settings) as client:
            yield client, requests


@pytest.mark.asyncio
async def test_semantic_unit_is_the_returned_source_and_tracks_replacements(tmp_path):
    async with embeddings() as (client, requests):
        memory = LocalMemory(LocalMemorySettings(directory=tmp_path / 'memory',
            embedding=EmbeddingBinding(provider='sample', model='three-topics', dimensions=3)), embedding=client)
        content = ('# 项目\n\n## 预算\n' + '预算用于修缮室内设施。' * 60
                   + '\n\n## 聚会\n集合地点是图书馆二楼。\n\n## 示例\n```markdown\n## 不是标题\n```\n')
        await memory.write(SCENE, 'events/week.md', content, '合成协议样本')
        assert len(requests[0]['input']) == 3
        assert all(text.startswith('项目\n## ') for text in requests[0]['input'])
        assert '## 不是标题' in requests[0]['input'][2]
        hits = await memory.search(SCENE, '借阅空间在哪？', 1, automatic=True)
        assert len(hits) == 1 and hits[0].preview == '## 聚会\n集合地点是图书馆二楼。\n\n'
        source = hits[0].sections[0]
        assert source['headings'] == [['项目', '聚会']]
        assert content[source['start_char']:source['end_char']] == hits[0].preview
        assert source['source_version'] == hashlib.sha256(content.encode()).hexdigest()

        updated = '# 新安排\n\n## 聚会\n集合地点改成图书馆三楼。\n'
        await memory.write(SCENE, 'events/week.md', updated, '已确认更正')
        hit = (await memory.search(SCENE, '借阅空间在哪？', 1))[0]
        assert '三楼' in hit.preview and '二楼' not in hit.preview
        assert hit.sections[0]['source_version'] != source['source_version']
        with sqlite3.connect(memory.index) as db:
            assert db.execute('SELECT COUNT(*) FROM memory_sections').fetchone()[0] == 1
        assert await memory.reindex_embeddings() == 1
        assert '三楼' in (await memory.search(SCENE, '借阅空间在哪？', 1))[0].preview
        assert len(await memory.history(SCENE, 'events/week.md')) == 2
        await memory.delete(SCENE, 'events/week.md', '删除样本')
        assert not await memory.search(SCENE, '借阅空间在哪？')
        await memory.write(SCENE, 'events/week.md', updated, '重新记录')
        await memory.forget(SCENE, 'events/week.md')
        assert not await memory.search(SCENE, '借阅空间在哪？')
        assert not await memory.history(SCENE, 'events/week.md')
        with sqlite3.connect(memory.index) as db:
            db.enable_load_extension(True)
            import sqlite_vec
            sqlite_vec.load(db)
            assert db.execute('SELECT COUNT(*) FROM memory_vec').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_vectors_alone_keep_only_close_sections_and_show_their_latest_part(tmp_path):
    async with embeddings() as (client, _):
        binding = EmbeddingBinding(provider='sample', model='three-topics', dimensions=3)
        settings = LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=tmp_path / 'memory',
                                     embedding=binding), recall_budget_chars=300, recall_limit=5)
        memory = LocalMemory(settings.local, embedding=client)
        await memory.write(SCENE, 'events/meet.md', '# 聚会\n\n## 集合\n' + '大家先在门口等人到齐。' * 60
                           + '\n集合地点最后定在图书馆二楼。\n', '合成样本')
        await memory.write(SCENE, 'events/money.md', '# 账目\n\n## 开销\n预算还剩三百元。\n', '合成样本')
        # Orthogonal topics are a cosine distance of 1 apart: a question near neither finds nothing.
        assert await memory.search(SCENE, '火星飞船几点起飞', 5, automatic=True) == []
        assert [hit.path for hit in await memory.search(SCENE, '借阅空间在哪', 5, automatic=True)] == ['events/meet.md']
        with Store(tmp_path / 'chat.db') as store, MemoryJobs(tmp_path / 'jobs.db') as jobs:
            service = MemoryService(settings, memory, jobs=jobs, store=store, active_personas={})
            [item] = (await service.recall(SCENE, chat('借阅空间那边最后怎么定的')))['items']
        assert item['path'] == 'events/meet.md' and item['content'].rstrip().endswith('图书馆二楼。')


@pytest.mark.asyncio
async def test_text_sections_preserve_source_spelling_merge_ranges_and_scope(tmp_path):
    memory = LocalMemory(LocalMemorySettings(directory=tmp_path / 'memory'))
    content = ('首段事件。\n\n街区\n======\n\n## 同词甲\nStraße 甲在东门。\n\n'
               '## 同词乙\nStraße 乙在西门。\n\n## 其他\n第三节只谈天气。\n\n'
               '同词丙\n------\nStraße 丙在南门。\n')
    await memory.write(SCENE, 'events/streets.md', content, '合成大小写样本')
    await memory.write('onebot:group:80002', 'events/streets.md', 'Straße 跨群秘密。', '隔离')
    await memory.write(SCENE, 'bot/other/profile.md', 'Straße 其他角色秘密。', '隔离')
    await memory.owner_write_public('public.md', 'Straße 公共资料。', '公共资料')
    hits = await memory.search(SCENE, 'STRASSE', bot_persona='current')
    assert [(hit.scope, hit.path) for hit in hits] == [('scene', 'events/streets.md'), ('public', 'public.md')]
    assert '其他' not in hits[0].preview and 'Straße' in hits[0].preview
    ranges = hits[0].sections
    assert len(ranges) == 2 and ranges[0]['headings'] == [['街区', '同词甲'], ['街区', '同词乙']]
    assert '\n…\n'.join(content[part['start_char']:part['end_char']] for part in ranges) == hits[0].preview
    assert all(part['source_version'] == hashlib.sha256(content.encode()).hexdigest() for part in ranges)
    assert await memory.reindex_text() == 4
    assert (await memory.search(SCENE, 'STRASSE', include_public=False, bot_persona='current'))[0].preview == hits[0].preview
    await memory.write(SCENE, 'empty.md', '# 只有标题\n', '空内容')
    assert not await memory.search(SCENE, '只有标题')


@pytest.mark.asyncio
async def test_recall_budget_truncates_units_without_duplicate_sources(tmp_path):
    settings = LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=tmp_path / 'memory'),
                                 recall_budget_chars=300, recall_limit=10)
    memory = LocalMemory(settings.local)
    await memory.write(SCENE, 'events/week.md', '# 计划\n\n## 甲\n' + '读书会。' * 80 + '\n## 乙\n读书会在东门。', '合成样本')
    message = parse_message({'post_type': 'message', 'message_type': 'group', 'group_id': 80001,
        'user_id': 90001, 'self_id': 80000, 'message_id': 1, 'time': 1791060000,
        'sender': {'nickname': '提问者', 'role': 'member'},
        'message': [{'type': 'text', 'data': {'text': '读书会'}}]}, own_message_ids=set())
    with Store(tmp_path / 'chat.db') as store, MemoryJobs(tmp_path / 'jobs.db') as jobs:
        service = MemoryService(settings, memory, jobs=jobs, store=store, active_personas={})
        result = await service.recall(SCENE, [message])
        assert result['content_chars'] <= 300 and len(result['items']) == 1
        assert result['items'][0]['truncated'] and result['items'][0]['sections']
        # The excerpt ends on the later matching sentence instead of cutting the source from its head.
        content = result['items'][0]['content']
        assert content.startswith('## 甲\n…\n') and content.rstrip().endswith('读书会在东门。')


@pytest.mark.asyncio
async def test_recall_shares_the_budget_so_a_long_hit_leaves_room_for_the_next(tmp_path):
    settings = LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=tmp_path / 'memory'),
                                 recall_budget_chars=600, recall_limit=5)
    memory = LocalMemory(settings.local)
    await memory.write(SCENE, 'events/trip.md', '# 秋游\n\n' + '秋游路线先走山脚步道，中途在茶亭休息。' * 60
                       + '\n秋游集合时间最新改为周日早上七点半。\n', '合成样本')
    await memory.write(SCENE, 'events/potluck.md', '# 聚餐\n\n聚餐由阿杰订位。\n', '合成样本')
    messages = [parse_message({'post_type': 'message', 'message_type': 'group', 'group_id': 80001,
        'user_id': 90001, 'self_id': 80000, 'message_id': index, 'time': 1791060000,
        'sender': {'nickname': '提问者', 'role': 'member'},
        'message': [{'type': 'text', 'data': {'text': text}}]}, own_message_ids=set())
        for index, text in enumerate(['秋游集合时间最新是几点', '聚餐由谁订位'], 1)]
    with Store(tmp_path / 'chat.db') as store, MemoryJobs(tmp_path / 'jobs.db') as jobs:
        service = MemoryService(settings, memory, jobs=jobs, store=store, active_personas={})
        result = await service.recall(SCENE, messages)
    content = '\n'.join(item['content'] for item in result['items'])
    assert {item['path'] for item in result['items']} == {'events/trip.md', 'events/potluck.md'}
    assert '周日早上七点半' in content and '阿杰订位' in content
    assert result['content_chars'] <= 600


def chat(*texts):
    return [parse_message({'post_type': 'message', 'message_type': 'group', 'group_id': 80001,
        'user_id': 90001, 'self_id': 80000, 'message_id': index, 'time': 1791060000,
        'sender': {'nickname': '提问者', 'role': 'member'},
        'message': [{'type': 'text', 'data': {'text': text}}]}, own_message_ids=set())
        for index, text in enumerate(texts, 1)]


def test_query_fragments_stay_inside_one_line():
    terms, short = query_terms('读书会的安排\n接着说 地点\n好')
    assert '安排\n' not in terms and '排\n接' not in terms and '说 地' in terms and ' 地点' not in terms
    assert short == ['好'] and evidence('## 安排\n秋游路线', '读书会的安排\n接着说') == 0


@pytest.mark.asyncio
async def test_text_recall_shows_a_section_sharing_little_wording_only_around_it(tmp_path):
    settings = LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=tmp_path / 'memory'),
                                 recall_budget_chars=1500, recall_limit=5)
    memory = LocalMemory(settings.local)
    await memory.write(SCENE, 'events/trip.md', '# 秋游\n\n## 安排\n' + '秋游路线先走山脚步道，中途在茶亭休息。' * 80
                       + '\n秋游集合时间最新改为周日早上七点半。\n', '合成样本')
    await memory.write(SCENE, 'events/week.md', '# 读书会\n\n读书会最终地点是图书馆二楼。\n', '合成样本')
    with Store(tmp_path / 'chat.db') as store, MemoryJobs(tmp_path / 'jobs.db') as jobs:
        service = MemoryService(settings, memory, jobs=jobs, store=store, active_personas={})
        # Two messages joined by a line break do not match the heading line followed by the route.
        follow = await service.recall(SCENE, chat('读书会的安排', '接着说地点'))
        assert [item['path'] for item in follow['items']] == ['events/week.md']
        # One shared fragment (游集合) shows the trip around it, not the whole budget.
        loose = await service.recall(SCENE, chat('南门出游集合'))
        assert [item['path'] for item in loose['items']] == ['events/trip.md']
        assert loose['content_chars'] <= 200 and '游集合' in loose['items'][0]['content']


@pytest.mark.asyncio
async def test_recap_promises_lead_recall_to_what_the_chat_no_longer_names(tmp_path):
    settings = LocalMemoryConfig(backend='local', local=LocalMemorySettings(directory=tmp_path / 'memory'),
                                 recall_budget_chars=1500, recall_limit=5)
    memory = LocalMemory(settings.local)
    await memory.write(SCENE, 'events/books.md', '# 十一月书单\n\n十一月书单定了《小王子》和《夜航西飞》。\n', '合成样本')
    await memory.write(SCENE, 'events/trip.md', '# 秋游\n\n秋游集合时间是周日早上七点半。\n', '合成样本')
    recap = ('## 话题脉络\n- 秋游安排\n\n## 我答应的事\n- 周五前把十一月书单发到群里\n\n'
             '## 没回答的问题\n- 小林问借书证怎么办\n\n## 关键原话\n- 秋游别迟到\n')
    cues = recall_cues(recap)
    assert cues == '周五前把十一月书单发到群里\n小林问借书证怎么办' and recall_cues(None) == ''
    with Store(tmp_path / 'chat.db') as store, MemoryJobs(tmp_path / 'jobs.db') as jobs:
        service = MemoryService(settings, memory, jobs=jobs, store=store, active_personas={})
        assert (await service.recall(SCENE, chat('那个弄好了没')))['items'] == []
        found = await service.recall(SCENE, chat('那个弄好了没'), cues)
        assert [item['path'] for item in found['items']] == ['events/books.md'] and found['cues'] == cues
        # The chat's own hits come first; a cue hit already shown is not repeated.
        both = await service.recall(SCENE, chat('秋游集合时间是几点'), cues)
        assert [item['path'] for item in both['items']] == ['events/trip.md', 'events/books.md']


@pytest.mark.asyncio
async def test_external_casefold_equivalent_edit_requires_reindex_before_using_offsets(tmp_path):
    memory = LocalMemory(LocalMemorySettings(directory=tmp_path / 'memory'))
    path = 'events/strasse.md'
    await memory.write(SCENE, path, '# Straße\n\n## 地址\nStraße 在东门。\n', '合成样本')
    target = memory.root / 'scenes' / SCENE / path
    target.write_text('# STRASSE\n\n## 地址\nSTRASSE 在东门。\n')
    with pytest.raises(ValueError, match='Markdown/index mismatch'):
        await memory.search(SCENE, 'STRASSE')
    assert await memory.reindex_text() == 1
    hit = (await memory.search(SCENE, 'STRASSE'))[0]
    source = hit.sections[0]
    assert target.read_text()[source['start_char']:source['end_char']] == hit.preview


@pytest.mark.asyncio
async def test_turn_detail_http_keeps_actual_recalled_section_sources(tmp_path):
    def configure(root):
        path = root / 'lenbot.config.json'
        source = json.loads(path.read_text())
        source['memory'] = {'backend': 'local', 'local': {'directory': str(root / 'memory')}}
        path.write_text(json.dumps(source))

    async with panel(tmp_path, configure) as (runtime, client, _):
        await login(client)
        content = '# 记录\n\n## 会场\n读书会在图书馆二楼。\n'
        await runtime.memory.write(SCENE, 'events/meeting.md', content, '合成协议样本')
        message = parse_message({'post_type': 'message', 'message_type': 'group', 'group_id': 80001,
            'user_id': 90001, 'self_id': 80000, 'message_id': 1, 'time': 1791060000,
            'sender': {'nickname': '提问者', 'role': 'member'},
            'message': [{'type': 'text', 'data': {'text': '读书会在哪里？'}}]}, own_message_ids=set())
        recall = await runtime.memory.recall(SCENE, [message])
        turn = runtime.store.start_turn(SCENE)
        call = runtime.store.start_call(turn, 'mind', {'messages': [], 'recall_items': recall['items']})
        runtime.store.end_call(call, {'message': {'role': 'assistant', 'content': '好'}}, None, model=('fixture', 'fixture-model'))
        runtime.store.end_turn(turn, 'settled')
        response = await client.get(f'/api/host/scenes/{SCENE}/turns/{turn}')
        assert response.status_code == 200, response.text
        recalled = response.json()['recall'][0]
        assert recalled['content'] == '## 会场\n读书会在图书馆二楼。\n'
        assert recalled['sections'][0]['headings'] == [['记录', '会场']]
        assert recalled['sections'][0]['source_version'] == hashlib.sha256(content.encode()).hexdigest()
