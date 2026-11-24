"""Protocol checks against redacted real provider responses.

The tool fixture came from .runtime/supplier-validation-20260908/response-02.json.
The text fixture came from .runtime/next-eval/current-model-20260926/response-02.json;
its opaque response ID and reasoning content were redacted, while null field
shapes and usage were retained.
"""

import asyncio
import json
from math import ceil
from pathlib import Path
from string import Template

import pytest
from pydantic import ValidationError

from len_bot.next.models.client import (
    ChatModel,
    ModelHTTPError,
    ModelOutputLimitError,
    ModelProtocolError,
    ModelSettings,
    parse_chat_completion,
)
from len_bot.next.models.projection import project_old_results
from len_bot.next.prompt_files import read_prompt
from len_bot.next.storage.codec import encode


RECORDED_RESPONSE = Path(__file__).parent / "fixtures/next/model/response-02.json"
RECORDED_TEXT_RESPONSE = Path(__file__).parent / "fixtures/next/model/response-text.json"


def recorded_response() -> dict:
    return json.loads(RECORDED_RESPONSE.read_text())


def recorded_text_response() -> dict:
    return json.loads(RECORDED_TEXT_RESPONSE.read_text())


def test_recorded_tool_call_keeps_native_continuation_and_usage():
    body = recorded_response()
    reply = parse_chat_completion(body)

    assert reply.message == body["choices"][0]["message"]
    assert reply.message is not body["choices"][0]["message"]
    assert reply.text == ""
    assert reply.finish_reason == "tool_calls"
    assert [(call.id, call.name, call.arguments) for call in reply.tool_calls] == [
        (
            "call_13d8afaf8eb845bc90f2b5fb231b97d5",
            "read_validation_document",
            {},
        )
    ]
    assert reply.usage == body["usage"]
    assert reply.usage["completion_tokens_details"]["reasoning_tokens"] == 374
    assert (reply.token_usage.prompt_tokens, reply.token_usage.completion_tokens,
            reply.token_usage.cached_tokens) == (3946, 388, 0)
    assert body["usage"]["total_tokens"] == 4333  # Retained, not forced to match the components.


def test_recorded_response_with_injected_native_extension_keeps_it_unchanged():
    body = recorded_response()
    message = body["choices"][0]["message"]
    message["provider_continuation"] = {"signature": "replay-only", "blocks": [None, 1]}
    reply = parse_chat_completion(body)
    assert reply.message == message
    assert reply.message["provider_continuation"] is not message["provider_continuation"]


def test_recorded_text_response_accepts_null_tool_calls_and_preserves_native_extras():
    body = recorded_text_response()
    message = body["choices"][0]["message"]
    assert message["tool_calls"] is None
    assert message["reasoning_content"] == "[redacted]"

    reply = parse_chat_completion(body)
    assert reply.text == message["content"]
    assert reply.tool_calls == []
    assert reply.finish_reason == "stop"
    assert reply.usage == body["usage"]
    assert (reply.token_usage.prompt_tokens, reply.token_usage.completion_tokens,
            reply.token_usage.cached_tokens) == (1351, 382, None)
    assert reply.message == message
    assert reply.message is not message


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda body: body["choices"][0].update(finish_reason="length"), "finish_reason"),
        (
            lambda body: body["choices"][0]["message"]["tool_calls"][0]["function"].update(
                arguments='{"offset":'
            ),
            "tool arguments",
        ),
        (
            lambda body: body["choices"][0]["message"]["tool_calls"][0]["function"].update(
                arguments='{"offset":NaN}'
            ),
            "non-standard JSON constant",
        ),
        (
            lambda body: body["choices"][0]["message"]["tool_calls"][0]["function"].update(
                arguments='{"offset":Infinity}'
            ),
            "non-standard JSON constant",
        ),
    ],
)
def test_recorded_response_fault_injections_fail_before_tool_execution(change, reason):
    body = recorded_response()
    change(body)
    with pytest.raises(ModelProtocolError) as failure:
        parse_chat_completion(body)
    assert reason in str(failure.value)
    if not isinstance(failure.value, ModelOutputLimitError):
        assert "response fragment:" in str(failure.value)
    assert failure.value.response == body
    assert failure.value.response is not body
    assert failure.value.usage == body["usage"]
    assert failure.value.token_usage.prompt_tokens == body["usage"]["prompt_tokens"]


