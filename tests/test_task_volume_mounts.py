"""Task directories inside the instance volume mount as volume subpaths, and only matching containers reconcile."""

import json
from pathlib import Path

import pytest

from len_bot.next.configuration.tasks import WorkerSettings
from len_bot.next.work.docker_mounts import require_task_volume_mounts
from len_bot.next.work.sandbox import _mount


def test_a_volume_mount_names_the_subpath_below_the_volume_root(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    [flag, specification] = _mount(root / 'task-workspaces' / 'onebot:group:1' / 'tasks' / '7', '/workspace',
                                   readonly=True, volume=('lenbot-data', root))
    assert flag == '--mount'
    assert specification == ('type=volume,source=lenbot-data,'
                             'volume-subpath=task-workspaces/onebot:group:1/tasks/7,target=/workspace,readonly')


def reported(root: Path, *, workspace: str = 'w/s/tasks/1', volume: str = 'lenbot-data') -> str:
    return json.dumps([
        {'Type': 'volume', 'Source': volume, 'Target': '/workspace', 'VolumeOptions': {'Subpath': workspace}},
        {'Type': 'volume', 'Source': volume, 'Target': '/home/agent', 'VolumeOptions': {'Subpath': 'r/s/1/home'}},
        {'Type': 'volume', 'Source': volume, 'Target': '/run/lenbot', 'ReadOnly': True,
         'VolumeOptions': {'Subpath': 'r/s/1/control'}},
    ])


def test_recorded_volume_mounts_must_match_this_task(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    paths = {'workspace': root / 'w/s/tasks/1', 'home': root / 'r/s/1/home', 'control': root / 'r/s/1/control'}
    require_task_volume_mounts(reported(root), ('lenbot-data', root), **paths)
    for raw in (reported(root, workspace='w/s/tasks/2'), reported(root, volume='other-data'), 'null'):
        with pytest.raises(ValueError):
            require_task_volume_mounts(raw, ('lenbot-data', root), **paths)


def test_task_trees_must_be_inside_the_volume() -> None:
    root = Path('/srv/lenbot').resolve()
    base = {'docker_binary': root / 'docker', 'docker_host': 'unix:///var/run/docker.sock', 'image': 'w:1',
            'uid': 10000, 'gid': 10000, 'model_reasoning': True, 'workspace_root': root / 'task-workspaces',
            'runtime_root': root / 'task-runtime', 'delivery_root': root / 'deliveries',
            'task_volume': {'name': 'lenbot-data', 'root': root}}
    assert WorkerSettings.model_validate(base).task_volume.name == 'lenbot-data'
    with pytest.raises(ValueError):
        WorkerSettings.model_validate({**base, 'runtime_root': root.parent / 'elsewhere'})
