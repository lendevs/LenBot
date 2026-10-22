"""Section retrieval across embedding HTTP, source edits and offline index upgrades."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from len_bot.next.maintenance.migrate_local_memory import migrate
from len_bot.next.memory.embeddings import EmbeddingBinding, EmbeddingClient, EmbeddingSettings
from len_bot.next.memory.local import FORMAT_VERSION, LocalMemory, LocalMemorySettings
from len_bot.next.memory.jobs import MemoryJobs
from len_bot.next.memory.service import LocalMemoryConfig, MemoryService
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
async def test_text_sections_preserve_source_spelling_merge_ranges_and_scope(tmp_path):
    memory = LocalMemory(LocalMemorySettings(directory=tmp_path / 'memory'))
    content = ('首段事件。\n\n街区\n======\n\n## 同词甲\nStraße 甲在东门。\n\n'
               '## 同词乙\nStraße 乙在西门。\n\n## 其他\n第三节只谈天气。\n\n'
               '同词丙\n------\nStraße 丙在南门。\n')
    await memory.write(SCENE, 'events/streets.md', content, '合成大小写样本')
    await memory.write('onebot:group:80002', 'events/streets.md', 'Straße 跨群秘密。', '隔离')
    await memory.write(SCENE, 'bot/other/profile.md', 'Straße 其他角色秘密。', '隔离')
    await memory.write(SCENE, 'legacy-import/pending.md', 'Straße 待采用秘密。', '隔离')
    await memory.owner_write_public('public.md', 'Straße 公共资料。', '公共资料')
    hits = await memory.search(SCENE, 'STRASSE', bot_persona='current', exclude_pending=True)
    assert [(hit.scope, hit.path) for hit in hits] == [('scene', 'events/streets.md'), ('public', 'public.md')]
    assert '其他' not in hits[0].preview and 'Straße' in hits[0].preview
    ranges = hits[0].sections
    assert len(ranges) == 2 and ranges[0]['headings'] == [['街区', '同词甲'], ['街区', '同词乙']]
    assert '\n…\n'.join(content[part['start_char']:part['end_char']] for part in ranges) == hits[0].preview
    assert all(part['source_version'] == hashlib.sha256(content.encode()).hexdigest() for part in ranges)
    assert await memory.reindex_text() == 5
    assert (await memory.search(SCENE, 'STRASSE', include_public=False, bot_persona='current', exclude_pending=True))[0].preview == hits[0].preview
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
        assert result['content_chars'] == 300 and len(result['items']) == 1
        assert result['items'][0]['truncated'] and result['items'][0]['sections']


@pytest.mark.asyncio
@pytest.mark.parametrize('vectors', [False, True])
async def test_format_three_migration_builds_units_without_rewriting_sources(tmp_path, vectors):
    fixture = Path(__file__).parent / 'fixtures/history/config0-business7-jobs6-index3/memory'
    root = tmp_path / 'memory'
    shutil.copytree(fixture, root)
    content = '# 记忆\n\n## 约定\n周六交报告。\n'
    # Extend a genuine format-3 fixture using its table/FTS contract.
    target = root / 'scenes' / SCENE / 'events/week.md'
    target.parent.mkdir(parents=True)
    target.write_text(content)
    index = root / '.memory-index.sqlite3'
    with sqlite3.connect(index) as db:
        rowid = db.execute('INSERT INTO memory_files(scope,path,content) VALUES(?,?,?)',
                           (SCENE, 'events/week.md', content.casefold())).lastrowid
        db.execute('INSERT INTO memory_fts(rowid,content) VALUES(?,?)', (rowid, content.casefold()))
        db.execute("INSERT INTO memory_changes(scope,path,changed_at,action,reason,after) VALUES(?,?,1,'write','样本',?)",
                   (SCENE, 'events/week.md', content))
        if vectors:
            import sqlite_vec
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.execute('CREATE VIRTUAL TABLE memory_vec USING vec0(embedding float[3] distance_metric=cosine, scope text)')
            db.execute('INSERT INTO memory_vec(rowid,embedding,scope) VALUES(?,?,?)',
                       (rowid, sqlite_vec.serialize_float32([1., 0., 0.]), SCENE))
            db.execute("INSERT INTO memory_vector_binding VALUES(1,'sample','http://127.0.0.1:9/v1','three-topics',3)")
    with pytest.raises(ValueError, match='format 3 requires offline migration'):
        LocalMemory(LocalMemorySettings(directory=root))
    backup = migrate(root)
    assert backup == index.with_name(index.name + '.v3.bak')
    with sqlite3.connect(index) as db, sqlite3.connect(backup) as old:
        assert db.execute('PRAGMA user_version').fetchone()[0] == FORMAT_VERSION
        assert old.execute('PRAGMA user_version').fetchone()[0] == 3
        assert db.execute('SELECT * FROM memory_changes').fetchall() == old.execute('SELECT * FROM memory_changes').fetchall()
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_vec'").fetchone()
        assert db.execute('SELECT COUNT(*) FROM memory_vector_binding').fetchone()[0] == 0
    memory = LocalMemory(LocalMemorySettings(directory=root))
    hit = (await memory.search(SCENE, '周六'))[0]
    assert hit.preview == '## 约定\n周六交报告。\n'
    assert target.read_bytes() == content.encode()
    assert migrate(root) is None


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
        runtime.store.end_call(call, {'message': {'role': 'assistant', 'content': '好'}}, None)
        runtime.store.end_turn(turn, 'settled')
        response = await client.get(f'/api/host/scenes/{SCENE}/turns/{turn}')
        assert response.status_code == 200, response.text
        recalled = response.json()['recall'][0]
        assert recalled['content'] == '## 会场\n读书会在图书馆二楼。\n'
        assert recalled['sections'][0]['headings'] == [['记录', '会场']]
        assert recalled['sections'][0]['source_version'] == hashlib.sha256(content.encode()).hexdigest()
