"""Built-in skills follow the programs and network mode of the task environment."""

from pathlib import Path

from len_bot.next.configuration.tasks import WorkerSettings
from len_bot.next.tools.skills import load_catalog, worker_catalog
from len_bot.next.work.environment import environment_prompt

NOWHERE = Path(__file__).parent / 'nonexistent-skills'
EVERYTHING = frozenset({'lenbot-render', 'lenbot-browser', 'ffmpeg', 'ffprobe', 'pandoc', 'pdftotext', 'pdftoppm',
                        'font:zh', 'python:pandas', 'python:openpyxl', 'python:matplotlib', 'python:python-docx',
                        'python:pypdf', 'python:pillow'})
BASELINE = {'pdf', 'presentation', 'skill-writing', 'group-summary'}


def names(programs: frozenset[str], *, network: bool = True) -> set[str]:
    return {skill.name for skill in load_catalog(NOWHERE, 'onebot:group:1', programs=programs, network=network)}


def worker(root: Path, **settings) -> WorkerSettings:
    return WorkerSettings.model_validate({
        'workspace_root': root / 'w', 'runtime_root': root / 'r', 'delivery_root': root / 'd',
        'model_reasoning': True, **settings})


def test_every_builtin_skill_loads_where_the_environment_has_all_programs() -> None:
    assert names(EVERYTHING) == BASELINE | {
        'html-document', 'media-processing', 'media-analysis', 'public-browser', 'web-research', 'spreadsheet',
        'data-analysis', 'word-document'}


def test_each_skill_waits_for_the_program_it_uses() -> None:
    every = names(EVERYTHING)
    assert every - names(EVERYTHING - {'ffmpeg'}) == {'media-processing', 'media-analysis'}
    assert every - names(EVERYTHING - {'lenbot-render'}) == {'html-document'}
    assert every - names(EVERYTHING - {'python:openpyxl'}) == {'spreadsheet'}
    assert every - names(EVERYTHING - {'python:python-docx'}) == {'word-document'}
    assert every - names(EVERYTHING - {'python:matplotlib'}) == {'data-analysis'}
    assert names(frozenset(), network=False) == BASELINE


def test_the_network_decides_the_skills_that_read_the_web() -> None:
    assert names(EVERYTHING) - names(EVERYTHING, network=False) == {'web-research', 'public-browser'}


def test_the_local_sandbox_lists_what_its_task_runtime_holds(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    runtime = root / 'task-runtime'
    (runtime / 'bin').mkdir(parents=True)
    (runtime / 'bin' / 'lenbot-render').touch()
    (runtime / 'python' / 'pandas').mkdir(parents=True)
    local = worker(root, sandbox='bwrap', bwrap_binary=root / 'bwrap', task_runtime=runtime)
    programs = local.available_programs()
    assert {'lenbot-render', 'python:pandas'} <= programs
    assert not programs & {'lenbot-browser', 'python:openpyxl', 'python:python-docx'}
    skills = {skill.name for skill in worker_catalog(local, 'onebot:group:1')}
    assert 'html-document' in skills and not skills & {'public-browser', 'spreadsheet', 'word-document'}


def test_the_worker_image_has_every_program_and_the_network_mode_follows_egress(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    image = {'docker_binary': root / 'docker', 'docker_host': 'unix:///var/run/docker.sock', 'image': 'w:1',
             'uid': 1, 'gid': 1}
    assert worker(root, **image).available_programs() >= EVERYTHING
    closed = {skill.name for skill in worker_catalog(worker(root, **image), 'onebot:group:1')}
    opened = {skill.name for skill in worker_catalog(
        worker(root, **image, egress={'mode': 'public'}), 'onebot:group:1')}
    assert opened - closed == {'web-research', 'public-browser'}
    assert closed == BASELINE | {'html-document', 'media-processing', 'media-analysis', 'spreadsheet',
                                 'data-analysis', 'word-document'}


def test_the_environment_text_describes_only_what_the_environment_has() -> None:
    facts = {'programs': sorted(EVERYTHING), 'public_browser': {'command': 'lenbot-browser'}}
    full = environment_prompt(facts, EVERYTHING)
    for phrase in ('lenbot-render', 'python-docx', '中文字体', 'ffmpeg', 'pdftotext', 'public_browser 非空'):
        assert phrase in full
    bare = environment_prompt({'programs': [], 'public_browser': None}, frozenset())
    for phrase in ('lenbot-render', 'pandas', '中文字体', 'ffmpeg', 'pdftotext', 'public_browser 非空'):
        assert phrase not in bare
    assert '\n\n\n' not in bare and '${' not in bare + full
