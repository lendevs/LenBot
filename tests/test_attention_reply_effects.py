"""Reply effects of the bot's ambient interjections stretch or, more slowly, shorten the wait before it joins in again
in that group."""

import json

import pytest

from len_bot.next.chat.attention import EFFECT_CEILING, EFFECT_FLOOR, SceneRunner
from len_bot.next.chat.session import Chat
from len_bot.next.storage.store import Store
from test_attention_protocol import START, config_for, message

OTHER = 'onebot:group:80002'


def judged(store: Store, scene: str, at: float, reaction: str, channels=('ambient',)) -> None:
    with store.db:
        entry = store.db.execute("SELECT COALESCE(MAX(entry_seq),0)+1 FROM reply_effects").fetchone()[0]
        store.db.execute(
            "INSERT INTO reply_effects(scene,entry_seq,turn_id,channels,message_seqs,planned_parts,first_sent_at,"
            "last_sent_at,deadline,observed_seqs,closed_at,reaction,reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (scene, entry, None, json.dumps(list(channels)), '[]', 1, at, at, at + 180, '[1]', at + 180,
             reaction, '合成判定'))


def runner(root, now):
    config, persona = config_for(root)
    store = Store(config.database, now=lambda: now[0])
    return store, SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)


@pytest.mark.parametrize(('reactions', 'factor'), [
    ([], 1.0),
    ([(0, 'continue')] * 4 + [(0, 'agree')] * 4, 1 + 0.25 * 8 / 10),
    ([(0, 'negative')] * 4, 1 - 0.5 * 4 / 6),
    ([(0, 'unrelated')] * 10, 1 - 0.5 * 10 / 12),
    # A day old counts half; three days old is out of the window.
    ([(86400, 'negative')], 1 - 0.5 * 0.5 / 2.5),
    ([(3 * 86400 + 1, 'negative')] * 4, 1.0),
    ([(0, 'negative'), (0, 'continue')], 1.0),
    ([(0, 'continue')] * 2, 1 + 0.25 * 2 / 4),
    ([(0, 'correct'), (0, 'uncertain')], 1.0),
])
def test_factor_weighs_recent_ambient_reactions_between_the_floor_and_the_ceiling(tmp_path, reactions, factor):
    now = [START + 10 * 86400]
    store, live = runner(tmp_path, now)
    with store:
        for age, reaction in reactions:
            judged(store, live.config.scene, now[0] - age, reaction)
        assert live.effect_factor() == pytest.approx(factor)
        assert EFFECT_FLOOR <= live.effect_factor() <= EFFECT_CEILING


def test_factor_ignores_direct_turns_other_groups_and_more_than_ten_samples(tmp_path):
    now = [START + 10 * 86400]
    store, live = runner(tmp_path, now)
    with store:
        for _ in range(5):
            judged(store, live.config.scene, now[0], 'negative', channels=('direct',))
            judged(store, OTHER, now[0], 'negative')
        assert live.effect_factor() == 1.0
        for _ in range(10):
            judged(store, live.config.scene, now[0], 'continue')
        for _ in range(10):
            judged(store, live.config.scene, now[0] - 60, 'negative')
        # Only the ten newest by record order count; here those are the negatives recorded last.
        assert live.effect_factor() == pytest.approx(1 - 0.5 * 10 / 12, abs=1e-3)


def waits(root, reactions) -> tuple[float, float]:
    """How long a message worth joining in on waits after the bot spoke, and how long an @ waits."""
    now = [START]
    store, live = runner(root, now)
    with store:
        for reaction in reactions:
            judged(store, live.config.scene, START - 600, reaction)
        live.state.spoke_at = START
        live.receive(message(70001, 1, '有人知道周末去哪爬山好吗？'))
        ambient = live.deadline() - START
        live.receive(message(70002, 2, '问你', direct=True))
        assert live.state.pending.channel == 'direct'
        return ambient, live.deadline() - START


def test_reactions_move_the_wait_to_join_in_both_ways_but_not_direct_replies(tmp_path):
    minimum = runner(tmp_path / 'config', [START])[1].settings.ambient_min_interval_seconds
    baseline = waits(tmp_path / 'none', [])
    welcomed = waits(tmp_path / 'welcomed', ['continue'] * 6)
    disliked = waits(tmp_path / 'disliked', ['negative', 'unrelated'] * 3)
    assert baseline[0] == minimum
    assert welcomed[0] == pytest.approx(minimum / (1 + 0.25 * 6 / 8), rel=1e-2)
    assert disliked[0] == pytest.approx(minimum / (1 - 0.5 * 6 / 8), rel=1e-2)
    # The same number of reactions holds the bot back further than it lets it in.
    assert disliked[0] - baseline[0] > baseline[0] - welcomed[0]
    assert disliked[1] == welcomed[1] == baseline[1]