def test_missing_usage_in_recorded_response_is_unknown_not_zero():
    body = recorded_response()
    del body["usage"]
    reply = parse_chat_completion(body)
    assert reply.usage is None
    assert reply.token_usage is None


@pytest.mark.parametrize('field', ['prompt_cache_hit_tokens', 'cache_read_input_tokens'])
def test_gateway_cached_usage_falls_back_only_when_standard_count_is_unknown(field):
    body = recorded_response()
    body['usage'][field] = 32
    assert parse_chat_completion(body).token_usage.cached_tokens == 0
    del body['usage']['prompt_tokens_details']
    assert parse_chat_completion(body).token_usage.cached_tokens == 32
    body['usage'][field] = -1
    with pytest.raises(ModelProtocolError, match=field):
        parse_chat_completion(body)


def test_old_web_results_fold_at_block_boundaries():
    page = {'document': 'doc-1', 'text': 'original body ' * 100}
    content = Template(read_prompt('next_web_read.md')).substitute(result=encode(page))
    tool = {'role': 'tool', 'tool_call_id': 'read-1', 'content': content}
    call = {'role': 'assistant', 'content': None, 'tool_calls': [
        {'type': 'function', 'id': 'read-1', 'function': {'name': 'web_read', 'arguments': '{}'}}]}
    history = [(1, call), (2, tool)]
    keep = ceil(len(encode(tool).encode()) / 3)
    short = [*history, (3, {'role': 'user', 'content': '还有呢？'})]
    longer = [*short, (4, {'role': 'user', 'content': 'x' * (keep * 2)})]
    assert project_old_results(history, keep) == history
    assert project_old_results(short, keep) == short
    folded = project_old_results(longer, keep)[1][1]['content']
    assert page['document'] in folded and page['text'] not in folded
    assert project_old_results(history, 0)[1][1]['content'] == folded
    assert tool['content'] == content


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda usage: usage.update(prompt_tokens=True), "prompt_tokens"),
        (lambda usage: usage.update(prompt_tokens=-1), "prompt_tokens"),
        (lambda usage: usage.update(completion_tokens=1.5), "completion_tokens"),
        (lambda usage: usage.update(completion_tokens="388"), "completion_tokens"),
        (lambda usage: usage["prompt_tokens_details"].update(cached_tokens=3947), "cached_tokens"),
        (lambda usage: usage["prompt_tokens_details"].update(cached_tokens=False), "cached_tokens"),
        (lambda usage: usage.update(prompt_tokens_details=[]), "prompt_tokens_details"),
    ],
)
def test_recorded_usage_faults_reject_without_losing_raw_response(change, field):
    body = recorded_response()
    change(body["usage"])
    with pytest.raises(ModelProtocolError) as failure:
        parse_chat_completion(body)
    assert field in str(failure.value)
    assert failure.value.response == body
    assert failure.value.usage == body["usage"]
    assert failure.value.token_usage is None


def test_recorded_usage_null_fields_remain_unknown_without_alias_guessing():
    body = recorded_response()
    body["usage"]["prompt_tokens"] = None
    body["usage"]["completion_tokens"] = None
    body["usage"]["prompt_tokens_details"] = None
    reply = parse_chat_completion(body)
    assert (reply.token_usage.prompt_tokens, reply.token_usage.completion_tokens,
            reply.token_usage.cached_tokens) == (None, None, None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api", "anthropic-messages"),
        ("base_url", ""),
        ("api_key", " "),
        ("model", ""),
        ("reasoning_effort", " "),
        ("max_output_tokens", 0),
        ("timeout_seconds", 0),
    ],
)
def test_model_settings_reject_invalid_config_at_named_field(field, value):
    source = {
        "api": "openai-chat",
        "base_url": "http://127.0.0.1:8080/v1",
        "api_key": "replay-only",
        "model": "recorded-model",
    }
    source[field] = value
    with pytest.raises(ValidationError) as failure:
        ModelSettings.model_validate(source)
    assert field in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["native", "omit-reasoning"])
