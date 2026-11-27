"""Structured replay files and real OneBot ingress validation only."""

import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from len_bot.eval.cases import (
    AwaitTurnStep, MessageStep, ObserveStep, RestartStep, SocialExpectation, load_cases,
)
from len_bot.eval.replay import observed_social, read_report
from len_bot.next.models.client import ModelReply, ToolCall
from len_bot.next.panel.routes.timeline import TimelineTurn, TurnDetail, read_turn, turn_record
from len_bot.next.persona.profile import load_persona
from len_bot.next.platform.messages import ChatMessage, Segment, Sender
from len_bot.next.storage.store import Store, encode


FIXTURE = Path(__file__).parent / "fixtures/eval/replay_cases.json"
SCENE = "onebot:group:80001"
BOT = 'onebot:90001'


def _source() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, source: dict) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(source, ensure_ascii=False, allow_nan=True), encoding="utf-8")
    return path


def test_synthetic_structured_cases_keep_original_onebot_envelopes_and_boundaries():
    source = _source()
    loaded = load_cases(FIXTURE, set_name="coherence", scene=SCENE, bot_id=BOT)

    assert loaded.format == "structured-development"
    assert loaded.source == source["source"]
    assert {"correction-restart", "ambient-observe"} <= {case.id for case in loaded.cases}
    assert [type(step) for step in loaded.cases[0].steps] == [
        MessageStep, AwaitTurnStep, RestartStep, MessageStep, AwaitTurnStep,
    ]
    assert [step.count for step in loaded.cases[0].steps if isinstance(step, AwaitTurnStep)] == [1, 2]
    assert [type(step) for step in loaded.cases[1].steps] == [MessageStep, ObserveStep]
    assert loaded.cases[0].steps[0].event == source["cases"][0]["steps"][0]["event"]
    assert loaded.cases[0].expect == source["cases"][0]["expect"]
    assert all(case.start_time is None for case in loaded.cases)
    assert all(case.initial_database is None for case in loaded.cases)


def test_initial_database_relative_path_resolves_beside_case_file_without_changing_event(tmp_path):
    source = _source()
    original_event = copy.deepcopy(source["cases"][0]["steps"][0]["event"])
    source["cases"][0]["initial_database"] = " snapshots/seed.sqlite3 "
    path = _write(tmp_path, source)

    loaded = load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)

    expected = (tmp_path / " snapshots/seed.sqlite3 ").resolve()
    assert loaded.cases[0].initial_database == expected
    assert loaded.cases[0].initial_database.is_absolute()
    assert loaded.cases[0].steps[0].event == original_event
    assert loaded.model_dump(mode="json")["cases"][0]["initial_database"] == str(expected)
    assert not expected.exists()


def test_initial_database_absolute_path_is_not_read_or_rebased(tmp_path):
    source = _source()
    absolute = (tmp_path / "separate-source.sqlite3").resolve()
    source["cases"][1]["initial_database"] = str(absolute)
    path = _write(tmp_path, source)

    loaded = load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)

    assert loaded.cases[1].initial_database == absolute
    assert loaded.cases[0].initial_database is None
    assert not absolute.exists()


@pytest.mark.parametrize("literal", ["~/seed.sqlite3", "$HOME/seed.sqlite3"])
def test_initial_database_does_not_expand_home_or_environment_tokens(tmp_path, literal):
    source = _source()
    source["cases"][0]["initial_database"] = literal
    path = _write(tmp_path, source)
    loaded = load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert loaded.cases[0].initial_database == (tmp_path / literal).resolve()


@pytest.mark.parametrize("value", ["", " \n ", 0, True, [], {}])
def test_initial_database_requires_a_nonblank_json_path_string(tmp_path, value):
    source = _source()
    source["cases"][0]["initial_database"] = value
    path = _write(tmp_path, source)

    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert "correction-restart" in str(failure.value)
    assert "initial_database" in str(failure.value)
    assert "raw=" in str(failure.value)


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows resolves a path containing NUL without raising')
def test_unresolvable_initial_database_reports_case_and_raw_path(tmp_path):
    source = _source()
    source["cases"][0]["initial_database"] = "bad\x00path.sqlite3"
    path = _write(tmp_path, source)
    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert "correction-restart" in str(failure.value)
    assert "initial_database" in str(failure.value)
    assert "raw=" in str(failure.value)


