"""Check a plugin catalog JSON against each entry's repository at its pinned commit.

    uv run --no-sync python scripts/check_plugin_catalog.py catalog.json [--only NAME ...]

The catalog uses the built-in catalog's format. Every entry pins ``ref`` to a full commit;
the script fetches that commit into a temporary directory and checks that ``plugin.toml``
is a valid manifest whose name, version, interface and declared permissions match the
entry, and that the package has ``__init__.py`` and a license file. Plugin code is never
imported or run. Exits 1 when any entry fails.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from packaging.specifiers import SpecifierSet

from len_bot.next.plugins.catalog import CatalogEntry, parse_index
from len_bot.next.plugins.manifest import parse_manifest

LICENSE_FILES = ('LICENSE', 'LICENSE.md', 'LICENSE.txt', 'COPYING')


def check_checkout(entry: CatalogEntry, checkout: Path) -> list[str]:
    """Problems between one entry and its repository contents; empty when they agree."""
    if not (checkout / 'plugin.toml').is_file():
        return ['仓库根目录没有 plugin.toml']
    try:
        manifest = parse_manifest(checkout / 'plugin.toml')
    except ValueError as error:
        return [f'plugin.toml 无效：{error}']
    problems = [f'{field} 在条目中是 {getattr(entry, field)!r}，plugin.toml 是 {getattr(manifest, field)!r}'
                for field in ('name', 'version', 'interface') if getattr(entry, field) != getattr(manifest, field)]
    if entry.permissions is not None:
        if manifest.permissions is None:
            problems.append('条目写了 permissions，plugin.toml 没有声明')
        elif sorted(entry.permissions) != sorted(manifest.permissions):
            problems.append(f'permissions 在条目中是 {entry.permissions!r}，plugin.toml 是 {manifest.permissions!r}')
    if entry.requires_lenbot is not None and entry.requires_lenbot != str(SpecifierSet(manifest.requires_lenbot)):
        problems.append(f'requires_lenbot 在条目中是 {entry.requires_lenbot!r}，plugin.toml 是 {manifest.requires_lenbot!r}')
    if not (checkout / '__init__.py').is_file():
        problems.append('仓库根目录没有 __init__.py')
    if not any((checkout / name).is_file() for name in LICENSE_FILES):
        problems.append('仓库根目录没有许可证文件（' + '、'.join(LICENSE_FILES) + '）')
    return problems


def fetch(entry: CatalogEntry, directory: Path) -> None:
    subprocess.run(['git', 'init', '--quiet', str(directory)], check=True)
    for args in (['fetch', '--quiet', '--depth', '1', '--', entry.repository, entry.ref],
                 ['checkout', '--quiet', 'FETCH_HEAD']):
        result = subprocess.run(['git', '-C', str(directory), *args], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'git {args[0]} 失败：{result.stderr.strip()}')


def check_entry(entry: CatalogEntry) -> list[str]:
    if entry.ref is None or re.fullmatch(r'[0-9a-f]{40}', entry.ref) is None:
        return [f'ref 必须是完整的 40 位提交号，实际为 {entry.ref!r}']
    with tempfile.TemporaryDirectory(prefix='lenbot-catalog-') as root:
        try:
            fetch(entry, Path(root) / 'checkout')
        except RuntimeError as error:
            return [f'取不到 {entry.repository} 的提交 {entry.ref}：{error}']
        return check_checkout(entry, Path(root) / 'checkout')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('catalog', type=Path)
    parser.add_argument('--only', nargs='+', metavar='NAME', help='只检查这些插件')
    options = parser.parse_args(argv)
    index = parse_index(options.catalog.read_bytes(), str(options.catalog))
    entries = [entry for entry in index.entries if options.only is None or entry.name in options.only]
    missing = set(options.only or ()) - {entry.name for entry in entries}
    if missing:
        print('目录中没有：' + '、'.join(sorted(missing)), file=sys.stderr)
        return 1
    failed = 0
    for entry in entries:
        problems = check_entry(entry)
        if problems:
            failed += 1
            print(f'{entry.name}：不通过')
            for problem in problems:
                print(f'  - {problem}')
        else:
            print(f'{entry.name} {entry.version}：通过')
    print(f'检查 {len(entries)} 项，{failed} 项不通过')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
