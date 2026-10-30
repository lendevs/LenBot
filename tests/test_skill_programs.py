"""Built-in skills whose program the task environment lacks are left out of the catalog."""

from pathlib import Path

from len_bot.next.configuration.tasks import WorkerSettings
from len_bot.next.tools.skills import load_catalog


def names(missing: frozenset[str], *, public_browser: bool = True) -> set[str]:
    return {skill.name for skill in load_catalog(Path(__file__).parent / 'nonexistent-skills', 'onebot:group:1',
                                                 public_browser=public_browser, missing=missing)}


def test_catalog_drops_only_the_skills_whose_program_is_missing() -> None:
    every = names(frozenset())
    assert {'html-document', 'media-processing', 'public-browser', 'pdf'} <= every
    assert every - names(frozenset({'ffmpeg', 'lenbot-render'})) == {'media-processing', 'html-document'}
    assert 'public-browser' not in names(frozenset(), public_browser=False)


def test_the_local_sandbox_reports_runtime_programs_it_lacks(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    runtime = root / 'task-runtime-image'
    (runtime / 'bin').mkdir(parents=True)
    (runtime / 'bin' / 'lenbot-render').touch()
    worker = WorkerSettings.model_validate({
        'sandbox': 'bwrap', 'bwrap_binary': root / 'bwrap', 'task_runtime': runtime,
        'workspace_root': root / 'w', 'runtime_root': root / 'r', 'delivery_root': root / 'd',
        'model_reasoning': True})
    missing = worker.missing_programs()
    assert 'lenbot-browser' in missing and 'lenbot-render' not in missing
    docker = WorkerSettings.model_validate({
        'docker_binary': root / 'docker', 'docker_host': 'unix:///var/run/docker.sock', 'image': 'w:1',
        'uid': 1, 'gid': 1, 'workspace_root': root / 'w', 'runtime_root': root / 'r',
        'delivery_root': root / 'd', 'model_reasoning': True})
    assert docker.missing_programs() == frozenset()