def test_explicit_case_start_time_preserves_platform_event_time_and_words(tmp_path):
    source = _source()
    original_event = copy.deepcopy(source["cases"][0]["steps"][0]["event"])
    source["cases"][0]["start_time"] = 1790000300.25
    path = _write(tmp_path, source)

    loaded = load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)

    assert loaded.cases[0].start_time == 1790000300.25
    assert loaded.cases[1].start_time is None
    assert loaded.cases[0].steps[0].event == original_event
    assert loaded.cases[0].steps[0].event["time"] == 1790000000


def test_case_start_time_accepts_integer_json_seconds_as_float(tmp_path):
    source = _source()
    original_event = copy.deepcopy(source["cases"][0]["steps"][0]["event"])
    source["cases"][0]["start_time"] = 1735689600
    path = _write(tmp_path, source)

    loaded = load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert loaded.cases[0].start_time == 1735689600.0
    assert type(loaded.cases[0].start_time) is float
    assert loaded.cases[0].steps[0].event == original_event


@pytest.mark.parametrize("value,fragment", [
    (True, "start_time"),
    ("1790000000.0", "start_time"),
    (float("nan"), "NaN"),
    (float("inf"), "Infinity"),
    (1e100, "start_time"),
])
def test_case_start_time_rejects_nonnumber_nonfinite_or_unrepresentable_values(tmp_path, value, fragment):
    source = _source()
    source["cases"][0]["start_time"] = value
    path = _write(tmp_path, source)

    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert fragment in str(failure.value)


@pytest.mark.parametrize("change,field", [
    (lambda data: data.pop("format"), "format"),
    (lambda data: data.update(format="natural-language"), "format"),
    (lambda data: data.update(source=" \n"), "source"),
    (lambda data: data.update(cases=[]), "cases"),
    (lambda data: data["cases"][0].update(id="../escape"), "cases.0.id"),
    (lambda data: data["cases"][0].update(expect=[]), "cases.0.expect"),
    (lambda data: data["cases"][0].update(expect=["  "]), "cases.0.expect"),
    (lambda data: data["cases"][0].update(steps=[]), "cases.0.steps"),
    (lambda data: data["cases"][0]["steps"][0].update(type="unknown"), "steps"),
    (lambda data: data["cases"][0]["steps"][0].update(unexpected=True), "unexpected"),
    (lambda data: data["cases"][0]["steps"][1].update(count=0), "count"),
    (lambda data: data["cases"][0]["steps"][1].update(count=True), "count"),
    (lambda data: data["cases"][1]["steps"][1].update(seconds=0), "seconds"),
    (lambda data: data["cases"][1]["steps"][1].update(seconds=-1), "seconds"),
    (lambda data: data["cases"][1]["steps"][1].update(seconds=float("inf")), "Infinity"),
    (lambda data: data["cases"][1]["steps"][1].update(seconds="0.2"), "seconds"),
])
def test_replay_case_structure_rejects_invalid_values_with_path_and_fragment(tmp_path, change, field):
    source = _source()
    change(source)
    path = _write(tmp_path, source)

    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert field in str(failure.value)
    assert "raw=" in str(failure.value)


def test_replay_case_ids_are_unique_and_set_matches_selected_name(tmp_path):
    source = _source()
    source["cases"][1]["id"] = source["cases"][0]["id"]
    path = _write(tmp_path, source)
    with pytest.raises(ValueError, match="case-insensitive paths"):
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)

    source["cases"][1]["id"] = "second-case"
    source["cases"][1]["set"] = "another-set"
    path = _write(tmp_path, source)
    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert "second-case" in str(failure.value)
    assert "another-set" in str(failure.value)
    assert str(path) in str(failure.value)


