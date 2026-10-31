"""A persistent structure that changed under an unchanged format number fails here, before a release carries it."""
from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from len_bot.next import config as root_config
from len_bot.next.memory import jobs, local
from len_bot.next.plugins import kv
from len_bot.next.storage import schema, store

# Fingerprints per format number. From the first RC on, a structure change comes with a new number, an upgrade
# step in ``maintenance/upgrade.py`` and a new entry here, and the entry of a released number stays as it is.
# Until then the numbers stay at 1 and the entry of 1 is replaced together with the structure change.
EXPECTED = {
    'root_config': {1: '47350ef9b94d2f15008cf7a1ed8131014398ce0bd7552bea9ec28fd6b499451a'},
    'business': {1: 'b214769fd5591fa83037f0c29331f6f60853b1fc674f82d06a3bbcbf11e06b80'},
    'memory_jobs': {1: 'ee52e1599807d9cc2e5191d2dee75d18c740ca80a6f0960fe7ec4c5479814151'},
    'local_memory_index': {1: '18837e0b06ca13a8d74f2ebe4fc9ea7377c401f15dc26bf31b8d03a107b7b8f1'},
    'plugin_kv': {1: 'bdf97df854e3bb90efd78dfd3e7c342a9729ea1f69931a88e191d54c64cdd56a'},
}
NUMBERS = {
    'root_config': root_config.CONFIG_VERSION,
    'business': store.FORMAT_VERSION,
    'memory_jobs': jobs.FORMAT_VERSION,
    'local_memory_index': local.FORMAT_VERSION,
    'plugin_kv': kv.FORMAT_VERSION,
}
SCHEMA_TEXT = {
    'business': schema.business_script,
    'memory_jobs': lambda: jobs.SCHEMA,
    'local_memory_index': lambda: local.INDEX_SCHEMA,
    'plugin_kv': lambda: kv.SCHEMA,
}
_DESCRIPTIVE = {'default', 'title', 'description', 'examples'}


def _sql_fingerprint(script: str) -> str:
    """Every table and index statement as SQLite stored it, spacing removed and sorted."""
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(script)
        statements = sorted((kind, name, ' '.join(sql.split())) for kind, name, sql in db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
    return hashlib.sha256(json.dumps(statements, ensure_ascii=False).encode()).hexdigest()


def _structure(node, *, field_names: bool = False):
    """The JSON schema of the root model without defaults and descriptions (a field named ``default`` stays).

    The field lists under ``required`` are sorted, so reordering the declarations changes nothing.
    """
    if isinstance(node, dict):
        return {key: sorted(value) if key == 'required' else _structure(value, field_names=key == 'properties')
                for key, value in node.items() if field_names or key not in _DESCRIPTIVE}
    if isinstance(node, list):
        return [_structure(value) for value in node]
    return node


def _config_fingerprint() -> str:
    structure = _structure(root_config.HostConfig.model_json_schema())
    return hashlib.sha256(json.dumps(structure, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _actual() -> dict[str, str]:
    return {'root_config': _config_fingerprint(),
            **{name: _sql_fingerprint(text()) for name, text in SCHEMA_TEXT.items()}}


@pytest.mark.parametrize('name', sorted(EXPECTED))
def test_a_structure_change_comes_with_a_new_format_number(name):
    number, actual = NUMBERS[name], _actual()[name]
    recorded = EXPECTED[name].get(number)
    assert recorded is not None, (
        f'{name} 的格式编号是 {number}，但没有记录它的结构指纹。递增编号后，在 EXPECTED 中补上 {number}: {actual!r}。')
    assert actual == recorded, (
        f'{name} 的结构变了，但格式编号 {number} 没有变。需要递增格式编号，并在 maintenance/upgrade.py 补从上一版本的迁移；'
        f'编号递增后，在 EXPECTED 中为新编号记录 {actual!r}。')
