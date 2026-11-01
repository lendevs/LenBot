"""The community catalog check compares entries with the pinned repository contents."""

import importlib.util
import json
from pathlib import Path
import subprocess

from len_bot.next.plugins.catalog import parse_index

TEMPLATE = Path(__file__).parent / 'fixtures/plugins/sample/plugin.toml'
SPEC = importlib.util.spec_from_file_location('check_plugin_catalog',
                                              Path(__file__).parents[1] / 'scripts/check_plugin_catalog.py')
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)
check_checkout, main = script.check_checkout, script.main


def entry(**changes):
    value = {'name': 'sample', 'title': '示例', 'description': '示例插件', 'authors': ['作者'],
             'license': 'AGPL-3.0-only', 'version': '1.0.0', 'interface': 1, 'category': '工具',
             'install': 'git', 'repository': 'https://example.invalid/author/sample.git', 'ref': 'a' * 40}
    value.update(changes)
    return parse_index(json.dumps({'version': 1, 'entries': [value]}).encode(), 'test').entries[0]


def checkout(tmp_path, *, manifest_extra='', files=('__init__.py', 'LICENSE')):
    root = tmp_path / 'checkout'
    root.mkdir()
    (root / 'plugin.toml').write_text(TEMPLATE.read_text().replace('interface = 1\n', 'interface = 1\n' + manifest_extra, 1))
    for name in files:
        (root / name).write_text('')
    return root


def test_matching_entry_and_repository_pass(tmp_path):
    root = checkout(tmp_path, manifest_extra='permissions = ["send"]\n')
    assert check_checkout(entry(permissions=['send'], requires_lenbot='>=0.2,<1'), root) == []


def test_differences_and_missing_files_are_reported(tmp_path):
    root = checkout(tmp_path, files=())
    problems = check_checkout(entry(version='1.0.1', permissions=['send']), root)
    assert problems == ["version 在条目中是 '1.0.1'，plugin.toml 是 '1.0.0'",
                        '条目写了 permissions，plugin.toml 没有声明',
                        '仓库根目录没有 __init__.py',
                        '仓库根目录没有许可证文件（LICENSE、LICENSE.md、LICENSE.txt、COPYING）']


def test_entries_must_pin_a_full_commit(tmp_path, capsys):
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'version': 1, 'entries': [
        {**json.loads(entry().model_dump_json(exclude_none=True)), 'ref': 'v1.0.0'}]}))
    assert main([str(catalog)]) == 1
    assert 'ref 必须是完整的 40 位提交号' in capsys.readouterr().out


def test_a_pinned_local_repository_is_fetched_and_checked(tmp_path, capsys, monkeypatch):
    root = checkout(tmp_path)
    for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                                                 'commit', '-qm', 'init']):
        subprocess.run(['git', '-C', str(root), *args], check=True)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    pinned = entry(ref=commit)
    # Catalog repositories are URLs; a file URL stands in for the remote here.
    monkeypatch.setattr(script, 'parse_index',
                        lambda raw, source: type('Index', (), {'entries': [pinned.model_copy(
                            update={'repository': root.as_uri()})]})())
    catalog = tmp_path / 'catalog.json'
    catalog.write_text('{}')
    assert main([str(catalog)]) == 0
    assert 'sample 1.0.0：通过' in capsys.readouterr().out
