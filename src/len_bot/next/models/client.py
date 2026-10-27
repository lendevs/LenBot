"""One non-streaming request through the configured native chat protocol."""

from __future__ import annotations

import copy
import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Literal
from .providers import ChatAPI, http_client, valid_url

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from len_bot.next.models.tokens import TokenUsage


logger = logging.getLogger(__name__)


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api: ChatAPI
    base_url: str
    api_key: str = Field(repr=False)
    model: str
    thinking: Literal["enabled", "disabled"] | None = None
    reasoning_effort: str | None = None
    thinking_budget_tokens: int | None = Field(default=None, ge=0)
    output_token_field: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    proxy: str | None = Field(default=None, repr=False)
    temperature: float | None = Field(default=0.6, ge=0, le=2, allow_inf_nan=False)
    max_output_tokens: int = Field(default=1024, gt=0)
    timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    retry_delays_seconds: tuple[float, ...] = ()

    @classmethod
    def from_binding(cls, provider, binding) -> ModelSettings:
        return cls(api=provider.api, base_url=provider.base_url, api_key=provider.api_key, proxy=provider.proxy,
                   **binding.model_dump(exclude={'provider', 'context_window_tokens', 'history_policy',
                                                 'quick_reasoning_effort', 'image_input'}))

    def with_effort(self, effort: str) -> ModelSettings:
        """The same request settings at another reasoning effort, validated again."""
        return ModelSettings.model_validate({**self.model_dump(), 'reasoning_effort': effort,
                                             'thinking_budget_tokens': None})

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        return valid_url(value)

    @field_validator("api_key", "model")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("reasoning_effort")
    @classmethod
    def nonblank_reasoning_effort(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def protocol_options(self):
        if self.thinking is not None and self.api != "openai-chat":
            raise ValueError("思考开关只能用于 OpenAI 兼容聊天接口")
        if self.thinking_budget_tokens is not None and self.reasoning_effort is not None:
            raise ValueError('思考额度与思考强度只能选一个')
        if self.thinking_budget_tokens is not None and self.api not in {'anthropic', 'gemini'}:
            raise ValueError('思考额度仅支持 Anthropic 和 Gemini')
        if self.api == 'anthropic' and (self.reasoning_effort is not None or self.thinking_budget_tokens is not None):
            if self.temperature is not None:
                raise ValueError('Anthropic 思考模式需要将温度留空')
            if self.thinking_budget_tokens is not None and not 1024 <= self.thinking_budget_tokens < self.max_output_tokens:
                raise ValueError('Anthropic 思考额度至少 1024，且必须小于输出额度')
        if self.api != 'openai-chat' and self.output_token_field != 'max_completion_tokens':
            raise ValueError('输出字段选择仅适用于 OpenAI 兼容聊天接口')
        return self


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    message: dict[str, Any]
    text: str
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: dict[str, Any] | None
    token_usage: TokenUsage | None
    response: dict | None = None


class ModelProtocolError(RuntimeError):
    """A successful HTTP response did not contain a complete model reply."""

    def __init__(self, message: str, *, response: object | None = None,
                 usage: dict[str, Any] | None = None, token_usage: TokenUsage | None = None):
        super().__init__(message)
        self.response = copy.deepcopy(response)
        self.usage = copy.deepcopy(usage)
        self.token_usage = token_usage


class ModelOutputLimitError(ModelProtocolError):
    """The provider stopped at this request's output allowance."""

    def describe(self, output_tokens: int, purpose: str = "模型", setting: str = "最长输出") -> None:
        counts = [] if self.token_usage is None else [
            f"{label} {value} token" for label, value in (
                ("输入", self.token_usage.prompt_tokens), ("输出", self.token_usage.completion_tokens),
            ) if value is not None
        ]
        usage = "，".join(counts) or "服务商未返回用量"
        self.args = (f"{purpose}输出额度用完：本次额度 {output_tokens} token，服务商用量：{usage}。"
                     f"请调大 {setting}，或降低思考强度。",)


# How providers say a model ID is unknown when they answer 400 or 422 instead of 404.
MODEL_MISSING = re.compile(r"model[_ ]not[_ ]found|model (?:does )?not exist|no such model|not a valid model|"
                           r"unknown model|模型不存在", re.IGNORECASE)
# How providers say the request is longer than the model's real context window.
CONTEXT_EXCEEDED = re.compile(r"context[_ ]length[_ ]exceeded|maximum context length|prompt is too long|"
                              r"exceeds the maximum number of tokens|input is too long|超过.{0,8}上下文", re.IGNORECASE)


class ModelHTTPError(RuntimeError):
    """The configured provider rejected a model request."""

    def __init__(self, status: int, detail: str, request_id: str | None = None):
        if status in {401, 403}:
            direction = "认证或权限校验失败，请检查服务商 API Key 和模型访问权限"
        elif status == 429:
            direction = "请求受限，请稍后重试或检查服务商额度"
        elif status >= 500:
            direction = "服务商或中转服务异常，请稍后重试或联系渠道运营方"
        elif CONTEXT_EXCEEDED.search(detail):
            direction = "请求超过模型实际的上下文长度，请按服务商文档调小该用途的上下文长度"
        elif status == 404 or MODEL_MISSING.search(detail):
            direction = "模型名或接口地址不存在，请核对模型名，或读取服务商的模型列表后选择；同时核对服务商地址"
        else:
            direction = "服务商拒绝请求，请查看调用详情并核对模型参数"
        self.status = status
        self.response = {"status": status, "request_id": request_id, "detail": detail}
        super().__init__(f"{direction}（HTTP {status}）" + (f"；request id: {request_id}" if request_id else ""))


class ModelConnectionError(RuntimeError):
    """The provider address could not be reached, or the connection broke before a response."""

    def __init__(self, base_url: str, error: httpx.TransportError, api_key: str = ""):
        detail = f"{type(error).__name__}: {error}"
        if api_key:
            detail = detail.replace(api_key, "[hidden]")
        if isinstance(error, httpx.ProxyError):
            direction = "代理连接失败，请检查代理地址和代理是否正在运行"
        elif isinstance(error, httpx.TimeoutException):
            direction = "服务商地址响应超时，请检查地址、网络和代理，或调大超时"
        else:
            direction = "无法连接服务商地址，请检查地址、网络和代理"
        super().__init__(f"{direction}（{base_url}；{detail}）")


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant in tool arguments: {value}")


def _finite_json_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'non-finite JSON number: {value[:100]}')
    return number