async def test_loopback_replay_sends_native_tool_continuation_without_retry(tmp_path, policy):
    recorded = recorded_response()
    recorded_text = recorded_text_response()
    requests = []
    recorded["choices"][0]["message"]["provider_continuation"] = {"signature": "synthetic-opaque"}

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        headers = await reader.readuntil(b"\r\n\r\n")
        request_line, *header_lines = headers.decode("ascii").split("\r\n")
        fields = {
            key.lower(): value.strip()
            for line in header_lines
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        payload = json.loads(await reader.readexactly(int(fields["content-length"])))
        requests.append((request_line, fields, payload))
        body = json.dumps(recorded if len(requests) == 1 else recorded_text).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(
            api="openai-chat", base_url=f"http://127.0.0.1:{port}/v1",
            api_key="replay-only", model="recorded-model", reasoning_effort="high",
        )
        assert settings.temperature == 0.6
        assert settings.max_output_tokens == 1024
        assert settings.timeout_seconds == 60
        tools = [{"type": "function", "function": {"name": "read_validation_document", "parameters": {"type": "object"}}}]
        messages = [{"role": "user", "content": "Read the document"}]
        from len_bot.next.config import LabConfig
        from len_bot.next.storage.store import Store
        from len_bot.next.models.request import request_model
        config = LabConfig.model_validate_json(json.dumps({
            "mode": "isolated", "scene": "onebot:group:80001", "bot_id": 'onebot:90001', "timezone": "UTC",
            "database": str(tmp_path / "chat.sqlite3"), "persona": str(tmp_path / "persona"),
            "models": {"providers": {"fixture": {"api": settings.api, "base_url": settings.base_url,
                                               "api_key": settings.api_key}},
                       "roles": {"mind": {"provider": "fixture", "model": settings.model,
                           "context_window_tokens": 200000, "history_policy": policy,
                           "reasoning_effort": "high"}}},
        }))
        async with ChatModel(settings) as model:
            with Store(config.database) as store:
                turn = store.start_turn(config.scene)
                first = await request_model(config, store, model, messages, tools,
                                            scene=config.scene, role="mind", turn_id=turn)
                continuation = messages + [first.message, {
                    "role": "tool", "tool_call_id": first.tool_calls[0].id, "content": "document excerpt",
                }]
                second = await request_model(config, store, model, continuation, tools,
                    scene=config.scene, role="mind", turn_id=turn, output_tokens=512)
                await request_model(config, store, model, continuation + [second.message, {
                    "role": "user", "content": "continue",
                }], tools, scene=config.scene, role="mind", turn_id=turn)
                raw = json.loads(store.db.execute("SELECT response FROM model_calls ORDER BY id LIMIT 1").fetchone()[0])
                assert raw["raw"] == recorded
        assert settings.max_output_tokens == 1024

    assert len(requests) == 3
    assert all(line == "POST /v1/chat/completions HTTP/1.1" for line, _, _ in requests)
    assert all(headers["authorization"] == "Bearer replay-only" for _, headers, _ in requests)
    first_payload = requests[0][2]
    assert first_payload["stream"] is False
    assert first_payload["model"] == "recorded-model"
    assert first_payload["temperature"] == 0.6
    assert first_payload["max_completion_tokens"] == 1024
    assert requests[1][2]["max_completion_tokens"] == 512
    assert requests[2][2]["max_completion_tokens"] == 1024
    assert first_payload["reasoning_effort"] == "high"
    assert first_payload["tools"] == tools
    native = recorded["choices"][0]["message"]
    assert requests[1][2]["messages"][1] == {key: value for key, value in native.items()
        if policy == "native" or key != "reasoning_content"}
    assert requests[1][2]["messages"][1]["provider_continuation"] == {"signature": "synthetic-opaque"}
    if policy == "omit-reasoning":
        assert all(headers["session-id"] == requests[0][1]["session-id"] for _, headers, _ in requests)
    else:
        assert all("session-id" not in headers for _, headers, _ in requests)
    assert requests[1][2]["messages"][2]["tool_call_id"] == first.tool_calls[0].id
    native = recorded_text["choices"][0]["message"]
    assert requests[2][2]["messages"][-2] == {key: value for key, value in native.items()
        if policy == "native" or key != "reasoning_content"}
    assert requests[2][2]["messages"][-2]["tool_calls"] is None
    if policy == "native":
        assert requests[2][2]["messages"][-2]["reasoning_content"] == "[redacted]"
    else:
        assert "reasoning_content" not in requests[2][2]["messages"][-2]


@pytest.mark.asyncio
async def test_loopback_http_error_propagates_original_body_without_retry():
    requests = 0
    payloads = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        nonlocal requests
        headers = await reader.readuntil(b"\r\n\r\n")
        for line in headers.decode("ascii").split("\r\n"):
            if line.lower().startswith("content-length:"):
                payloads.append(json.loads(await reader.readexactly(int(line.split(":", 1)[1]))))
        requests += 1
        body = b'{"error":{"message":"replay rate limit"}}'
        writer.write(
            b"HTTP/1.1 429 Too Many Requests\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(
            api="openai-chat", base_url=f"http://127.0.0.1:{port}/v1",
            api_key="replay-only", model="recorded-model",
        )
        async with ChatModel(settings) as model:
            with pytest.raises(ModelHTTPError, match="请求受限") as failure:
                await model.complete([{"role": "user", "content": "hello"}], [])
    assert "replay rate limit" in failure.value.response["detail"]
    assert "HTTP 429: replay rate limit" in str(failure.value)
    assert failure.value.status == 429 and failure.value.retryable
    assert failure.value.body == failure.value.response['detail']
    assert requests == 1
    assert "reasoning_effort" not in payloads[0]


def test_http_error_plain_text_is_printable_and_bounded():
    detail = 'busy\r\n\tupstream\x00' + 'x' * 300
    error = ModelHTTPError(502, detail)
    assert 'HTTP 502: ' + ('busy upstream ' + 'x' * 300)[:240] + '）' in str(error)
    assert error.body == detail and error.retryable
    empty = ModelHTTPError(400, '')
    assert 'HTTP 400）' in str(empty) and not empty.retryable


@pytest.mark.asyncio
async def test_configured_retry_resends_same_request_after_transient_errors():
    statuses = [b"429 Too Many Requests", b"503 Service Unavailable", b"200 OK"]
    payloads = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        headers = await reader.readuntil(b"\r\n\r\n")
        for line in headers.decode("ascii").split("\r\n"):
            if line.lower().startswith("content-length:"):
                payloads.append(json.loads(await reader.readexactly(int(line.split(":", 1)[1]))))
        status = statuses[len(payloads) - 1]
        body = json.dumps(recorded_text_response()).encode() if status.startswith(b"200") else b'{"error":"busy"}'
        writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\n"
                     + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(api="openai-chat", base_url=f"http://127.0.0.1:{port}/v1", api_key="replay-only",
                                 model="recorded-model", retry_delays_seconds=(0, 0, 0))
        retried = []
        async with ChatModel(settings) as model:
            reply = await model.complete([{"role": "user", "content": "hello"}], [],
                                         on_retry=lambda: retried.append(len(payloads)))
    assert reply.text
    assert len(payloads) == 3 and payloads[0] == payloads[1] == payloads[2]
    assert retried == [1, 2]


@pytest.mark.asyncio
async def test_loopback_truncated_recorded_json_has_unknown_usage():
    recorded_bytes = RECORDED_RESPONSE.read_bytes()
    truncated = recorded_bytes[:recorded_bytes.index(b'"usage"')]

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        headers = await reader.readuntil(b"\r\n\r\n")
        for line in headers.decode("ascii").split("\r\n"):
            if line.lower().startswith("content-length:"):
                await reader.readexactly(int(line.split(":", 1)[1]))
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(truncated)}\r\nConnection: close\r\n\r\n".encode()
            + truncated
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        settings = ModelSettings(
            api="openai-chat", base_url=f"http://127.0.0.1:{port}/v1",
            api_key="replay-only", model="recorded-model",
        )
        async with ChatModel(settings) as model:
            with pytest.raises(ModelProtocolError, match="Invalid chat completion JSON") as failure:
                await model.complete([{"role": "user", "content": "hello"}], [])
    assert failure.value.usage is None
    assert failure.value.response == truncated.decode()


