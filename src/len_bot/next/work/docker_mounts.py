"""One native Docker mount report before reconciling a recorded task container."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class ContainerMount(BaseModel):
    model_config = ConfigDict(strict=True, extra='ignore')
    type: str = Field(alias='Type')
    source: str = Field(alias='Source')
    destination: str = Field(alias='Destination')
    writable: bool = Field(alias='RW')


MOUNTS = TypeAdapter(list[ContainerMount])


def require_task_mounts(raw: str, *, workspace: Path, home: Path, control: Path) -> None:
    try:
        mounts = MOUNTS.validate_json(raw, strict=True)
    except ValidationError as error:
        raise ValueError(f'Invalid Docker task mounts: {error}; raw={raw[:1000]!r}') from error
    expected = {'/workspace': (str(workspace), True), '/home/agent': (str(home), True),
                '/run/lenbot': (str(control), False)}
    present: set[str] = set()
    for mount in mounts:
        if mount.destination == '/inputs':
            expected['/inputs'] = (str(control.parent / 'inputs'), False)
        if mount.destination not in expected:
            continue
        if mount.destination in present:
            raise ValueError(f'Duplicate task mount destination {mount.destination!r}; raw={raw[:1000]!r}')
        present.add(mount.destination)
        source, writable = expected[mount.destination]
        if mount.type != 'bind' or mount.source != source or mount.writable != writable:
            raise ValueError(f'Recorded container belongs to a different task/instance mount: '
                             f'expected {mount.destination!r} source={source!r} RW={writable}; '
                             f'actual={mount.model_dump()!r}')
    if missing := set(expected) - present:
        raise ValueError(f'Recorded container lacks its current task mounts: {sorted(missing)!r}; raw={raw[:1000]!r}')


class VolumeOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra='ignore')
    subpath: str = Field(default='', alias='Subpath')


class ConfiguredMount(BaseModel):
    model_config = ConfigDict(strict=True, extra='ignore')
    type: str = Field(alias='Type')
    source: str = Field(alias='Source')
    target: str = Field(alias='Target')
    read_only: bool = Field(default=False, alias='ReadOnly')
    volume_options: VolumeOptions = Field(default_factory=VolumeOptions, alias='VolumeOptions')


CONFIGURED = TypeAdapter(list[ConfiguredMount] | None)


def require_task_volume_mounts(raw: str, volume: tuple[str, Path], *, workspace: Path, home: Path,
                               control: Path) -> None:
    """The ``HostConfig.Mounts`` of a task container whose directories are subpaths of ``volume``."""
    try:
        mounts = CONFIGURED.validate_json(raw, strict=True) or []
    except ValidationError as error:
        raise ValueError(f'Invalid Docker task mounts: {error}; raw={raw[:1000]!r}') from error
    name, root = volume
    root = root.resolve()

    def subpath(path: Path) -> str:
        return path.relative_to(root).as_posix()
    expected = {'/workspace': (subpath(workspace), False), '/home/agent': (subpath(home), False),
                '/run/lenbot': (subpath(control), True)}
    present: set[str] = set()
    for mount in mounts:
        if mount.target == '/inputs':
            expected['/inputs'] = (subpath(control.parent / 'inputs'), True)
        if mount.target not in expected:
            continue
        if mount.target in present:
            raise ValueError(f'Duplicate task mount destination {mount.target!r}; raw={raw[:1000]!r}')
        present.add(mount.target)
        path, read_only = expected[mount.target]
        if (mount.type != 'volume' or mount.source != name or mount.volume_options.subpath != path
                or mount.read_only != read_only):
            raise ValueError(f'Recorded container belongs to a different task/instance mount: '
                             f'expected {mount.target!r} volume={name!r} subpath={path!r} read_only={read_only}; '
                             f'actual={mount.model_dump()!r}')
    if missing := set(expected) - present:
        raise ValueError(f'Recorded container lacks its current task mounts: {sorted(missing)!r}; raw={raw[:1000]!r}')