def parse_token_usage(usage: dict[str, Any] | None) -> TokenUsage | None:
    if usage is None:
        return None

    def token(value: object, field: str) -> int | None:
        if value is None:
            return None
        if type(value) is not int or value < 0:
            raise ValueError(f"usage.{field} must be a nonnegative integer or null")
        return value

    prompt = token(usage.get("prompt_tokens"), "prompt_tokens")
    completion = token(usage.get("completion_tokens"), "completion_tokens")
    details = usage.get("prompt_tokens_details")
    if details is not None and not isinstance(details, dict):
        raise ValueError("usage.prompt_tokens_details must be an object or null")
    cached = token(None if details is None else details.get("cached_tokens"),
                   "prompt_tokens_details.cached_tokens")
    if prompt is not None and cached is not None and cached > prompt:
        raise ValueError("usage.prompt_tokens_details.cached_tokens exceeds prompt_tokens")
    return TokenUsage(prompt, completion, cached)


def parse_chat_completion(body: object) -> ModelReply:
    """Parse a provider response once, retaining its native assistant message."""
    token_usage = None
    try:
        if not isinstance(body, dict):
            raise ValueError("expected a response object")
        usage = body.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ValueError("usage must be an object or null")
        token_usage = parse_token_usage(usage)
        choices = body["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError("expected a nonempty choices array")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ValueError("expected a choice object")
        finish_reason = choice["finish_reason"]
        if finish_reason == "length":
            raise ModelOutputLimitError("模型输出额度耗尽（finish_reason=length）", response=body,
                                        usage=usage, token_usage=token_usage)
        if finish_reason not in {"stop", "tool_calls"}:
            raise ValueError(f"incomplete or unsupported finish_reason: {finish_reason!r}")
        message = choice["message"]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("expected an assistant message")
        content = message["content"]
        if content is not None and not isinstance(content, str):
            raise ValueError("assistant content must be a string or null")

        native_calls = message.get("tool_calls")
        if native_calls is None:
            native_calls = []
        if not isinstance(native_calls, list):
            raise ValueError("tool_calls must be an array")
        calls: list[ToolCall] = []
        for native in native_calls:
            if not isinstance(native, dict) or native.get("type") != "function":
                raise ValueError("expected a native function tool call")
            call_id = native["id"]
            function = native["function"]
            if not isinstance(function, dict):
                raise ValueError("expected a function object")
            name = function["name"]
            raw_arguments = function["arguments"]
            if not isinstance(call_id, str) or not call_id.strip():
                raise ValueError("tool call id must be a nonempty string")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tool name must be a nonempty string")
            if not isinstance(raw_arguments, str):
                raise ValueError("tool arguments must be a JSON string")
            try:
                arguments = json.loads(raw_arguments, parse_constant=_reject_non_json_constant)
            except json.JSONDecodeError as error:
                raise ValueError(f"incomplete or invalid tool arguments JSON: {error}") from error
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must decode to an object")
            calls.append(ToolCall(call_id, name, arguments))
        if len({call.id for call in calls}) != len(calls):
            raise ValueError("duplicate tool call ids")
        if (finish_reason == "tool_calls") != bool(calls):
            raise ValueError("finish_reason and tool calls disagree")

    except (KeyError, TypeError, ValueError) as error:
        fragment = json.dumps(body, ensure_ascii=False, default=repr)[:500]
        raw_usage = body.get("usage") if isinstance(body, dict) else None
        usage = raw_usage if isinstance(raw_usage, dict) else None
        raise ModelProtocolError(
            f"Invalid chat completion: {error}; response fragment: {fragment}",
            response=body, usage=usage, token_usage=token_usage,
        ) from error

    return ModelReply(
        message=copy.deepcopy(message),
        text=content or "",
        tool_calls=calls,
        finish_reason=finish_reason,
        usage=copy.deepcopy(usage),
        token_usage=token_usage,
        response=copy.deepcopy(body),
    )


class ChatModel:
    def __init__(self, settings: ModelSettings):
        self.settings = settings
        self._client = http_client(base_url=settings.base_url, api_key=settings.api_key, api=settings.api,
                                   timeout_seconds=settings.timeout_seconds, proxy=settings.proxy)

    async def __aenter__(self) -> ChatModel:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def complete(self, messages: list[dict], tools: list[dict], *,
                       max_output_tokens: int | None = None, session_id: str | None = None,
                       settings: ModelSettings | None = None) -> ModelReply:
        """``settings`` overrides request options for this call only; the client keeps its connection."""
        from .protocols import build_request, parse_reply
        settings = self.settings if settings is None else settings
        path, payload = build_request(settings, messages, tools, max_output_tokens=max_output_tokens)
        for delay in (*settings.retry_delays_seconds, None):
            deadline = asyncio.timeout(settings.timeout_seconds)
            try:
                async with deadline:
                    response = await self._client.post(path, json=payload,
                                                       headers={} if session_id is None else {"Session-Id": session_id})
            except TimeoutError as error:
                if deadline.expired():
                    raise TimeoutError(f"模型请求超过 {settings.timeout_seconds:g} 秒未完成（{settings.base_url}），"
                                       "请检查网络和代理，或调大超时") from error
                raise
            except httpx.TransportError as error:
                if delay is None:
                    raise ModelConnectionError(settings.base_url, error, self.settings.api_key) from error
                logger.warning("model request retry in %ss after %s", delay, type(error).__name__)
            else:
                if delay is None or (response.status_code != 429 and response.status_code < 500):
                    break
                logger.warning("model request retry in %ss after HTTP %s", delay, response.status_code)
            await asyncio.sleep(delay)
        if not response.is_success:
            fragment = response.text.replace(self.settings.api_key, '[hidden]')[:2000]
            match = re.search(r"request[ _-]id[\s:：=]+([^\s)\"}]+)", fragment, re.IGNORECASE)
            request_id = response.headers.get('x-request-id') or response.headers.get('request-id')
            if request_id is None and match is not None:
                request_id = match.group(1)
            raise ModelHTTPError(response.status_code, fragment, request_id)
        try:
            body = json.loads(response.text, parse_constant=_reject_non_json_constant, parse_float=_finite_json_number)
        except ValueError as error:
            raise ModelProtocolError(
                f"Invalid chat completion JSON: {error}; response fragment: {response.text[:500]}",
                response=response.text[:2000],
            ) from error
        try:
            return parse_reply(settings, body)
        except ModelOutputLimitError as error:
            error.describe(settings.max_output_tokens if max_output_tokens is None else max_output_tokens)
            raise
