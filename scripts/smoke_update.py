"""Update a deployment from the panel end to end: the launcher, the version switch, readiness and rollback.

The current wheel is installed as version A in a deployment package layout, with a virtual environment in
place of the packaged Python. Copies relabelled A.post1 and A.post2 (whose host exits at start) are served
as releases in GitHub's list format. After first setup the script, through the panel API only:

1. updates to A.post1: snapshot, migration, start and readiness, and the new version keeps running and
   then runs the plugin updates;
2. updates to A.post2: the new host fails, the launcher restores the snapshot and A.post1 runs again;
3. restores the snapshot taken before step 1: A runs again with its data.

With --image the same update runs in a container started from that host image: the panel installs A.post1
into the data volume, and after a container restart the volume version still runs.

Needs uv and Python 3.13 (and Docker for --image); no OneBot service or model.

    uv run --no-sync python scripts/smoke_update.py <work directory> [--image I] [--wheel W --requirements R]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.cookiejar
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from functools import partial

from smoke_install import Output, free_port, request, wait_until_served

PROJECT = Path(__file__).resolve().parents[1]
PLATFORM = 'smoke'
SWITCH_SECONDS = 300


def build_inputs(work: Path) -> tuple[Path, Path]:
    dist = work / 'dist'
    subprocess.run(['uv', 'build', '--wheel', '--out-dir', str(dist)], cwd=PROJECT, check=True)
    requirements = work / 'requirements.txt'
    subprocess.run(['uv', 'export', '--frozen', '--no-dev', '--no-emit-project', '--no-hashes',
                    '--output-file', str(requirements)], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
    wheel, = dist.glob('len_bot-*.whl')
    return wheel, requirements


def relabel(wheel: Path, version: str, destination: Path, *, broken: bool = False) -> Path:
    """The same wheel under another version; broken makes its host exit before the panel starts."""
    old = wheel.name.split('-')[1]
    target = destination / wheel.name.replace(f'-{old}-', f'-{version}-')
    records = []
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as output:
        for item in source.infolist():
            name = item.filename.replace(f'len_bot-{old}.dist-info', f'len_bot-{version}.dist-info')
            data = source.read(item)
            if name.endswith('.dist-info/METADATA'):
                data = re.sub(rb'^Version: .*$', f'Version: {version}'.encode(), data, count=1, flags=re.M)
            if broken and name == 'len_bot/next/host.py':
                data = b"raise SystemExit('smoke: this release does not start')\n" + data
            if name.endswith('.dist-info/RECORD'):
                continue
            output.writestr(name, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            records.append(f'{name},sha256={digest},{len(data)}')
        record = f'len_bot-{version}.dist-info/RECORD'
        output.writestr(record, '\n'.join([*records, f'{record},,']) + '\n')
    return target


def install_release(directory: Path, version: str, wheel: Path, requirements: Path) -> None:
    """releases/<version>: python/ (a virtual environment here) and release.json."""
    directory.mkdir(parents=True)
    subprocess.run(['uv', 'venv', '--quiet', '--python', '3.13', str(directory / 'python')], check=True)
    subprocess.run(['uv', 'pip', 'install', '--quiet', '--python', str(directory / 'python/bin/python3'),
                    '--requirement', str(requirements), str(wheel)], check=True)
    (directory / 'release.json').write_text(json.dumps({'version': version, 'platform': PLATFORM}) + '\n')


def publish(work: Path, served: Path, base: str, version: str, wheel: Path, requirements: Path) -> dict:
    """One release in the served folder: its package and manifest, and its entry in the GitHub list."""
    name = f'lenbot-{version}-{PLATFORM}'
    staging = work / 'staging' / name
    install_release(staging / 'releases' / version, version, wheel, requirements)
    folder = served / version
    folder.mkdir(parents=True)
    bundle = folder / f'{name}.tar.gz'
    with tarfile.open(bundle, 'w:gz') as archive:
        archive.add(staging, arcname=name)
    shutil.rmtree(staging)
    body = bundle.read_bytes()
    manifest = {'manifest_version': 1, 'updater_protocol': 2, 'version': version, 'tag': 'v' + version,
                'bundles': {PLATFORM: bundle.name},
                'files': {bundle.name: {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}}}
    (folder / 'release-manifest.json').write_text(json.dumps(manifest))
    return {'tag_name': 'v' + version, 'prerelease': False, 'draft': False, 'body': f'# LenBot {version}\n',
            'published_at': None, 'assets': [{'name': item, 'browser_download_url': f'{base}/{version}/{item}'}
                                             for item in (bundle.name, 'release-manifest.json')]}


class Panel:
    def __init__(self, port: int):
        self.url = f'http://127.0.0.1:{port}'
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path: str, body: dict | None = None) -> dict:
        status, text = request(self.opener, self.url + path, body=body, headers={'Origin': self.url})
        if status != 200:
            raise RuntimeError(f'{path} answered {status}: {text[:1000]}')
        return json.loads(text)

    def ready_version(self) -> str | None:
        try:
            status, text = request(self.opener, self.url + '/api/host/ready')
            value = json.loads(text) if status == 200 else None
        except (OSError, ValueError):
            return None
        return value['version'] if value and value['ready'] else None

    def login(self) -> None:
        self.call('/api/auth/login', {'username': 'smoke', 'password': 'smoke-password'})

    def switch(self, path: str, body: dict | None, previous: str, alive) -> dict:
        """Start an update or a restore, wait until the host went away and came back, and read the result."""
        self.call(path, body)
        deadline = time.monotonic() + SWITCH_SECONDS
        gone = False
        while time.monotonic() < deadline:
            if not alive():
                raise RuntimeError('the launcher exited during the switch')
            version = self.ready_version()
            gone = gone or version is None
            if gone and version is not None:
                self.login()
                state = self.call('/api/host/updates')
                if state['result'] and state['result']['finished_at'] > deadline - SWITCH_SECONDS:
                    return state
            time.sleep(1)
        raise TimeoutError(f'{path} did not finish within {SWITCH_SECONDS}s (was {previous})')


def plugins_followed(panel: Panel, state: dict) -> dict:
    """The new host brings plugins to their catalog versions; these instances have none."""
    deadline = time.monotonic() + 120
    while state['result']['plugins'] == 'pending' and time.monotonic() < deadline:
        time.sleep(1)
        state = panel.call('/api/host/updates')
    assert state['result']['plugins'] == [], state['result']
    return state


def run(work: Path, wheel: Path | None, requirements: Path | None) -> dict:
    work.mkdir(parents=True, exist_ok=False)
    if wheel is None:
        wheel, requirements = build_inputs(work)
    current = wheel.name.split('-')[1]
    good, broken = current + '.post1', current + '.post2'
    wheels = work / 'wheels'
    wheels.mkdir()
    root = work / 'Len Bot'
    install_release(root / 'releases' / current, current, wheel, requirements)
    script = (PROJECT / 'deploy/package/run').read_text().replace('@VERSION@', current)
    (root / 'run').write_text(script)
    (root / 'run').chmod(0o755)

    served = work / 'served'
    served.mkdir()
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(served)))
    base = f'http://127.0.0.1:{server.server_address[1]}'
    releases = [publish(work, served, base, good, relabel(wheel, good, wheels), requirements),
                publish(work, served, base, broken, relabel(wheel, broken, wheels, broken=True), requirements)]
    (served / 'releases.json').write_text(json.dumps(releases))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    port = free_port()
    process = subprocess.Popen([str(root / 'run')], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace', start_new_session=True,
                               env={**os.environ, 'LENBOT_RELEASES_URL': base + '/releases.json'})
    output = Output(process.stdout)
    alive = lambda: process.poll() is None
    result = {'from': current}
    try:
        match = output.find(re.compile(r'http://127\.0\.0\.1:(\d+)/#token=(\S+)'), time.monotonic() + 90)
        setup = f'http://127.0.0.1:{match[1]}'
        opener = urllib.request.build_opener()
        wait_until_served(opener, setup + '/', time.monotonic() + 90, alive)
        status, text = request(opener, setup + '/api/setup', body={
            'bot_id': 'onebot:90001', 'owners': ['onebot:70001'], 'timezone': 'Asia/Shanghai',
            # No platform: the host runs at once, and with it the plugin updates that follow an update.
            'onebot': None,
            'provider': {'api': 'openai-chat', 'base_url': f'http://127.0.0.1:{free_port()}/v1', 'api_key': 'smoke'},
            'mind': {'provider': 'primary', 'model': 'smoke', 'context_window_tokens': 8192},
            'compaction': {'input_tokens': 6000},
            'scene': 'onebot:group:80001', 'persona_id': 'smoke', 'persona_name': '冒烟角色', 'brief': '更新检查',
            'voice_text': '简短', 'boundaries': '更新检查', 'panel_port': port,
            'username': 'smoke', 'password': 'smoke-password'}, headers={'X-Setup-Token': match[2]})
        assert status == 200, f'first setup answered {status}: {text}'
        panel = Panel(port)
        deadline = time.monotonic() + 90
        while panel.ready_version() != current:
            if time.monotonic() > deadline or not alive():
                raise TimeoutError('the panel did not start after first setup')
            time.sleep(0.5)
        panel.login()
        assert panel.call('/api/host/updates')['managed'] == 'package'

        state = panel.switch('/api/host/updates/start', {'tag': 'v' + good, 'plugins': True}, current, alive)
        assert state['version'] == good and state['result']['status'] == 'complete', state
        first_snapshot = state['result']['snapshot']
        state = plugins_followed(panel, state)
        result['update'] = state['result']

        state = panel.switch('/api/host/updates/start', {'tag': 'v' + broken, 'plugins': False}, good, alive)
        assert state['version'] == good and state['result']['status'] == 'rolled_back', state
        assert 'smoke: this release does not start' in output.tail(400) or state['result']['error'], state
        result['rollback'] = state['result']

        state = panel.switch(f'/api/host/updates/snapshots/{first_snapshot}/restore', {}, good, alive)
        assert state['version'] == current and state['result']['action'] == 'restore', state
        result['restore'] = state['result']
        result['releases'] = sorted(path.name for path in (root / 'releases').iterdir())
    except BaseException:
        print(output.tail(200), file=sys.stderr)
        raise
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(60)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        server.shutdown()
        output.thread.join(5)
    result['exit'] = process.returncode
    if process.returncode != 0:
        print(output.tail(), file=sys.stderr)
        raise RuntimeError(f'run exited with {process.returncode} after SIGTERM')
    return result


def run_docker(work: Path, image: str, wheel: Path | None, requirements: Path | None) -> dict:
    """The same update in a container: the panel installs the next version into the data volume and restarts."""
    work.mkdir(parents=True, exist_ok=False)
    if wheel is None:
        wheel, requirements = build_inputs(work)
    current = subprocess.run(['docker', 'run', '--rm', '--entrypoint', '/opt/lenbot/.venv/bin/python', image, '-c',
                              'from importlib.metadata import version; print(version("len-bot"))'],
                             capture_output=True, text=True, check=True).stdout.strip()
    good = current + '.post1'
    served = work / 'served'
    (served / good).mkdir(parents=True)
    relabelled = relabel(wheel, good, served / good)
    shutil.copy2(requirements, served / good / 'requirements.txt')
    files = {path.name: path.read_bytes() for path in (served / good).iterdir()}
    manifest = {'manifest_version': 1, 'updater_protocol': 2, 'version': good, 'tag': 'v' + good, 'bundles': {},
                'files': {name: {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)} for name, body in files.items()}}
    (served / good / 'release-manifest.json').write_text(json.dumps(manifest))
    server = ThreadingHTTPServer(('0.0.0.0', 0), partial(SimpleHTTPRequestHandler, directory=str(served)))
    base = f'http://host.docker.internal:{server.server_address[1]}'
    (served / 'releases.json').write_text(json.dumps([{
        'tag_name': 'v' + good, 'prerelease': False, 'draft': False, 'body': f'# LenBot {good}\n', 'published_at': None,
        'assets': [{'name': name, 'browser_download_url': f'{base}/{good}/{name}'}
                   for name in (relabelled.name, 'requirements.txt', 'release-manifest.json')]}]))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    name = f'lenbot-update-smoke-{time.time_ns()}'
    volume = name + '-data'
    port = free_port()
    setup = json.loads((PROJECT / 'deploy/current/first-setup.example.json').read_text(encoding='utf-8'))
    setup.update(password='smoke-password', username='smoke', onebot=None)
    setup['provider']['api_key'] = 'smoke'
    alive = lambda: subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', name],
                                   capture_output=True, text=True).stdout.strip() == 'true'
    result = {'image': image, 'from': current}
    subprocess.run(['docker', 'volume', 'create', volume], check=True, stdout=subprocess.DEVNULL)
    try:
        subprocess.run(['docker', 'run', '--rm', '-i', '--user', '10000:10000', '-v', f'{volume}:/data',
                        '--entrypoint', '/opt/lenbot/.venv/bin/python', image, '-m', 'len_bot.next.maintenance.initialize'],
                       input=json.dumps(setup, ensure_ascii=False), text=True, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'run', '-d', '--name', name, '-p', f'127.0.0.1:{port}:11307', '-v', f'{volume}:/data',
                        '--add-host', 'host.docker.internal:host-gateway',
                        '-e', f'LENBOT_RELEASES_URL={base}/releases.json', image], check=True, stdout=subprocess.DEVNULL)
        panel = Panel(port)
        deadline = time.monotonic() + 120
        while panel.ready_version() != current:
            if time.monotonic() > deadline or not alive():
                raise TimeoutError('the container panel did not start')
            time.sleep(1)
        panel.login()
        assert panel.call('/api/host/updates')['managed'] == 'docker'
        state = panel.switch('/api/host/updates/start', {'tag': 'v' + good, 'plugins': True}, current, alive)
        assert state['version'] == good and state['result']['status'] == 'complete', state
        state = plugins_followed(panel, state)
        result['update'] = state['result']
        # Restarted, the container runs the version in the volume instead of the image's.
        subprocess.run(['docker', 'restart', '--timeout', '60', name], check=True, stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 120
        while panel.ready_version() != good:
            if time.monotonic() > deadline:
                raise TimeoutError(f'after a restart the container did not run {good}')
            time.sleep(1)
        result['after_restart'] = good
        foreign = subprocess.run(['docker', 'exec', name, 'find', '/data', '!', '-uid', '10000'],
                                 capture_output=True, text=True, check=True).stdout.split()
        if foreign:
            raise RuntimeError(f'files not owned by the lenbot user: {foreign[:20]}')
    except BaseException:
        subprocess.run(['docker', 'logs', '--tail', '120', name])
        raise
    finally:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['docker', 'volume', 'rm', volume], stdout=subprocess.DEVNULL)
        server.shutdown()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('work', type=Path)
    parser.add_argument('--image', help='Update a container started from this host image instead of a package layout')
    parser.add_argument('--wheel', type=Path, help='A built wheel; built from this checkout when omitted')
    parser.add_argument('--requirements', type=Path, help='The locked requirements that go with --wheel')
    args = parser.parse_args()
    if (args.wheel is None) != (args.requirements is None):
        parser.error('--wheel and --requirements go together')
    result = (run(args.work, args.wheel, args.requirements) if args.image is None
              else run_docker(args.work, args.image, args.wheel, args.requirements))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
