"""Install two real wheel versions and exercise the native update HTTP protocol and snapshot restore."""

import argparse
from http.cookiejar import CookieJar
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
import zipfile

from build_deployment import build_deployments
from release_metadata import write_manifest
from smoke_install import check_panel, request, smoke_package

ROOT = Path(__file__).resolve().parents[1]


def baseline(artifacts: Path, work: Path, *, version: str = '0.0.0', broken: bool = False) -> Path:
    prefix = 'broken' if broken else 'baseline'
    project = work / (prefix + '-source')
    source = project / 'src'
    source.mkdir(parents=True)
    wheel, = artifacts.glob('*.whl')
    with zipfile.ZipFile(wheel) as package:
        for name in package.namelist():
            if name.startswith('len_bot/'):
                package.extract(name, source)
    for name in ('pyproject.toml', 'README.md', 'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, project / name)
    config = (project / 'pyproject.toml').read_text(encoding='utf-8')
    current = tomllib.loads(config)['project']['version']
    (project / 'pyproject.toml').write_text(config.replace(f'version = "{current}"', f'version = "{version}"', 1), encoding='utf-8')
    if broken:
        host = source / 'len_bot/next/host.py'
        text = host.read_text(encoding='utf-8')
        assert 'import asyncio' in text
        host.write_text(text.replace('import asyncio',
            'raise RuntimeError("synthetic startup failure")\nimport asyncio', 1), encoding='utf-8')
    output = work / (prefix + '-artifacts')
    output.mkdir()
    subprocess.run(['uv', 'build', '--wheel', '--out-dir', str(output)], cwd=project, check=True)
    old_wheel, = output.glob('*.whl')
    requirements = output / 'requirements.txt'
    shutil.copy2(artifacts / 'requirements.txt', requirements)
    build_deployments(old_wheel, ROOT, output, requirements)
    write_manifest(project, output, revision='synthetic-upgrade-fixture')
    return output


def next_patch(artifacts: Path) -> str:
    """The version after the built release; the synthetic broken release takes it."""
    version = json.loads((artifacts / 'release-manifest.json').read_text(encoding='utf-8'))['version']
    major, minor, patch = map(int, re.match(r'(\d+)\.(\d+)\.(\d+)', version).groups())
    return f'{major}.{minor}.{patch + 1}'


def run(artifacts: Path, work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=False)
    old = baseline(artifacts, work)
    installed = smoke_package(old, work / 'installed')
    root = Path(installed['root'])
    fixture = work / 'release-server'
    shutil.copytree(artifacts, fixture)
    manifest = json.loads((fixture / 'release-manifest.json').read_text(encoding='utf-8'))
    broken = baseline(artifacts, work, version=next_patch(artifacts), broken=True)
    broken_manifest = json.loads((broken / 'release-manifest.json').read_text(encoding='utf-8'))
    shutil.copytree(broken, fixture / 'broken')
    # The real HTTP fixture serves the actual built package, including its original checksums.
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(fixture), **kwargs)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    address = f'http://127.0.0.1:{http.server_port}'
    available = [{'tag_name': manifest['tag'], 'draft': False,
        'prerelease': manifest['prerelease'], 'body': 'Synthetic candidate update; no public release.',
        'assets': [{'name': file.name, 'browser_download_url': address + '/' + file.name}
                   for file in fixture.iterdir() if file.is_file() and file.name != 'releases']},
        {'tag_name': broken_manifest['tag'], 'draft': False, 'prerelease': False,
         'body': 'Synthetic version that fails during startup.',
         'assets': [{'name': file.name, 'browser_download_url': address + '/broken/' + file.name}
                    for file in broken.iterdir() if file.is_file()]}]
    (fixture / 'releases').write_text(json.dumps(available), encoding='utf-8')
    deployment = json.loads((root / 'deployment.json').read_text(encoding='utf-8'))
    deployment['release_api'] = address + '/releases'
    (root / 'deployment.json').write_text(json.dumps(deployment), encoding='utf-8')
    config = json.loads((root / 'instance/lenbot.config.json').read_text(encoding='utf-8'))
    panel_port = config['panel']['port']
    marker = root / 'instance/upgrade-fixture.txt'
    marker.write_text('before upgrade', encoding='utf-8')
    command = [str(root / 'control/.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')),
               '-X', 'utf8', str(root / 'control/code/controller.py'), str(root)]
    with (work / 'controller.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=sys.platform != 'win32',
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0)
        try:
            check_panel(panel_port, 'smoke', 'smoke-password', lambda: process.poll() is None)
            reference = json.loads((root / 'instance/.runtime/update-control.json').read_text(encoding='utf-8'))
            headers = {'Authorization': 'Bearer ' + reference['token']}
            opener = __import__('urllib.request', fromlist=['build_opener']).build_opener()
            def status():
                code, text = request(opener, reference['endpoint'] + '/api/status', headers=headers)
                assert code == 200, text
                return json.loads(text)
            def finish(expected: str):
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    value = status()
                    if value['status'] == expected:
                        return value
                    if value['status'] == 'failed' and expected != 'failed':
                        raise RuntimeError(value['error'] + '\n' + (root / 'updates/updater.jsonl').read_text(encoding='utf-8')[-4000:]
                                           + '\n' + (root / 'updates/updater.log').read_text(encoding='utf-8')[-4000:])
                    if expected == 'failed' and value['status'] == 'complete':
                        raise AssertionError('The synthetic broken release unexpectedly started successfully')
                    time.sleep(0.25)
                raise TimeoutError(status())
            def action(name: str, body: dict):
                code, text = request(opener, reference['endpoint'] + '/api/' + name, body=body, headers=headers)
                assert code == 202, text
            code, _ = request(opener, reference['endpoint'] + '/api/status')
            assert code == 401
            action('prepare', {'tag': manifest['tag']})
            finish('prepared')
            action('apply', {})
            updated = finish('complete')
            assert updated['current_version'] == manifest['version']
            marker.write_text('after upgrade', encoding='utf-8')
            action('restore', {})
            restored = finish('restored')
            assert restored['current_version'] == '0.0.0'
            assert marker.read_text(encoding='utf-8') == 'before upgrade'
            action('start', {})
            finish('complete')
            check_panel(panel_port, 'smoke', 'smoke-password', lambda: process.poll() is None)
            action('prepare', {'tag': broken_manifest['tag']})
            finish('prepared')
            action('apply', {})
            # The broken release does not start; the updater restores the snapshot and starts 0.0.0 by itself.
            rolled = finish('rolled_back')
            assert rolled['current_version'] == '0.0.0' and not rolled['stopped'] and rolled['actions'] == ['prepare']
            assert 'exited' in rolled['error'] and rolled['rolled_back_from'] == broken_manifest['version']
            assert marker.read_text(encoding='utf-8') == 'before upgrade'
            check_panel(panel_port, 'smoke', 'smoke-password', lambda: process.poll() is None)
            # Both updates left a snapshot; the panel lists them through the controller and deletes the older one.
            panel = f'http://127.0.0.1:{panel_port}'
            session = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
            code, text = request(session, panel + '/api/auth/login', body={'username': 'smoke', 'password': 'smoke-password'})
            assert code == 200, text
            code, text = request(session, panel + '/api/host/updates/snapshots')
            assert code == 200, text
            snapshots = json.loads(text)
            assert len(snapshots) == 2 and all(item['complete'] and item['bytes'] > 0 and not item['restore']
                                               for item in snapshots), snapshots
            removal = urllib.request.Request(panel + '/api/host/updates/snapshots/' + snapshots[1]['name'], method='DELETE')
            with session.open(removal, timeout=60) as response:
                assert [item['name'] for item in json.loads(response.read())] == [snapshots[0]['name']]
            assert not (root / 'backups' / snapshots[1]['name']).exists() and (root / 'backups' / snapshots[0]['name']).is_dir()
            return {'baseline': '0.0.0', 'target': manifest['version'], 'installed': True,
                    'upgrade': 'ready', 'restore': 'data and old program restored', 'restart': 'ready',
                    'startup_failure': 'rolled back to the previous program automatically', 'failed_update_rollback': 'ready',
                    'snapshots': 'listed and the older one deleted from the panel'}
        finally:
            process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM)
            process.wait(timeout=190)
            http.shutdown()
            http.server_close()
            thread.join()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('work', type=Path)
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--broken-only', action='store_true', help='Only build the next patch version that fails during startup')
    args = parser.parse_args()
    if args.baseline_only or args.broken_only:
        args.work.mkdir(parents=True, exist_ok=False)
        artifacts = args.artifacts.resolve()
        print(baseline(artifacts, args.work.resolve()) if args.baseline_only
              else baseline(artifacts, args.work.resolve(), version=next_patch(artifacts), broken=True))
    else:
        print(json.dumps(run(args.artifacts.resolve(), args.work.resolve()), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