def test_case_ids_differing_only_by_case_are_rejected_for_case_insensitive_output(tmp_path):
    source = _source()
    source["cases"][0]["id"] = "A"
    source["cases"][1]["id"] = "a"
    path = _write(tmp_path, source)

    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert "cases[1]" in str(failure.value)
    assert "'A' and 'a'" in str(failure.value)


@pytest.mark.parametrize("change,fragment", [
    (lambda event: event.update(message="not an array"), "message must be a OneBot segment array"),
    (lambda event: event.pop("sender"), "sender"),
    (lambda event: event["message"].append({"type": "text", "data": {"text": 3}}), "message[2]"),
    (lambda event: event.update(group_id='onebot:89999'), "scene/self_id"),
    (lambda event: event.update(self_id='onebot:90002'), "scene/self_id"),
])
def test_replay_message_uses_actual_onebot_parser_and_configured_scene(tmp_path, change, fragment):
    source = _source()
    event = source["cases"][0]["steps"][0]["event"]
    change(event)
    original = copy.deepcopy(event)
    path = _write(tmp_path, source)

    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert "correction-restart" in str(failure.value)
    assert fragment in str(failure.value)
    assert event == original


def test_natural_language_draft_is_not_inferred_as_onebot_steps(tmp_path):
    path = _write(tmp_path, {"cases": [{"question": "自然语言草稿", "expected": "不能猜原事件"}]})
    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert "format" in str(failure.value)


def test_bad_json_and_nonstandard_constant_report_raw_fragment(tmp_path):
    path = tmp_path / "cases.json"
    path.write_bytes(b'{"format":"structured-development", "cases": [}\n')
    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert '"cases": [}' in str(failure.value)

    path.write_text('{"format":"structured-development", "source":"synthetic", "cases":NaN}', encoding="utf-8")
    with pytest.raises(ValueError) as failure:
        load_cases(path, set_name="coherence", scene=SCENE, bot_id=BOT)
    assert str(path) in str(failure.value)
    assert "NaN" in str(failure.value)


def test_public_social_cases_keep_expected_speech_and_protocol_inputs():
    path = Path(__file__).parents[1] / 'examples/replay/social.json'
    cases = load_cases(path, set_name='social', scene=SCENE, bot_id='onebot:90002')
    assert {case.social.category for case in cases.cases} == {
        'listen', 'join', 'accuracy', 'expression', 'sticker', 'preference'}
    assert sum(not case.social.speak for case in cases.cases) == 5
    assert sum(bool(case.social.sticker_files) for case in cases.cases) == 5


def test_social_expectation_rejects_unknown_metric_configuration(tmp_path):
    source = _source()
    source['cases'][0]['social'] = {'category': 'listen', 'speak': False, 'automatic_approval': True}
    with pytest.raises(ValueError, match='automatic_approval'):
        load_cases(_write(tmp_path, source), set_name='coherence', scene=SCENE, bot_id=BOT)


def test_social_expectation_reports_invalid_answer_pattern_at_config_boundary(tmp_path):
    source = _source()
    source['cases'][0]['social'] = {'category': 'accuracy', 'speak': True, 'answer_patterns': ['[']}
    with pytest.raises(ValueError, match='invalid answer pattern'):
        load_cases(_write(tmp_path, source), set_name='coherence', scene=SCENE, bot_id=BOT)


def _self_part(message_id: str, text: str, *, send_status: str) -> ChatMessage:
    return ChatMessage(
        id=message_id,
        platform='onebot',
        bot_id=BOT,
        scene=SCENE,
        platform_message_id=message_id if send_status == 'sent' else None,
        sender=Sender(BOT, '小然', None, None),
        time=1791201600.0,
        segments=[Segment('text', {'text': text})],
        reply_to=None,
        mentions_bot=False,
        is_self=True,
        send_status=send_status,
    )