def test_recorded_summary_code_fence_is_not_silently_repaired():
    from len_bot.next.memory.summary import parse_summary
    recorded = json.loads((RECORDED_RESPONSE.parent / 'summary-fenced-response.json').read_text())
    reply = parse_chat_completion({'choices': [recorded]})
    with pytest.raises(ValueError, match='Invalid memory summary response.*response fragment'):
        parse_summary(reply)


def test_old_large_readonly_tool_results_fold_with_quantized_stability():
    search_payload = {
        'provider': 'tavily',
        'query': 'LenBot 部署说明',
        'fetched_at': '2026-10-01T08:00Z',
        'results': [
            {
                'title': '部署指南',
                'url': 'https://example.invalid/deploy',
                'snippet': '详细部署步骤说明' * 40,
                'published_at': '2026-09-30',
            },
            {
                'title': '常见问题',
                'url': 'https://example.invalid/faq',
                'snippet': '常见问题排查说明' * 40,
            },
        ],
        'top_page': {
            'document': 42,
            'url': 'https://example.invalid/deploy',
            'title': '部署指南',
            'total_chars': 3000,
            'next_offset': 2000,
            'text': '这是完整网页正文内容' * 120,
        },
    }
    search_content = Template(read_prompt('next_web_search.md')).substitute(
        result=json.dumps(search_payload, ensure_ascii=False))

    recall_body = (
        '2026-09-20｜UTC +0000\n'
        '12:00:00 "小明"(onebot:1001) [id="m-101"，record=11]\n'
        + '  ' + ('上周讨论过月报字段口径' * 70) + '\n'
        '12:05:00 "小红"(onebot:1002) [id="m-102"，record=12]\n'
        + '  ' + ('确认需要保留原始明细表' * 70)
    )
    recall_content = Template(read_prompt('next_recall.md')).substitute(
        summary='search（最新优先） 第 1 页，共 2 条。没有下一页了。', result=recall_body)

    knowledge_payload = {
        'action': 'search',
        'query': '端口 配置',
        'offset': 0,
        'next_offset': None,
        'matches': [
            {
                'scope': 'chat',
                'filename': 'ops/guide.md',
                'heading': ['部署', '端口'],
                'page': 3,
                'offset': 512,
                'matched': ['端口'],
                'text': '默认面板端口与反向代理配置原文内容' * 80,
            },
        ],
    }
    knowledge_content = Template(read_prompt('next_knowledge.md')).substitute(
        persona_id='p1', persona_name='小然', chat='本群',
        result=json.dumps(knowledge_payload, ensure_ascii=False))

    forward_text = '\n'.join([
        '[1] [2026-09-20 10:00:00+08:00] 小明(onebot:1001)：',
        '  ' + ('第一条转发消息正文' * 40),
        '[2] [2026-09-20 10:02:00+08:00] 小红(onebot:1002)：',
        '  ' + ('第二条转发消息正文' * 40),
        '[3] [2026-09-20 10:05:00+08:00] 小明(onebot:1001)：',
        '  ' + ('第三条转发消息正文' * 40),
        '[4] [2026-09-20 10:08:00+08:00] 小刚(onebot:1003)：',
        '  ' + ('第四条超长隐藏内容' * 40),
    ])
    forward_payload = {
        'message': 'm-900', 'forward': 1, 'forward_id': 'fwd-1',
        'top_level_items': 4, 'offset': 0, 'total_chars': len(forward_text),
        'next_offset': None, 'text': forward_text,
    }
    forward_content = Template(read_prompt('next_forward.md')).substitute(
        scene='onebot:group:80001', result=encode(forward_payload)).strip()

    small_search = Template(read_prompt('next_web_search.md')).substitute(
        result=json.dumps({'provider': 'tavily', 'query': '短查', 'results': [
            {'title': '短标题', 'url': 'https://example.invalid/s', 'snippet': '短摘要'}]}, ensure_ascii=False))
    malformed_knowledge = 'not valid json ' * 100

    assert all(len(c) > 1200 for c in (search_content, recall_content, knowledge_content,
                                       forward_content, malformed_knowledge))
    assert len(small_search) <= 1200

    assistant = {
        'role': 'assistant', 'content': None,
        'tool_calls': [
            {'type': 'function', 'id': 'c-search', 'function': {
                'name': 'web_search', 'arguments': json.dumps({'query': 'LenBot 部署说明', 'count': 2}, ensure_ascii=False)}},
            {'type': 'function', 'id': 'c-recall', 'function': {
                'name': 'recall_chat', 'arguments': json.dumps({'action': 'search', 'query': '月报'}, ensure_ascii=False)}},
            {'type': 'function', 'id': 'c-know', 'function': {
                'name': 'knowledge', 'arguments': json.dumps({'action': 'search', 'query': '端口 配置'}, ensure_ascii=False)}},
            {'type': 'function', 'id': 'c-fwd', 'function': {
                'name': 'open_forward', 'arguments': json.dumps({'message': 'm-900'}, ensure_ascii=False)}},
            {'type': 'function', 'id': 'c-small', 'function': {
                'name': 'web_search', 'arguments': json.dumps({'query': '短查'}, ensure_ascii=False)}},
            {'type': 'function', 'id': 'c-bad', 'function': {
                'name': 'knowledge', 'arguments': json.dumps({'action': 'search', 'query': '坏'}, ensure_ascii=False)}},
        ],
    }
    history = [
        (1, assistant),
        (2, {'role': 'tool', 'tool_call_id': 'c-search', 'content': search_content}),
        (3, {'role': 'tool', 'tool_call_id': 'c-recall', 'content': recall_content}),
        (4, {'role': 'tool', 'tool_call_id': 'c-know', 'content': knowledge_content}),
        (5, {'role': 'tool', 'tool_call_id': 'c-fwd', 'content': forward_content}),
        (6, {'role': 'tool', 'tool_call_id': 'c-small', 'content': small_search}),
        (7, {'role': 'tool', 'tool_call_id': 'c-bad', 'content': malformed_knowledge}),
    ]
    total_tokens = sum(ceil(len(encode(m).encode('utf-8')) / 3) for _, m in history)
    keep = total_tokens + 200

    # Within keep_recent_tokens: nothing folds.
    assert project_old_results(history, keep) == history
    # Small follow-up that does not cross the quantized step boundary keeps the prefix identical.
    with_small = [*history, (8, {'role': 'user', 'content': '继续聊聊'})]
    assert project_old_results(with_small, keep) == with_small

    # Push past cutoff into the middle of a quantized step so all early entries fold cleanly.
    step = keep // 2
    pushed = [*with_small, (9, {'role': 'user', 'content': 'x' * ((2 * step + step // 2) * 3)})]
    projected = project_old_results(pushed, keep)
    # Adding another small turn inside the same step leaves the folded prefix byte-for-byte stable.
    pushed_more = [*pushed, (10, {'role': 'user', 'content': '好的收到'})]
    assert project_old_results(pushed_more, keep)[:len(pushed)] == projected

    folded_search = projected[1][1]['content']
    assert 'web_read(document=...)' in folded_search and 'web_search' in folded_search
    search_json = json.loads(folded_search.splitlines()[0])
    assert search_json['query'] == 'LenBot 部署说明'
    assert search_json['top_page']['document'] == 42
    assert 'text' not in search_json['top_page']
    assert len(search_json['results']) == 2
    assert search_payload['top_page']['text'] not in folded_search

    folded_recall = projected[2][1]['content']
    assert 'recall_chat' in folded_recall
    recall_json = json.loads(folded_recall.splitlines()[0])
    assert recall_json['arguments'] == {'action': 'search', 'query': '月报'}
    assert recall_json['count'] == 2
    assert [m['record'] for m in recall_json['messages']] == [11, 12]
    assert [m['platform_message_id'] for m in recall_json['messages']] == ['m-101', 'm-102']
    assert len(folded_recall) < len(recall_content)

    folded_know = projected[3][1]['content']
    assert 'knowledge' in folded_know
    know_json = json.loads(folded_know.splitlines()[0])
    assert know_json['count'] == 1
    assert know_json['matches'][0]['filename'] == 'ops/guide.md'
    assert know_json['matches'][0]['offset'] == 512
    assert know_json['matches'][0]['page'] == 3
    assert 'text' not in know_json['matches'][0]
    assert len(folded_know) < len(knowledge_content)

    folded_fwd = projected[4][1]['content']
    assert 'open_forward' in folded_fwd
    fwd_json = json.loads(folded_fwd.splitlines()[0])
    assert fwd_json['item_count'] == 4
    assert fwd_json['senders'] == ['小明(onebot:1001)', '小红(onebot:1002)', '小刚(onebot:1003)']
    assert fwd_json['time_range'] == {'start': '2026-09-20 10:00:00+08:00', 'end': '2026-09-20 10:08:00+08:00'}
    assert len(fwd_json['previews']) == 3
    assert '第四条超长隐藏内容' not in folded_fwd

    # Small result (<= 1200 chars) and unparseable result stay untouched.
    assert projected[5][1]['content'] == small_search
    assert projected[6][1]['content'] == malformed_knowledge

    # Unconsumed trailing tool outputs larger than keep_recent_tokens must NEVER fold before assistant reads them.
    assert project_old_results(history, 50) == history


def test_recap_source_extracts_ticket_anchors_and_preserves_plain_sessions():
    from len_bot.next.chat.recap import extract_ticket_anchors, recap_source

    plain_entries = [
        (1, {'role': 'user', 'content': '大家好'}),
        (2, {'role': 'assistant', 'content': '你好呀'}),
    ]
    expected_plain = encode({
        '已有回想': '之前的回想',
        '新增旧会话': [
            {'role': 'user', 'content': '大家好'},
            {'role': 'assistant', 'content': '你好呀'},
        ],
    })
    assert extract_ticket_anchors(plain_entries) == []
    assert recap_source('之前的回想', plain_entries) == expected_plain

    done_notice = (
        '[任务执行结束] #7；请求人 onebot:1001；导出月报\n含华东分部\n'
        + json.dumps({
            'status': 'done',
            'summary': '已生成月报',
            'error': None,
            'files': [{'id': 3, 'name': '月报.xlsx', 'size': 2048}],
            'can_continue': True,
        }, ensure_ascii=False)
    )
    question_notice = (
        '[任务提问] #8；请求人 onebot:1002\n'
        + json.dumps({'id': 'q-1', 'title': '请选择导出范围', 'method': 'select'}, ensure_ascii=False)
    )
    task_entries = [
        *plain_entries,
        (3, {'role': 'user', 'content': done_notice}),
        (4, {'role': 'user', 'content': question_notice}),
    ]
    parsed = json.loads(recap_source(None, task_entries))
    assert parsed['涉及工单与交付标识'] == [
        {
            'task_id': 7,
            'requester': 'onebot:1001',
            'goal': '导出月报 含华东分部',
            'status': 'done',
            'can_continue': True,
            'files': [{'id': 3, 'name': '月报.xlsx'}],
        },
        {
            'task_id': 8,
            'requester': 'onebot:1002',
            'question_id': 'q-1',
            'question_title': '请选择导出范围',
        },
    ]
