"""The wizard's default persona and the replay copy are the same package."""

from pathlib import Path

from len_bot.next.persona.profile import load_persona, select_examples

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'src/len_bot/default_personas/companion'
REPLAY = ROOT / 'examples/personas/companion'


def files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob('*')) if path.is_file()}


def test_default_persona_matches_the_replay_copy():
    assert files(DEFAULT) == files(REPLAY)


def test_default_persona_carries_examples_for_each_kind_of_turn():
    persona = load_persona(DEFAULT)
    examples = select_examples(persona)
    assert len(examples) == len(persona.examples) == 8
    assert {tag for example in examples for tag in example.tags} == {'闲聊', '求助', '斗嘴', '纠正', '不确定'}
    assert persona.styles == []