def test_timeline_held_receipt_parses_status_and_expression_counts(tmp_path):
    clock = 1791201600.0
    with Store(tmp_path / 'chat.sqlite3', now=lambda: clock) as store:
        # 0-part held: pre-send guard held the whole say call, so expressions stays 0 and status is held.
        turn_zero = store.start_turn(SCENE, wake_channel='ambient')
        call_zero = store.start_call(turn_zero, 'mind', {'settings': {'api': 'openai-chat', 'model': 'm'}})
        store.end_call(
            call_zero,
            {
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{
                        'id': 'call_held_zero',
                        'type': 'function',
                        'function': {'name': 'say', 'arguments': json.dumps({'content': '本来想接一句'})},
                    }],
                },
                'finish_reason': 'tool_calls',
            },
            None,
            tokens={'input': 40, 'output': 10, 'cached': 0},
            model=('local', 'm'),
            append_to_scene=SCENE,
        )
        store.complete_tool(SCENE, 'call_held_zero', 'say 未发：发送前收到新的群消息，本条未发出。')
        store.end_turn(turn_zero, 'settled')

        # Partial held: first part sent, remaining parts held -> still counts as 1 expression and status is held.
        clock += 5.0
        turn_partial = store.start_turn(SCENE, wake_channel='ambient')
        call_partial = store.start_call(turn_partial, 'mind', {'settings': {'api': 'openai-chat', 'model': 'm'}})
        store.end_call(
            call_partial,
            {
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{
                        'id': 'call_held_partial',
                        'type': 'function',
                        'function': {'name': 'say', 'arguments': json.dumps({'content': '第一段\n第二段'})},
                    }],
                },
                'finish_reason': 'tool_calls',
            },
            None,
            tokens={'input': 50, 'output': 15, 'cached': 0},
            model=('local', 'm'),
            append_to_scene=SCENE,
        )
        partial_receipt = '第一段\n共 2 段，第 1..1 段已发出；余段因收到新消息未发：\n第二段'
        entry_seq = store.prepare_expression(SCENE, 'call_held_partial', partial_receipt)
        store.start_expression_part(
            entry_seq, _self_part('msg-part-1', '第一段', send_status='sent'),
            partial_receipt, persona_id='companion', turn_id=turn_partial,
        )
        store.end_turn(turn_partial, 'settled')

        # Failed part or interrupted prefix still takes precedence over held.
        clock += 5.0
        turn_priority = store.start_turn(SCENE, wake_channel='direct')
        call_priority = store.start_call(turn_priority, 'mind', {'settings': {'api': 'openai-chat', 'model': 'm'}})
        store.end_call(
            call_priority,
            {
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [
                        {
                            'id': 'call_failed_partial',
                            'type': 'function',
                            'function': {'name': 'say', 'arguments': json.dumps({'content': '第一段失败'})},
                        },
                        {
                            'id': 'call_interrupted',
                            'type': 'function',
                            'function': {'name': 'say', 'arguments': json.dumps({'content': '被中断'})},
                        },
                    ],
                },
                'finish_reason': 'tool_calls',
            },
            None,
            tokens={'input': 60, 'output': 18, 'cached': 0},
            model=('local', 'm'),
            append_to_scene=SCENE,
        )
        failed_receipt = '第一段失败\n共 2 段，第 1..1 段已发出；余段因收到新消息未发：\n第二段'
        failed_entry = store.prepare_expression(SCENE, 'call_failed_partial', failed_receipt)
        store.start_expression_part(
            failed_entry, _self_part('msg-part-fail', '第一段失败', send_status='failed'),
            failed_receipt, persona_id='companion', turn_id=turn_priority,
        )
        store.complete_tool(SCENE, 'call_interrupted', 'say 中断：余段因收到新消息未发')
        store.end_turn(turn_priority, 'settled')

        row_zero = store.db.execute('SELECT * FROM turns WHERE id=?', (turn_zero,)).fetchone()
        row_partial = store.db.execute('SELECT * FROM turns WHERE id=?', (turn_partial,)).fetchone()
        row_priority = store.db.execute('SELECT * FROM turns WHERE id=?', (turn_priority,)).fetchone()

        record_zero = TimelineTurn.model_validate(turn_record(store, row_zero))
        detail_zero = TurnDetail.model_validate(read_turn(store, SCENE, turn_zero))
        assert record_zero.expressions == 0
        assert detail_zero.steps[0].tools[0].status == 'held'
        assert detail_zero.steps[0].tools[0].messages == []

        record_partial = TimelineTurn.model_validate(turn_record(store, row_partial))
        detail_partial = TurnDetail.model_validate(read_turn(store, SCENE, turn_partial))
        assert record_partial.expressions == 1
        assert detail_partial.steps[0].tools[0].status == 'held'
        assert len(detail_partial.steps[0].tools[0].messages) == 1

        record_priority = TimelineTurn.model_validate(turn_record(store, row_priority))
        detail_priority = TurnDetail.model_validate(read_turn(store, SCENE, turn_priority))
        assert record_priority.expressions == 1
        assert [tool.status for tool in detail_priority.steps[0].tools] == ['error', 'interrupted']


