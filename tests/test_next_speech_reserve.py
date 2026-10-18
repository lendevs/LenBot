"""Who may use the direct reserve of the hourly speech limit (audit A-1, A-2)."""
import pytest

from len_bot.next.models.limits import SpeechLimitReached, record_speech
from len_bot.next.storage.store import Store


def _runner(tmp_path, limit=2, reserve=1):
    from test_next_persona_permissions import _config, _package
    from len_bot.next.chat.attention import SceneRunner
    from len_bot.next.chat.session import Chat
    from len_bot.next.persona.profile import load_persona
    package = _package(tmp_path, 'plain', tools=['say'], documents={})
    config = _config(tmp_path / 'instance', package)
    config.limits.messages_per_hour, config.limits.direct_reserve = limit, reserve
    store = Store(config.database)
    return SceneRunner(Chat(config, load_persona(package), store, None), lambda event: None), store, config


@pytest.mark.parametrize('channel,reserve', [('schedule', True), ('task', True), ('audio', False),
                                             ('plugin', False), ('ambient', False), ('resume', False)])
def test_only_direct_reminder_and_task_turns_use_the_reserve(tmp_path, channel, reserve):
    runner, store, config = _runner(tmp_path)
    with store:
        record_speech(store, config.scene); record_speech(store, config.scene)
        chat = runner.chat
        chat.turn_channel, chat.direct_request = channel, False
        assert chat.speech_reserve is reserve
        if reserve:
            chat.check_limits()
        else:
            with pytest.raises(SpeechLimitReached):
                chat.check_limits()
        chat.direct_request = True
        assert chat.speech_reserve
        chat.check_limits()


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['audio', 'plugin'])
async def test_audio_and_plugin_wakes_wait_for_the_normal_limit(tmp_path, monkeypatch, source):
    from len_bot.next.chat import attention
    from len_bot.next.chat.attention import PendingWake
    runner, store, config = _runner(tmp_path)
    with store:
        if source == 'audio':
            monkeypatch.setattr(runner, 'audio_ready', lambda: True)
        else:
            monkeypatch.setattr(attention.PluginStore, 'plugin_wake_pending', lambda self, scene: True)
        assert await runner.ready_messages(wait=False) is not None
        record_speech(store, config.scene); record_speech(store, config.scene)
        # Normal limit used, reserve left: a voice note or plugin event must not start a turn.
        assert await runner.ready_messages(wait=False) is None
        # A real @ still gets through and may then answer the transcript in the same turn.
        runner.state.pending = PendingWake('direct', store.now())
        assert await runner.ready_messages(wait=False) is not None


@pytest.mark.asyncio
async def test_non_direct_follow_ups_after_an_answer_do_not_drain_the_reserve(tmp_path, monkeypatch):
    from len_bot.next.chat.attention import PendingWake
    runner, store, config = _runner(tmp_path)
    with store:
        chat = runner.chat
        chat.direct_request, chat.turn_channel = True, 'direct'
        ready = [([(1, object(), 0.0)], None, [])]

        async def ready_messages(**_):
            return ready[0]
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        monkeypatch.setattr(runner, 'batch', lambda pending, reason: (1, ['x']))
        monkeypatch.setattr(store, 'append_batch', lambda *args, **kwargs: None)
        # Before the @ is answered, queued chatter rides along with the direct reserve.
        assert await runner.append_during_turn(False, 'turn')
        assert chat.speech_reserve
        chat.turn_expressions = chat.turn_messages = 1
        assert await runner.append_during_turn(False, 'turn')
        assert not chat.speech_reserve
        # A new @ in the same turn grants it again.
        runner.state.pending = PendingWake('direct', store.now())
        assert await runner.append_during_turn(False, 'turn')
        assert chat.speech_reserve


