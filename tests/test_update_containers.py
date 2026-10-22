"""Docker backend: hosts that `docker compose up` recreated or removed are found again or rebuilt."""

from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/updater'))
from common import read_json, write_json
from containers import Containers, NotFound

IMAGES = {'registry/lenbot:0.1.0': {'Config': {'Env': ['PATH=/usr/bin'], 'Labels': {}}},
          'registry/lenbot:0.2.0': {'Config': {'Env': ['PATH=/usr/bin'], 'Labels': {}}}}


def container(identifier: str, name: str, image: str, volume: str, running: bool) -> dict:
    return {'Id': identifier, 'Name': '/' + name, 'Image': image, 'State': {'Running': running},
            'Config': {'Image': image, 'Env': ['PATH=/usr/bin'], 'Labels': {'com.docker.compose.service': 'lenbot'}},
            'HostConfig': {'Binds': [volume + ':/opt/lenbot/.venv:rw', 'lenbot-data:/srv/lenbot:rw'], 'GroupAdd': None},
            'NetworkSettings': {'Networks': {'lenbot_default': {
                'IPAMConfig': None, 'Links': None, 'Aliases': ['lenbot'], 'DriverOpts': None}}}}


class Engine(Containers):
    """A daemon in memory: containers by ID, looked up by ID or name like the Engine API."""

    def __init__(self, root: Path, containers: list[dict]):
        super().__init__(root, log=None)
        self.containers = {item['Id']: item for item in containers}
        self.commands: list[list[str]] = []

    def find(self, key: str) -> dict:
        for item in self.containers.values():
            if key in (item['Id'], item['Name'].lstrip('/')):
                return item
        raise NotFound(f'No such container: {key}')

    def api(self, method: str, endpoint: str, payload=None):
        path = urlsplit(endpoint)
        parts = [unquote(part) for part in path.path.strip('/').split('/')]
        query = {key: value[0] for key, value in parse_qs(path.query).items()}
        if parts[0] == 'images':
            if parts[1] not in IMAGES and not any(item['Image'] == parts[1] for item in self.containers.values()):
                raise NotFound(f'No such image: {parts[1]}')
            return IMAGES.get(parts[1], IMAGES['registry/lenbot:0.2.0'])
        if parts == ['containers', 'create']:
            identifier = f'created-{len(self.containers)}'
            volume = payload['HostConfig']['Binds'][0].split(':')[0]
            self.containers[identifier] = {**container(identifier, query['name'], payload['Image'], volume, False),
                                           'Config': payload, 'HostConfig': payload['HostConfig']}
            return {'Id': identifier}
        item = self.find(parts[1])
        if method == 'DELETE':
            del self.containers[item['Id']]
        elif parts[2:] == ['stop']:
            item['State']['Running'] = False
        elif parts[2:] == ['start']:
            item['State']['Running'] = True
        elif parts[2:] == ['rename']:
            item['Name'] = '/' + query['name']
        else:
            return item
        return None

    def command(self, args: list[str], *, capture: bool = False) -> str:
        self.commands.append(args)
        return ''


@pytest.fixture
def deployment(tmp_path: Path) -> Path:
    write_json(tmp_path / 'deployment.json', {'mode': 'docker', 'project': 'lenbot', 'container': 'lenbot-host',
                                              'docker_socket': '/var/run/docker.sock', 'host_directory': str(tmp_path)})
    return tmp_path


def test_a_recreated_host_is_found_by_its_fixed_name(deployment: Path) -> None:
    write_json(deployment / 'current.json', {'version': '0.2.0', 'container': 'removed-by-compose',
                                             'host_image': 'registry/lenbot:0.2.0', 'python_volume': 'lenbot-python-0.2.0'})
    engine = Engine(deployment, [container('recreated', 'lenbot-host', 'registry/lenbot:0.2.0', 'lenbot-python-0.2.0', True)])
    assert engine.metadata()['container'] == 'recreated'
    engine.stop()
    assert not engine.containers['recreated']['State']['Running']


def test_restore_rebuilds_a_previous_host_that_compose_removed(deployment: Path, tmp_path: Path) -> None:
    old = {'version': '0.1.0', 'container': 'previous-removed', 'host_image': 'registry/lenbot:0.1.0',
           'python_volume': 'lenbot-python-0.1.0'}
    write_json(deployment / 'previous.json', old)
    write_json(deployment / 'current.json', {'version': '0.2.0', 'container': 'replaced-by-compose',
                                             'host_image': 'registry/lenbot:0.2.0', 'python_volume': 'lenbot-python-0.2.0'})
    engine = Engine(deployment, [container('recreated', 'lenbot-host', 'registry/lenbot:0.2.0', 'lenbot-python-0.2.0', True)])
    engine.restore(old, tmp_path / 'backups/snapshot')

    host, = engine.containers.values()
    assert host['Name'] == '/lenbot-host' and host['Image'] == 'registry/lenbot:0.1.0'
    assert host['HostConfig']['Binds'] == ['lenbot-python-0.1.0:/opt/lenbot/.venv:rw', 'lenbot-data:/srv/lenbot:rw']
    restore, = engine.commands
    assert restore[restore.index('--volumes-from') + 1] == host['Id'] and 'registry/lenbot:0.1.0' in restore
    assert read_json(deployment / 'current.json') == {**old, 'container': host['Id']}
    assert 'image: registry/lenbot:0.1.0' in (deployment / 'host.version.compose.yaml').read_text()


def test_applying_a_candidate_that_compose_removed_asks_to_prepare_again(deployment: Path) -> None:
    write_json(deployment / 'current.json', {'version': '0.1.0', 'container': 'lenbot-host',
                                             'host_image': 'registry/lenbot:0.1.0', 'python_volume': 'lenbot-python-0.1.0'})
    engine = Engine(deployment, [container('running', 'lenbot-host', 'registry/lenbot:0.1.0', 'lenbot-python-0.1.0', True)])
    with pytest.raises(ValueError, match='重新准备更新'):
        engine.inspect({'version': '0.2.0', 'container': 'candidate-removed', 'host_image': 'registry/lenbot:0.2.0'})
    assert engine.commands == [] and engine.containers['running']['State']['Running']
