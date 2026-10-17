"""One-task, byte-transparent native model stream boundary.

The caller owns the task record and the HTTP route. This object owns the
configured upstream binding (plus its fallbacks), its task token, and actual
model-call limits. The container always speaks to the primary binding; a
fallback is tried only when the current candidate fails before any response
byte reaches the container.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
import hmac
import httpx
import json
import math
from typing import Any


from ..chat.recap import estimate_text_request
from ..models.client import ModelProtocolError, ModelSettings
from ..models.failover import FAILOVER_STATUS, ProviderHealth
from ..models.slots import ModelSlots
from ..models.tokens import token_record
from .worker_stream import ChatCompletionStream
from .native_stream import NativeStream
from ..models.providers import http_client, auth_headers
from urllib.parse import quote
from ..runtime.logs import redact, redact_record

REJECTED_HTTP_STATUSES = frozenset({400, 401, 403, 404, 405, 409, 413, 415, 422, 429})


class WorkerModelError(RuntimeError):
    """One worker model call was refused or did not complete."""


class _FailedOver(Exception):
    """One candidate failed before streaming; the proxy tries the next one."""


@dataclass(frozen=True, slots=True)
class Limits:
    max_calls: int
    max_request_bytes: int
    max_response_bytes: int
    # Input plus output tokens left for this execution; None means no token cap.
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("max_calls", "max_request_bytes", "max_response_bytes"):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_tokens is not None and self.max_tokens < 0:
            raise ValueError("max_tokens must be a nonnegative integer or null")


@dataclass(frozen=True, slots=True)
class WorkerResponse:
    status: int
    headers: dict[str, str]
    body: AsyncIterator[bytes]


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"JSON number is not finite: {value[:100]}")
    return number


class WorkerModelProxy:
    def __init__(
        self,
        settings: ModelSettings,
        provider: str,
        context_window_tokens: int,
        token: str,
        limits: Limits,
        *,
        slots: ModelSlots | None = None,
        scene: str | None = None,
        start_call: Callable[[dict[str, Any]], int],
        finish_call: Callable[[int, dict[str, Any]], None],
        fallbacks: Sequence[tuple[str, ModelSettings]] = (),
        health: ProviderHealth | None = None,
        role: str = "worker",
    ):
        if not provider.strip() or not token:
            raise ValueError("provider and task token must not be empty")
        if context_window_tokens <= 0:
            raise ValueError("context_window_tokens must be positive")
        self.settings = settings
        self.provider = provider
        self.context_window_tokens = context_window_tokens
        self.limits = limits
        self.slots = slots
        self.scene = scene
        self.start_call = start_call
        self.finish_call = finish_call
        self._token = token
        self._entered = False
        self._closed = False
        self._busy = False
        self._calls = 0
        self._spent = 0
        self._tokens_unknown = False
        self._active_task: asyncio.Task[Any] | None = None
        for _, candidate in fallbacks:
            if candidate.api != settings.api:
                raise ValueError("worker fallbacks must use the primary binding's API protocol")
        self.role = role
        self.candidates = [(provider, settings), *fallbacks]
        self.health = health if fallbacks else None
        if self.health is not None:
            self.health.register(role, [(name, candidate.model) for name, candidate in self.candidates])
        self._clients = [http_client(base_url=candidate.base_url, api_key=candidate.api_key, api=candidate.api,
                                     timeout_seconds=candidate.timeout_seconds, proxy=candidate.proxy)
                         for _, candidate in self.candidates]
        self._client = self._clients[0]

    @property
    def path(self) -> str:
        return {'openai-chat': '/v1/chat/completions', 'openai-responses': '/v1/responses',
                'anthropic': '/v1/messages', 'gemini': '/v1beta/models/' + quote(self.settings.model.removeprefix('models/'), safe='') + ':streamGenerateContent?alt=sse'}[self.settings.api]

    @property
    def upstream_path(self) -> str:
        return self._upstream_path(self.settings)

    @staticmethod
    def _upstream_path(settings: ModelSettings) -> str:
        return {'openai-chat': 'chat/completions', 'openai-responses': 'responses',
                'anthropic': 'messages', 'gemini': 'models/' + quote(settings.model.removeprefix('models/'), safe='') + ':streamGenerateContent?alt=sse'}[settings.api]

    def _native_request(self, inbound: dict, payload_bytes: bytes, settings: ModelSettings):
        api = self.settings.api
        if api != 'gemini' and inbound.get('model') != self.settings.model:
            raise WorkerModelError('worker model does not match the configured binding')
        if api != 'gemini' and inbound.get('stream') is not True:
            raise WorkerModelError('worker native request must use stream=true')
        allowed = ({'model', 'input', 'instructions', 'tools', 'tool_choice', 'parallel_tool_calls', 'stream', 'store', 'include', 'max_output_tokens', 'temperature', 'reasoning', 'prompt_cache_key'} if api == 'openai-responses' else
                   {'model', 'messages', 'system', 'tools', 'tool_choice', 'stream', 'max_tokens', 'temperature', 'thinking', 'output_config', 'metadata', 'cache_control'} if api == 'anthropic' else
                   {'contents', 'systemInstruction', 'tools', 'toolConfig', 'generationConfig', 'safetySettings'})
        unknown = inbound.keys() - allowed
        if unknown:
            raise WorkerModelError(f'unsupported worker {api} fields: {sorted(unknown)}')
        key = 'input' if api == 'openai-responses' else 'messages' if api == 'anthropic' else 'contents'
        if not isinstance(inbound.get(key), list):
            raise WorkerModelError(f'worker {key} must be an array')
        outgoing = inbound.copy()
        if api != 'gemini':
            outgoing['model'] = settings.model
        for tool in outgoing.get('tools', []):
            if api == 'openai-responses':
                valid = isinstance(tool, dict) and tool.get('type') == 'function'
            elif api == 'anthropic':
                valid = isinstance(tool, dict) and tool.get('type', 'custom') == 'custom' and 'input_schema' in tool
            else:
                valid = isinstance(tool, dict) and set(tool) == {'functionDeclarations'}
            if not valid:
                raise WorkerModelError('worker tools must be local function declarations; provider network tools are unavailable')
        options = dict(inbound.get('generationConfig', {})) if api == 'gemini' else outgoing
        output_field = 'max_output_tokens' if api == 'openai-responses' else 'max_tokens' if api == 'anthropic' else 'maxOutputTokens'
        output_tokens = options.get(output_field, self.settings.max_output_tokens)
        if type(output_tokens) is not int or not 0 < output_tokens <= self.settings.max_output_tokens:
            raise WorkerModelError('worker output tokens exceed configured binding')
        # Validated against the binding the container sees, then capped by the serving candidate.
        output_tokens = min(output_tokens, settings.max_output_tokens)
        options[output_field] = output_tokens
        if settings.temperature is None:
            options.pop('temperature', None)
        else:
            options['temperature'] = settings.temperature
        if api == 'openai-responses':
            if outgoing.get('store') is True:
                raise WorkerModelError('worker store may only be false')
            outgoing.update(store=False, include=['reasoning.encrypted_content'])
            outgoing.pop('reasoning', None)
            if settings.reasoning_effort is not None:
                outgoing['reasoning'] = {'effort': settings.reasoning_effort}
        elif api == 'anthropic':
            outgoing.pop('thinking', None)
            outgoing.pop('output_config', None)
            if settings.thinking_budget_tokens is not None:
                outgoing['thinking'] = {'type': 'enabled', 'budget_tokens': settings.thinking_budget_tokens}
            elif settings.reasoning_effort is not None:
                outgoing.update(thinking={'type': 'adaptive'}, output_config={'effort': settings.reasoning_effort})
        else:
            options.pop('thinkingConfig', None)
            if settings.thinking_budget_tokens is not None:
                options['thinkingConfig'] = {'thinkingBudget': settings.thinking_budget_tokens}
            elif settings.reasoning_effort is not None:
                options['thinkingConfig'] = {'thinkingLevel': settings.reasoning_effort}
            outgoing['generationConfig'] = options
        # Count readable JSON, retaining signed continuation in the estimate; image token cost is unknown.
        image_unknown = False
        def readable(value):
            nonlocal image_unknown
            if isinstance(value, dict):
                if value.get('type') in {'input_image', 'image'} or 'inlineData' in value or 'fileData' in value:
                    image_unknown = True
                    return '[image tokens unknown]'
                return {k: readable(v) for k, v in value.items()}
            return [readable(v) for v in value] if isinstance(value, list) else value
        estimated = math.ceil(len(json.dumps(readable(outgoing), ensure_ascii=False).encode()) / 3) + output_tokens
        if estimated > self.context_window_tokens:
            raise WorkerModelError(f'worker native request estimate {estimated} exceeds configured context window {self.context_window_tokens}')
        wire = json.dumps(outgoing, ensure_ascii=False, allow_nan=False).encode()
        if len(wire) > self.limits.max_request_bytes:
            raise WorkerModelError('forwarded worker model request exceeds max_request_bytes')
        return outgoing, wire, estimated, image_unknown

    async def __aenter__(self) -> WorkerModelProxy:
        if self._entered or self._closed:
            raise WorkerModelError("worker model proxy has already been opened or closed")
        self._entered = True
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        self._closed = True
        active = self._active_task
        if active is not None and active is not asyncio.current_task():
            active.cancel()
        for client in self._clients:
            await client.aclose()

    @asynccontextmanager
    async def _slot(self) -> AsyncIterator[None]:
        if self.slots is None:
            yield
        else:
            async with self.slots.slot(scene=self.scene):
                yield

    def _add_tokens(self, tokens: dict[str, int | None] | None) -> None:
        if tokens is None:
            self._tokens_unknown = True
            return
        self._spent += tokens["input"] + tokens["output"]

    def _request(self, payload_bytes: bytes, settings: ModelSettings | None = None) -> tuple[dict[str, Any], bytes, int, bool]:
        settings = self.settings if settings is None else settings
        if len(payload_bytes) > self.limits.max_request_bytes:
            raise WorkerModelError("worker model request exceeds max_request_bytes")
        try:
            inbound = json.loads(payload_bytes.decode("utf-8"), parse_constant=_reject_constant,
                                 parse_float=_finite_float)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise WorkerModelError(
                f"invalid worker Chat Completions JSON: {error}; fragment={payload_bytes[:500]!r}"
            ) from error
        if not isinstance(inbound, dict):
            raise WorkerModelError(
                f"worker Chat Completions request must be an object: {payload_bytes[:500]!r}"
            )
        if self.settings.api != "openai-chat":
            return self._native_request(inbound, payload_bytes, settings)
        allowed = {
            "model", "messages", "tools", "tool_choice", "stream", "stream_options",
            "temperature", "max_completion_tokens", "max_tokens", "reasoning_effort", "store",
        }
        unsupported = sorted(inbound.keys() - allowed)
        if unsupported:
            raise WorkerModelError(f"unsupported worker Chat Completions fields: {unsupported!r}; "
                                   f"fragment={payload_bytes[:500]!r}")
        if inbound.get("model") != self.settings.model:
            raise WorkerModelError("worker model does not match the configured binding")
        if inbound.get("stream") is not True:
            raise WorkerModelError("worker Chat Completions request must use stream=true")
        if "stream_options" in inbound and inbound["stream_options"] != {"include_usage": True}:
            raise WorkerModelError("worker stream_options must request include_usage=true")
        if "store" in inbound and inbound["store"] is not False:
            raise WorkerModelError("worker store may only be false")
        messages = inbound.get("messages")
        tools = inbound.get("tools", [])
        if not isinstance(messages, list) or not all(
            isinstance(message, dict) and isinstance(message.get("role"), str)
            for message in messages
        ):
            raise WorkerModelError(f"worker messages must be native message objects; "
                                   f"fragment={payload_bytes[:500]!r}")
        if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
            raise WorkerModelError(
                f"worker tools must be an array of objects; fragment={payload_bytes[:500]!r}"
            )
        if "tool_choice" in inbound and not isinstance(inbound["tool_choice"], (str, dict)):
            raise WorkerModelError(f"worker tool_choice must be a string or object; "
                                   f"fragment={payload_bytes[:500]!r}")
        if "store" in inbound:
            store = False
        else:
            store = None
        other_output_field = 'max_tokens' if self.settings.output_token_field == 'max_completion_tokens' else 'max_completion_tokens'
        if other_output_field in inbound:
            raise WorkerModelError(f'worker output budget must use configured field {self.settings.output_token_field}')
        output_tokens = inbound.get(self.settings.output_token_field, self.settings.max_output_tokens)
        if type(output_tokens) is not int or not 0 < output_tokens <= self.settings.max_output_tokens:
            raise WorkerModelError(
                f"worker max_completion_tokens must be a positive integer <= "
                f"{self.settings.max_output_tokens}; actual={output_tokens!r}")
        output_tokens = min(output_tokens, settings.max_output_tokens)
        outgoing: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            settings.output_token_field: output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if settings.temperature is not None:
            outgoing["temperature"] = settings.temperature
        if tools or "tools" in inbound:
            outgoing["tools"] = tools
        if "tool_choice" in inbound:
            outgoing["tool_choice"] = inbound["tool_choice"]
        if store is False:
            outgoing["store"] = False
        if settings.reasoning_effort is not None:
            outgoing["reasoning_effort"] = settings.reasoning_effort
        image_tokens_unknown = any(
            isinstance(message.get("content"), list)
            and any(isinstance(block, dict) and block.get("type") == "image_url"
                    for block in message["content"])
            for message in messages
        )
        try:
            text_estimate = estimate_text_request(
                [{"content": None, **message} for message in messages],
                tools, output_tokens,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise WorkerModelError(f"invalid worker message content: {error}; "
                                   f"fragment={payload_bytes[:500]!r}") from error
        if text_estimate > self.context_window_tokens:
            raise WorkerModelError(
                f"worker text request estimate {text_estimate} exceeds configured "
                f"context window {self.context_window_tokens}; image tokens are unknown"
            )
        try:
            wire = json.dumps(outgoing, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")
        except (UnicodeEncodeError, ValueError) as error:
            raise WorkerModelError(f"invalid worker request data: {error}; "
                                   f"fragment={payload_bytes[:500]!r}") from error
        if len(wire) > self.limits.max_request_bytes:
            raise WorkerModelError("forwarded worker model request exceeds max_request_bytes")
        return outgoing, wire, text_estimate, image_tokens_unknown

    def authorize(self, token: str) -> None:
        if (not self._entered or self._closed
                or not hmac.compare_digest(token.encode("utf-8"), self._token.encode("utf-8"))):
            raise WorkerModelError("worker model task token is invalid or expired")

    def recorded(self, value: Any) -> Any:
        """Project records, not executed requests, using credentials owned by this proxy."""
        secrets = tuple(sorted({self._token, *(candidate.api_key for _, candidate in self.candidates)},
                               key=len, reverse=True))
        return redact_record(value, lambda text: redact(text, secrets))

    def _finish_record(self, call_id: int, facts: dict[str, Any]) -> None:
        recorded = {**facts, **{name: self.recorded(facts[name]) for name in ('error', 'error_body', 'usage')}}
        self.finish_call(call_id, recorded)

    def _order(self) -> list[int]:
        return [0] if self.health is None else self.health.order(self.role)

    @asynccontextmanager
    async def open(self, token: str, payload_bytes: bytes, *, headers: dict | None = None) -> AsyncIterator[WorkerResponse]:
        self.authorize(token)
        headers = {} if headers is None else headers
        if (headers.keys() - {"anthropic-beta"} or any(not isinstance(v, str) for v in headers.values())
                or (headers and self.settings.api != "anthropic")):
            raise WorkerModelError("unsupported worker protocol headers")
        if self._busy:
            raise WorkerModelError("worker model proxy already has an active call")
        if self._calls >= self.limits.max_calls:
            raise WorkerModelError("worker model call limit reached")
        if self.limits.max_tokens is not None and (
            self._tokens_unknown or self._spent >= self.limits.max_tokens
        ):
            raise WorkerModelError("worker model token limit reached, or an earlier call reported no tokens")
        self._busy = True
        self._active_task = asyncio.current_task()
        try:
            # Validate against the binding the container was configured with before any upstream work.
            self._request(payload_bytes)
            order = self._order()
            failed_before: list[dict[str, Any]] = []
            async with self._slot():
                for position, index in enumerate(order):
                    if self._closed:
                        raise WorkerModelError("worker model task token has expired")
                    try:
                        async with self._attempt(index, payload_bytes, headers,
                                                 final=position == len(order) - 1,
                                                 failed_before=failed_before) as response:
                            yield response
                        return
                    except _FailedOver as failure:
                        provider, settings = self.candidates[index]
                        failed_before.append({"provider": provider, "model": settings.model,
                                              "error": str(failure)})
                        continue
        finally:
            self._active_task = None
            self._busy = False
            if self._closed:
                for client in self._clients:
                    if not client.is_closed:
                        await client.aclose()

    def _served(self, index: int, failed_before: list[dict[str, Any]]) -> None:
        if self.health is None:
            return
        provider, settings = self.candidates[index]
        self.health.succeeded(self.role, provider, settings.model)
        self.health.record_served(self.role, {"provider": provider, "model": settings.model, "priority": index,
                                              "failed_before": list(failed_before)})

    @asynccontextmanager
    async def _attempt(self, index: int, payload_bytes: bytes, headers: dict, *, final: bool,
                       failed_before: list[dict[str, Any]]) -> AsyncIterator[WorkerResponse]:
        """One upstream call, recorded on its own; raises ``_FailedOver`` only before the container sees bytes."""
        provider, settings = self.candidates[index]
        client = self._clients[index]
        upstream_path = self._upstream_path(settings)
        call_id: int | None = None
        settled = False
        streaming = False
        status: int | None = None
        response_bytes = 0
        error_body = bytearray()
        deadline: asyncio.Timeout | None = None
        wire = b""
        try:
            outgoing, wire, text_estimate, image_unknown = self._request(payload_bytes, settings)
            call_id = self.start_call({
                "provider": provider,
                "model": settings.model,
                "request": self.recorded(outgoing),
                "request_bytes": len(wire),
                "incoming_bytes": len(payload_bytes),
                "text_request_estimate_tokens": text_estimate,
                "image_tokens_unknown": image_unknown,
                **({"failover_priority": index} if self.health is not None else {}),
            })
            if not failed_before:
                # One container request is one call against the task's limit, however many candidates it took.
                self._calls += 1
            deadline = asyncio.timeout(settings.timeout_seconds)
            async with deadline:
                request = client.build_request(
                    "POST", upstream_path, content=wire,
                    headers={
                        **auth_headers(settings.api, settings.api_key),
                        **headers,
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "Accept-Encoding": "identity",
                    },
                )
                upstream = await client.send(request, stream=True)
                try:
                    status = upstream.status_code
                    if (not final and not upstream.is_success
                            and (status in FAILOVER_STATUS or status >= 500)):
                        async for chunk in upstream.aiter_raw():
                            response_bytes += len(chunk)
                            if response_bytes > self.limits.max_response_bytes:
                                break
                            error_body.extend(chunk)
                        raise _FailedOver(f"upstream model HTTP {status}")
                    encoding = upstream.headers.get("content-encoding", "identity")
                    if encoding != "identity":
                        raise WorkerModelError(f"unsupported upstream content-encoding: {encoding}")
                    parser = ((ChatCompletionStream(self.limits.max_response_bytes) if settings.api == "openai-chat"
                               else NativeStream(settings, self.limits.max_response_bytes))
                              if upstream.is_success else None)
                    if upstream.is_success:
                        self._served(index, failed_before)
                    elif self.health is not None and (status in FAILOVER_STATUS or status >= 500):
                        self.health.failed(self.role, provider, settings.model,
                                           WorkerModelError(f"upstream model HTTP {status}"))

                    def settle(*, result: Any = None, error: str | None = None) -> None:
                        nonlocal settled
                        tokens = token_record(None if result is None else result.token_usage)
                        facts = {
                            "http_status": status,
                            "request_bytes": len(wire),
                            "response_bytes": response_bytes,
                            "finish_reason": None if result is None else result.finish_reason,
                            "usage": None if result is None else result.usage,
                            "token_usage": None if result is None or result.token_usage is None
                            else asdict(result.token_usage),
                            "tokens": tokens,
                            "error": error,
                            "error_body": error_body.decode("utf-8", errors="backslashreplace")
                            if error_body else None,
                        }
                        settled = True
                        try:
                            self._finish_record(call_id, facts)
                        except BaseException:
                            self._closed = True
                            raise
                        if tokens is not None or status not in REJECTED_HTTP_STATUSES:
                            self._add_tokens(tokens)

                    async def body() -> AsyncIterator[bytes]:
                        nonlocal response_bytes
                        async for chunk in upstream.aiter_raw():
                            response_bytes += len(chunk)
                            if response_bytes > self.limits.max_response_bytes:
                                raise WorkerModelError("worker model response exceeds max_response_bytes")
                            if parser is not None:
                                parser.feed(chunk)
                                if parser.done:
                                    settle(result=parser.finish())
                                    yield chunk
                                    return
                            else:
                                error_body.extend(chunk)
                            yield chunk
                        if parser is not None:
                            settle(result=parser.finish())
                        else:
                            settle(error=f"upstream model HTTP {status}")

                    stream = body()
                    response_headers = {
                        "content-type": upstream.headers.get("content-type", "application/octet-stream")
                    }
                    streaming = True
                    yield WorkerResponse(status, response_headers, stream)
                    if not settled:
                        await stream.aclose()
                        raise WorkerModelError("worker model response was not fully consumed")
                finally:
                    await upstream.aclose()
        except BaseException as error:
            original_error = error
            if isinstance(error, TimeoutError) and deadline is not None and deadline.expired():
                error = TimeoutError(
                    f"worker model {provider}/{settings.model} POST {upstream_path} "
                    f"exceeded {settings.timeout_seconds:g} seconds; "
                    f"HTTP status={status}, received_bytes={response_bytes}; request did not finish"
                )
            if isinstance(error, asyncio.CancelledError):
                self._closed = True
            # Only an unreachable or failing upstream moves on; a refused request or a broken stream does not.
            fail_over = (call_id is not None and not streaming and not final and not self._closed
                         and isinstance(error, (_FailedOver, TimeoutError, httpx.TransportError)))
            if call_id is not None and not settled:
                settled = True
                known_usage = error.usage if isinstance(error, ModelProtocolError) else None
                known_tokens = error.token_usage if isinstance(error, ModelProtocolError) else None
                tokens = token_record(known_tokens)
                facts = {
                    "http_status": status,
                    "request_bytes": len(wire),
                    "response_bytes": response_bytes,
                    "finish_reason": None,
                    "usage": known_usage,
                    "token_usage": None if known_tokens is None else asdict(known_tokens),
                    "tokens": tokens,
                    "error": str(error) if isinstance(error, _FailedOver) else f"{type(error).__name__}: {error}",
                    "error_body": error_body.decode("utf-8", errors="backslashreplace")
                    if error_body else None,
                }
                try:
                    self._finish_record(call_id, facts)
                except BaseException as finish_error:
                    self._closed = True
                    fail_over = False
                    error.add_note(f"model-call recording also failed: {finish_error}")
                # A candidate that answered with an error status or was never reached produced no output.
                uncharged = fail_over and (isinstance(error, (_FailedOver, httpx.ConnectError, httpx.ConnectTimeout)))
                if tokens is not None or (status not in REJECTED_HTTP_STATUSES and not uncharged):
                    self._add_tokens(tokens)
            if (self.health is not None and call_id is not None and not streaming
                    and isinstance(error, (_FailedOver, TimeoutError, httpx.TransportError))):
                self.health.failed(self.role, provider, settings.model, error)
            if fail_over:
                if isinstance(error, _FailedOver):
                    raise
                raise _FailedOver(f"{type(error).__name__}: {error}") from error
            if isinstance(error, _FailedOver):
                # Recording failed after a failover-worthy status; surface it as a worker error.
                raise WorkerModelError(str(error)) from error
            if error is not original_error:
                raise error from original_error
            raise