@pytest.mark.asyncio
async def test_direct_turn_cut_off_by_the_limit_resumes_with_the_reserve(tmp_path, monkeypatch):
    from len_bot.next.chat.attention import AttentionState, PendingWake
    runner, store, config = _runner(tmp_path)
    with store:
        seen = []

        async def run_turn(**turn):
            seen.append((turn['channel'], turn.get('direct'), runner.chat.speech_reserve))
            runner.chat.direct_request = turn.get('direct', False)
            runner.chat.turn_channel = turn['channel']
            turn_id = store.start_turn(config.scene)
            return {'turn_id': turn_id, 'status': 'limited', 'error': 'SpeechLimitReached: 用完',
                    'expressions': [], 'failed_tools': 0, 'limit_until': store.now() + 60, 'limit_kind': 'speech'}
        monkeypatch.setattr(runner.chat, 'run_turn', run_turn)
        runner.state.pending = PendingWake('direct', store.now())
        await runner._turn('direct', batch=None, direct=True)
        assert runner.resume and runner.state.resume_reserve
        for _ in range(2): record_speech(store, config.scene)
        # Normal limit used, reserve left: the resume does not wait for the normal window.
        assert runner.speech_hold() is None
        assert AttentionState(**__import__('dataclasses').asdict(runner.state)).resume_reserve
        # An ordinary wake cut off by the limit resumes at the normal limit.
        runner.chat.direct_request = False
        await runner._turn('ambient', batch=None, direct=False)
        assert runner.resume and not runner.state.resume_reserve
        assert runner.speech_hold() is not None


@pytest.mark.asyncio
async def test_resume_of_a_direct_turn_starts_as_direct(tmp_path, monkeypatch):
    runner, store, config = _runner(tmp_path)
    with store:
        runner.resume, runner.state.resume_reserve = True, True
        calls = []

        async def ready_messages(**_):
            if len(calls) > 0:
                raise RuntimeError('stop')
            return [], None, []

        async def turn(channel, **kwargs):
            calls.append((channel, kwargs['direct']))
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        monkeypatch.setattr(runner, '_turn', turn)
        with pytest.raises(RuntimeError, match='stop'):
            await runner._run()
        assert calls == [('resume', True)]


@pytest.mark.parametrize('extra', [{'events': True}, {'notices': True}, {'audio': True}])
def test_direct_turn_with_other_sources_is_recorded_as_direct(extra):
    from len_bot.next.chat.attention import wake_channel
    base = dict(scheduled=False, notices=False, events=False, audio=False)
    assert wake_channel(**{**base, **extra}, pending='direct') == 'direct'
    assert wake_channel(**{**base, **extra}, pending='ambient') != 'direct'
    assert wake_channel(**{**base, 'events': True}, pending=None) == 'plugin'
    assert wake_channel(**{**base, 'scheduled': True}, pending='direct') == 'schedule'


@pytest.mark.asyncio
async def test_a_reaction_alone_does_not_count_as_having_spoken(tmp_path, monkeypatch):
    runner, store, config = _runner(tmp_path)
    with store:
        chat = runner.chat
        chat.direct_request, chat.turn_channel = True, 'direct'

        async def ready_messages(**_):
            return ([(1, object(), 0.0)], None, [])
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        monkeypatch.setattr(runner, 'batch', lambda pending, reason: (1, ['x']))
        monkeypatch.setattr(store, 'append_batch', lambda *args, **kwargs: None)
        chat.turn_expressions = 1  # only a reaction so far
        assert await runner.append_during_turn(False, 'turn')
        assert chat.speech_reserve
        chat.turn_messages = 1
        assert await runner.append_during_turn(False, 'turn')
        assert not chat.speech_reserve


def test_quota_hint_names_private_chats_and_task_results(tmp_path):
    from len_bot.next.chat.context import turn_state
    runner, store, config = _runner(tmp_path)
    with store:
        record_speech(store, config.scene); record_speech(store, config.scene)
        content = turn_state(config, store, now=store.now())['content']
        assert '私聊' in content and '任务结果' in content and '还能说 1 条' in content


# Review 2 (A-1 incomplete): reserve rules for input joining a running turn.

@pytest.mark.asyncio
async def test_reminder_joining_an_ambient_turn_gets_the_reserve(tmp_path, monkeypatch):
    runner, store, config = _runner(tmp_path)
    with store:
        chat = runner.chat
        chat.direct_request, chat.turn_channel = False, 'ambient'

        async def ready_messages(**_):
            return ([], None, [{'id': 1}])
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        monkeypatch.setattr(store, 'append_schedules', lambda *a, **k: None)
        assert await runner.append_during_turn(False, 'turn')
        assert 'schedule' in chat.turn_channels
        record_speech(store, config.scene); record_speech(store, config.scene)
        assert chat.speech_reserve
        chat.check_limits()  # normal limit used, the reminder still answers from the reserve