def test_social_replay_counts_message_reaction_and_double_write_calls(tmp_path):
    db_path = tmp_path / 'chat.sqlite3'
    clock = 1791201600.0
    with Store(db_path, now=lambda: clock) as store:
        # Historical call before after_call must be ignored by this case's social metrics.
        old_turn = store.start_turn(SCENE, wake_channel='direct')
        old_call = store.start_call(old_turn, 'mind', {'settings': {'api': 'openai-chat', 'model': 'm'}})
        store.end_call(
            old_call,
            {
                'message': {
                    'role': 'assistant',
                    'content': '历史正文双写',
                    'tool_calls': [
                        {
                            'id': 'old_say',
                            'type': 'function',
                            'function': {'name': 'say', 'arguments': json.dumps({'content': '旧发言'})},
                        },
                        {
                            'id': 'old_react',
                            'type': 'function',
                            'function': {'name': 'message_reaction', 'arguments': json.dumps({'message': '999', 'emoji_id': '66'})},
                        },
                    ],
                },
                'finish_reason': 'tool_calls',
            },
            None,
            tokens={'input': 20, 'output': 10, 'cached': 0},
            model=('local', 'm'),
            append_to_scene=SCENE,
        )
        store.complete_tool(SCENE, 'old_say', '旧发言')
        store.complete_tool(SCENE, 'old_react', encode({'message': '999', 'emoji_id': '66', 'set': True, 'status': 'sent'}))
        store.end_turn(old_turn, 'settled')

        after_message = store.db.execute('SELECT COALESCE(MAX(seq),0) FROM messages').fetchone()[0]
        after_call = store.db.execute('SELECT COALESCE(MAX(id),0) FROM model_calls').fetchone()[0]

        # Reaction-only case: no self messages in messages table, one sent + one simulated + one failed reaction.
        clock += 10.0
        turn_react = store.start_turn(SCENE, wake_channel='ambient')
        call_react = store.start_call(turn_react, 'mind', {'settings': {'api': 'openai-chat', 'model': 'm'}})
        store.end_call(
            call_react,
            {
                'message': {
                    'role': 'assistant',
                    'content': '点个赞就行',
                    'tool_calls': [
                        {
                            'id': 'react_ok',
                            'type': 'function',
                            'function': {'name': 'message_reaction', 'arguments': json.dumps({'message': '1001', 'emoji_id': '76'})},
                        },
                        {
                            'id': 'react_sim',
                            'type': 'function',
                            'function': {'name': 'message_reaction', 'arguments': json.dumps({'message': '1002', 'emoji_id': '99'})},
                        },
                        {
                            'id': 'react_fail',
                            'type': 'function',
                            'function': {'name': 'message_reaction', 'arguments': json.dumps({'message': '1003', 'emoji_id': '66'})},
                        },
                    ],
                },
                'finish_reason': 'tool_calls',
            },
            None,
            tokens={'input': 30, 'output': 12, 'cached': 0},
            model=('local', 'm'),
            append_to_scene=SCENE,
        )
        store.complete_tool(SCENE, 'react_ok', encode({'message': '1001', 'emoji_id': '76', 'set': True, 'status': 'sent'}))
        store.complete_tool(SCENE, 'react_sim', encode({'message': '1002', 'emoji_id': '99', 'set': True, 'status': 'simulated'}))
        store.complete_tool(SCENE, 'react_fail', 'message_reaction 失败：ValueError: 当前场景没有平台消息 1003')
        store.end_turn(turn_react, 'settled')

    expected_speak = SocialExpectation(category='join', speak=True)
    social_react = observed_social(
        db_path,
        scene=SCENE,
        expected=expected_speak,
        turns=[],
        requests=1,
        tokens=None,
        after_message=after_message,
        after_call=after_call,
    )
    assert social_react['reactions'] == [
        {'message': '1001', 'emoji_id': '76'},
        {'message': '1002', 'emoji_id': '99'},
    ]
    assert social_react['spoke'] is True
    assert social_react['missed_reply'] is False
    assert social_react['false_interruption'] is False
    assert social_react['double_write_calls'] == 0

    expected_silent = SocialExpectation(category='listen', speak=False)
    social_interrupt = observed_social(
        db_path,
        scene=SCENE,
        expected=expected_silent,
        turns=[],
        requests=1,
        tokens=None,
        after_message=after_message,
        after_call=after_call,
    )
    assert social_interrupt['spoke'] is True
    assert social_interrupt['false_interruption'] is True

    # Add calls testing double_write_calls: only role='mind' with non-blank content and a say tool call counts.
    with Store(db_path, now=lambda: clock + 20.0) as store:
        turn_dw = store.start_turn(SCENE, wake_channel='direct')
        cases = [
            ('mind', '内部重复写一遍', [{'id': 'dw_1', 'type': 'function', 'function': {'name': 'say', 'arguments': '{"content":"好的"}'}}]),
            ('mind', '   \n\t  ', [{'id': 'dw_ws', 'type': 'function', 'function': {'name': 'say', 'arguments': '{"content":"仅空白不算"}'}}]),
            ('mind', '单纯想法不调用 say', []),
            ('mind', '再次双写', [{'id': 'dw_2', 'type': 'function', 'function': {'name': 'say', 'arguments': '{"content":"再来一句"}'}}]),
            ('recap', '压缩角色不算', [{'id': 'dw_recap', 'type': 'function', 'function': {'name': 'say', 'arguments': '{"content":"忽略"}'}}]),
        ]
        for role, content, calls in cases:
            cid = store.start_call(turn_dw, role, {'settings': {'api': 'openai-chat', 'model': 'm'}})
            store.end_call(
                cid,
                {'message': {'role': 'assistant', 'content': content, 'tool_calls': calls}, 'finish_reason': 'tool_calls' if calls else 'stop'},
                None,
                tokens={'input': 20, 'output': 10, 'cached': 0},
                model=('local', 'm'),
                append_to_scene=SCENE if role == 'mind' else None,
            )
            if role == 'mind':
                for call in calls:
                    store.complete_tool(SCENE, call['id'], '已发送')
        store.end_turn(turn_dw, 'settled')

    social_dw = observed_social(
        db_path,
        scene=SCENE,
        expected=expected_speak,
        turns=[],
        requests=5,
        tokens=None,
        after_message=after_message,
        after_call=after_call,
    )
    assert social_dw['double_write_calls'] == 2

    # Verify read_report aggregates double_write_calls across cases while preserving all existing keys.
    run_dir = tmp_path / 'run'
    (run_dir / 'case-a' / '1').mkdir(parents=True)
    (run_dir / 'case-b' / '1').mkdir(parents=True)
    (run_dir / 'case-legacy' / '1').mkdir(parents=True)
    (run_dir / 'run.json').write_text(json.dumps({
        'id': '20261126T000000.000000Z',
        'plan': {'set': 'social', 'case_ids': ['case-a', 'case-b', 'case-legacy'], 'repetitions': 1},
    }), encoding='utf-8')
    (run_dir / 'annotations.json').write_text(json.dumps([
        {'case_id': 'case-a', 'repeat': 1, 'verdict': 'pass', 'reason': 'ok'},
        {'case_id': 'case-b', 'repeat': 1, 'verdict': 'pass', 'reason': 'ok'},
        {'case_id': 'case-legacy', 'repeat': 1, 'verdict': 'unreviewed', 'reason': ''},
    ]), encoding='utf-8')
    for name, social_payload in [
        ('case-a', social_dw),
        ('case-b', {**social_react, 'double_write_calls': 1}),
        ('case-legacy', {k: v for k, v in social_react.items() if k not in {'reactions', 'double_write_calls'}}),
    ]:
        (run_dir / name / '1' / 'result.json').write_text(json.dumps({
            'case_id': name,
            'script_completed': True,
            'usage': [],
            'tokens': None,
            'social': social_payload,
        }), encoding='utf-8')

    report = read_report(run_dir)
    assert {'run', 'quality', 'scored', 'social', 'double_write_calls', 'pass_rate', 'tokens', 'results', 'notice'} <= report.keys()
    assert report['double_write_calls'] == 3
    assert len(report['social']) == 3
    by_case = {item['case_id']: item for item in report['social']}
    assert by_case['case-a']['double_write_calls'] == 2
    assert by_case['case-b']['reactions'] == social_react['reactions']


