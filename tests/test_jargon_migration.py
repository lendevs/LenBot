"""The published business format upgrades without changing manual meanings or source records."""
from contextlib import closing
import sqlite3

from len_bot.next.maintenance.upgrade import migrate_business_database
from len_bot.next.learning.jargon_store import JargonStore
from len_bot.next.storage.schema import business_script
from len_bot.next.storage.store import Store


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
