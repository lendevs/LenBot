"""The published business format upgrades without changing manual meanings or source records."""
from contextlib import closing
import sqlite3

from len_bot.next.maintenance.upgrade import migrate_business_database
from len_bot.next.learning.jargon_store import JargonStore
from len_bot.next.storage.schema import business_script
from len_bot.next.storage.store import FORMAT_VERSION, Store


def test_current_format_upgrade_restores_missing_message_time_indexes(tmp_path):
    path = tmp_path / 'business.db'
    with Store(path):
        pass
    with closing(sqlite3.connect(path)) as db:
        db.execute('DROP INDEX message_scene_time')
        db.execute('DROP INDEX message_sender_time')
    assert migrate_business_database(path)
    assert not migrate_business_database(path)
    with closing(sqlite3.connect(path)) as db:
        indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {'message_scene_time', 'message_sender_time'} <= indexes
        plan = list(db.execute(
            "EXPLAIN QUERY PLAN SELECT seq,body FROM messages WHERE scene=? AND +seq<=? "
            "AND json_extract(body,'$.time')>=? AND json_extract(body,'$.time')<? "
            "ORDER BY json_extract(body,'$.time'),seq LIMIT 500", ('test:group:1', 1000, 0, 100)))
        assert any('message_scene_time' in row[3] for row in plan)
        assert all('TEMP B-TREE' not in row[3] for row in plan)



def test_format_2_upgrade_builds_the_mind_usage_index(tmp_path):
    path = tmp_path / 'business.db'
    index = 'CREATE INDEX model_call_mind_usage ON model_calls(scene,role,id) WHERE plugin IS NULL;\n'
    assert index in business_script()
    with closing(sqlite3.connect(path)) as db:
        db.executescript('PRAGMA application_id=1279413809; PRAGMA user_version=2;\n'
                         + business_script().replace(index, ''))
        with db:
            for request, plugin in (('{"from": "chat"}', None), ('{"from": "plugin"}', 'group_digest')):
                db.execute("INSERT INTO model_calls(role,started,ended,request,usage,scene,plugin) "
                           "VALUES ('mind',1,2,?,'{}','test:group:1',?)", (request, plugin))
    assert migrate_business_database(path)
    assert not migrate_business_database(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == FORMAT_VERSION
        plan = [row[3] for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT request FROM model_calls WHERE scene=? AND role='mind' "
            "AND plugin IS NULL ORDER BY id DESC LIMIT 1", ('test:group:1',))]
        assert any('USING INDEX model_call_mind_usage' in step for step in plan), plan
    with Store(path) as store:
        assert store.last_mind_usage('test:group:1') == ({'from': 'chat'}, {})


def test_format_3_upgrade_builds_format_4_indexes(tmp_path):
    path = tmp_path / 'business.db'
    new_indexes = (
        'CREATE INDEX notices_scene_received ON notices(scene,received_at,id);\n',
        "CREATE INDEX scene_group_bans ON notices(scene,time,id) WHERE kind='group_ban';\n",
        'CREATE INDEX message_scene_seq ON messages(scene,seq);\n',
        'CREATE INDEX message_scene_received ON messages(scene,received_at,seq)\n    WHERE raw IS NOT NULL AND received_at IS NOT NULL;\n',
        'CREATE INDEX model_call_plugin ON model_calls(plugin,id) WHERE plugin IS NOT NULL;\n',
        'CREATE INDEX turns_started ON turns(started,scene,id);\n',
        'CREATE INDEX plugin_events_scene ON plugin_events(scene,id);\n',
    )
    script = business_script()
    for statement in new_indexes:
        assert statement in script, statement
        script = script.replace(statement, '')
    with closing(sqlite3.connect(path)) as db:
        db.executescript('PRAGMA application_id=1279413809; PRAGMA user_version=3;\n' + script)
    assert migrate_business_database(path)
    assert not migrate_business_database(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == FORMAT_VERSION
        indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {'notices_scene_received', 'scene_group_bans', 'message_scene_seq',
                'message_scene_received', 'model_call_plugin', 'turns_started', 'plugin_events_scene'} <= indexes

def test_jargon_upgrade_preserves_manual_controls_and_queues_old_records(tmp_path):
    path = tmp_path / 'business.db'
    old = business_script().replace('    judgment TEXT, last_evaluated_seq INTEGER NOT NULL DEFAULT 0,\n', '')
    with closing(sqlite3.connect(path)) as db:
        db.executescript('PRAGMA application_id=1279413809; PRAGMA user_version=1;\n' + old)
        with db:
            for term, status, meaning in [('自动', 'pending', None), ('固定', 'adopted', '人工解释'),
                                           ('禁用', 'rejected', None)]:
                db.execute('INSERT INTO jargon(scene,term,count,sample_seqs,latest_meaning,meaning,status,updated) '
                           'VALUES (?,?,8,?,\'旧自动解释\',?,?,1)', ('test:group:1', term, '[3,5]', meaning, status))
    assert migrate_business_database(path)
    assert not migrate_business_database(path)
    with Store(path) as store:
        jargon = JargonStore(store)
        items = {item['term']: item for item in jargon.items('test:group:1', None, 20, 0)['items']}
        assert (items['固定']['status'], items['固定']['meaning']) == ('adopted', '人工解释')
        assert items['禁用']['status'] == 'rejected'
        assert all(item['sample_seqs'] == [3, 5] and item['latest_meaning'] == '旧自动解释' for item in items.values())
        assert all(item['classification'] == 'uncertain' for item in items.values())
        assert len(jargon.pending('test:group:1')) == 3
        assert [item['term'] for item in jargon.matches('test:group:1', ['自动 固定 禁用'])] == ['固定']