def test_compare_voice_modes_run_v3_marks_double_write_when_map_reply_has_text_and_say():
    spec = importlib.util.spec_from_file_location(
        'compare_voice_modes', Path(__file__).parents[1] / 'scripts/compare_voice_modes.py',
    )
    assert spec is not None and spec.loader is not None
    compare_voice_modes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compare_voice_modes)

    persona = load_persona(Path(__file__).parents[1] / 'examples/personas/companion')
    tools = compare_voice_modes.build_voice_tools(persona)

    class _StubModel:
        def __init__(self, replies: list[ModelReply]) -> None:
            self._replies = iter(replies)

        async def complete(self, messages, call_tools):
            return next(self._replies)

    draft_reply = ModelReply(
        message={'role': 'assistant', 'content': '好的，我来记一下'},
        text='好的，我来记一下',
        tool_calls=[],
        finish_reason='stop',
        usage=None,
        token_usage=None,
    )
    say_call = ToolCall(id='call_say_1', name='say', arguments={'content': '好的，我来记一下'})
    double_write_map_reply = ModelReply(
        message={'role': 'assistant', 'content': '好的，我来记一下'},
        text='好的，我来记一下',
        tool_calls=[say_call],
        finish_reason='tool_calls',
        usage=None,
        token_usage=None,
    )
    clean_map_reply = ModelReply(
        message={'role': 'assistant', 'content': '   '},
        text='   ',
        tool_calls=[say_call],
        finish_reason='tool_calls',
        usage=None,
        token_usage=None,
    )

    result_dw = asyncio.run(compare_voice_modes.run_v3(
        _StubModel([draft_reply, double_write_map_reply]),
        persona=persona,
        scene=SCENE,
        bot_id=BOT,
        context_text='[群友]: 记得帮我记一下',
        tools=tools,
    ))
    assert result_dw['double_write'] is True
    assert result_dw['action'] == 'say'
    assert result_dw['output_text'] == '好的，我来记一下'

    result_clean = asyncio.run(compare_voice_modes.run_v3(
        _StubModel([draft_reply, clean_map_reply]),
        persona=persona,
        scene=SCENE,
        bot_id=BOT,
        context_text='[群友]: 记得帮我记一下',
        tools=tools,
    ))
    assert result_clean['double_write'] is False