@pytest.mark.asyncio
async def test_reminder_after_revocation_gets_the_reserve_back(tmp_path, monkeypatch):
    runner, store, config = _runner(tmp_path)
    with store:
        chat = runner.chat
        chat.direct_request, chat.turn_channel = True, 'direct'
        chat.turn_messages = 1
        seq = [([(1, object(), 0.0)], None, []), ([], None, [{'id': 1}]), ([(2, object(), 0.0)], None, [])]

        async def ready_messages(**_):
            return seq.pop(0)
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        monkeypatch.setattr(runner, 'batch', lambda p, r: (1, ['x']))
        monkeypatch.setattr(store, 'append_batch', lambda *a, **k: None)
        monkeypatch.setattr(store, 'append_schedules', lambda *a, **k: None)
        assert await runner.append_during_turn(False, 'turn')
        assert chat.reserve_revoked and not chat.speech_reserve
        assert await runner.append_during_turn(False, 'turn')
        assert chat.speech_reserve and chat.turn_messages == 0
        # Once the reminder is answered, ordinary follow-ups are back at the normal limit.
        chat.turn_messages = 1
        assert await runner.append_during_turn(False, 'turn')
        assert not chat.speech_reserve


@pytest.mark.asyncio
async def test_task_result_joining_a_turn_gets_the_reserve(tmp_path, monkeypatch):
    from types import SimpleNamespace
    runner, store, config = _runner(tmp_path)
    with store:
        chat = runner.chat
        chat.direct_request, chat.turn_channel = False, 'ambient'
        chat.turn_messages = 1

        async def ready_messages(**_):
            return ([], None, [])
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        chat.tasks = SimpleNamespace(records=SimpleNamespace(pending_notices=lambda scene: [(1, 'done')]))
        monkeypatch.setattr(store, 'append_task_notices', lambda *a, **k: None)
        assert await runner.append_during_turn(False, 'turn')
        assert 'task' in chat.turn_channels and chat.speech_reserve


@pytest.mark.asyncio
@pytest.mark.parametrize('answered', [True, False])
async def test_plugin_event_after_the_answer_revokes_the_reserve(tmp_path, monkeypatch, answered):
    from len_bot.next.chat import attention
    runner, store, config = _runner(tmp_path)
    with store:
        chat = runner.chat
        chat.direct_request, chat.turn_channel = True, 'direct'
        chat.turn_messages = int(answered)

        async def ready_messages(**_):
            return ([], None, [])
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        monkeypatch.setattr(attention.PluginStore, 'pending_plugin_events',
                            lambda self, scene, include_events=True: [{'e': 1}])
        monkeypatch.setattr(store, 'append_plugin_events', lambda *a, **k: None)
        assert await runner.append_during_turn(False, 'turn')
        assert 'plugin' in chat.turn_channels
        # Before the @ is answered the event rides along; after it, it follows the normal limit.
        assert chat.speech_reserve is (not answered)


@pytest.mark.asyncio
async def test_plugin_event_with_a_reminder_keeps_the_reserve(tmp_path, monkeypatch):
    from len_bot.next.chat import attention
    runner, store, config = _runner(tmp_path)
    with store:
        chat = runner.chat
        chat.direct_request, chat.turn_channel = True, 'direct'
        chat.turn_messages = 1

        async def ready_messages(**_):
            return ([], None, [{'id': 1}])
        monkeypatch.setattr(runner, 'ready_messages', ready_messages)
        monkeypatch.setattr(store, 'append_schedules', lambda *a, **k: None)
        monkeypatch.setattr(attention.PluginStore, 'pending_plugin_events',
                            lambda self, scene, include_events=True: [{'e': 1}])
        monkeypatch.setattr(store, 'append_plugin_events', lambda *a, **k: None)
        assert await runner.append_during_turn(False, 'turn')
        assert chat.speech_reserve

