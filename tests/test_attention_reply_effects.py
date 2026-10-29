"""Reply effects of the bot's ambient interjections scale its later participation score in that group."""

import json

import pytest

from len_bot.next.chat.attention import EFFECT_FLOOR, SceneRunner
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


def runner(root, now, activity=1.0):
    config, persona = config_for(root)
    config.attention.activity = activity
    store = Store(config.database, now=lambda: now[0])
    return store, SceneRunner(Chat(config, persona, store, None, now=lambda: now[0]), lambda event: None)


@pytest.mark.parametrize(('reactions', 'factor'), [
    ([], 1.0),
    ([(0, 'continue')] * 4 + [(0, 'agree')] * 4, 1.0),
    ([(0, 'negative')] * 4, 1 - 0.5 * 4 / 6),
    ([(0, 'unrelated')] * 10, 1 - 0.5 * 10 / 12),
    # A day old counts half; three days old is out of the window.
    ([(86400, 'negative')], 1 - 0.5 * 0.5 / 2.5),
    ([(3 * 86400 + 1, 'negative')] * 4, 1.0),
    ([(0, 'negative'), (0, 'continue')], 1.0),
    ([(0, 'correct'), (0, 'uncertain')], 1.0),
])
def test_factor_weighs_recent_ambient_reactions_between_the_floor_and_one(tmp_path, reactions, factor):
    now = [START + 10 * 86400]
    store, live = runner(tmp_path, now)
    with store:
        for age, reaction in reactions:
            judged(store, live.config.scene, now[0] - age, reaction)
        assert live.effect_factor() == pytest.approx(factor)
        assert EFFECT_FLOOR <= live.effect_factor() <= 1


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


QUESTIONS = ['有人知道周末去哪爬山好吗？', '今天好热啊', '谁会修自行车链条？', '哈哈', '这个怎么弄？',
             '晚饭吃什么', '有没有推荐的耳机？', '嗯', '下雨了', '为什么我的快递还没到？']


def ambient_wakes(root, reactions) -> tuple[int, int]:
    """Ambient wakes and direct wakes for one fixed hour of group messages."""
    now = [START]
    store, live = runner(root, now, activity=0.3)
    with store:
        for reaction in reactions:
            judged(store, live.config.scene, START - 600, reaction)
        ambient = direct = 0
        for index in range(60):
            now[0] = START + index * 60
            raw = message(70001 + index % 4, 60000 + index, QUESTIONS[index % len(QUESTIONS)], direct=index % 15 == 0)
            receipt = live.receive(raw)
            verdict = receipt['wake_verdict']
            ambient += verdict['woke'] and verdict['channel'] == 'ambient'
            direct += verdict['woke'] and verdict['channel'] == 'direct'
            if verdict['woke']:
                # The turn reads the batch at once, so the next message starts a new one.
                with store.db:
                    store.db.execute("INSERT INTO mind_sessions(scene,last_message_seq) VALUES (?,?) "
                                     "ON CONFLICT(scene) DO UPDATE SET last_message_seq=excluded.last_message_seq",
                                     (live.config.scene, receipt['message_seq']))
                live.state.pending = None
                live.state.ambient_last_at = None
        return ambient, direct


def test_disliked_interjections_lower_hourly_ambient_wakes_but_not_direct_replies(tmp_path):
    baseline = ambient_wakes(tmp_path / 'none', [])
    welcomed = ambient_wakes(tmp_path / 'welcomed', ['continue'] * 6)
    disliked = ambient_wakes(tmp_path / 'disliked', ['negative', 'unrelated'] * 3)
    assert baseline[0] > 0 and welcomed == baseline
    assert disliked[0] < baseline[0]
    assert disliked[1] == baseline[1] == 4
