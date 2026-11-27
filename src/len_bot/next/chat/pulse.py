"""A small model request that screens ambiguous wakes before a Mind turn."""

from __future__ import annotations

import logging
import re
from string import Template
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from .declarations import Intent
from .recap import estimate_content, estimate_request
from ..models.client import ChatModel, ModelSettings
from ..models.request import request_model
from ..platform.messages import ChatMessage, plain_text
from ..prompt_files import read_prompt
from ..runtime.logs import log_event
from ..storage.codec import encode

if TYPE_CHECKING:
    from .session import Chat


logger = logging.getLogger(__name__)
PULSE_CHANNELS = frozenset({'ambient', 'explore', 'named'})
PULSE_BYPASS = frozenset({'direct', 'focus', 'attention', 'schedule', 'task', 'plugin', 'audio', 'resume'})
INPUT_TOKENS = 1050


class PulseVerdict(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    decision: Literal["silent", "wake"]
    target_msg_id: str | None = None
    matched_watch_ids: list[str] = Field(default_factory=list)


class PulseModel:
    """Use the Mind client's connection with the Pulse binding's request options."""

    def __init__(self, client: ChatModel, settings: ModelSettings):
        self.client = client
        self.settings = settings

    async def complete(self, messages, tools, *, settings=None, **options):
        return await self.client.complete(messages, tools, settings=settings or self.settings, **options)


def shares_connection(mind: ModelSettings, pulse: ModelSettings) -> bool:
    fields = ('api', 'base_url', 'api_key', 'proxy', 'model')
    return all(getattr(mind, field) == getattr(pulse, field) for field in fields)


def excerpt(text: str, chars: int) -> str:
    return ' '.join(text.split())[:chars]


def pulse_prompt(chat: Chat, pending: list[tuple[int, ChatMessage, float]],
                 watches: list[Intent], channels: set[str]) -> tuple[list[dict], dict[str, ChatMessage]]:
    persona = chat.persona
    system = Template(read_prompt('next_pulse.md')).substitute(
        name=excerpt(persona.name, 32), brief=excerpt(persona.brief, 90),
        aliases=excerpt('、'.join([*persona.aliases, *chat.config.persona_aliases]), 60) or '无',
    ).strip()
    summaries = []
    for intent in watches:
        summary = {'id': intent.id, 'reason': excerpt(intent.reason, 32),
                   'watch': excerpt('；'.join(condition['watch'] for condition in intent.conditions
                                             if condition.get('watch')), 60)}
        if estimate_content(encode([*summaries, summary])) > 450:
            break
        summaries.append(summary)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': ''}]
    heading = '候选渠道 ' + '、'.join(sorted(channels)) + '\n挂念 ' + encode(summaries) + '\n消息\n'
    rows = []
    for seq, message, _ in reversed(pending[-12:]):
        ident = message.platform_message_id or message.id
        speaker = excerpt(message.sender.card or message.sender.nickname or '', 16)
        reply = message.semantic_reply_to or message.reply_to
        text = excerpt(plain_text(message), 120)
        row = encode([seq, ident, message.sender.uid, speaker, reply, text])
        messages[-1]['content'] = heading + '\n'.join([row, *(item[0] for item in reversed(rows))])
        if rows and estimate_request(messages, [], 0) > INPUT_TOKENS:
            break
        rows.append((row, ident, message))
    messages[-1]['content'] = heading + '\n'.join(row for row, _, _ in reversed(rows))
    return messages, {ident: message for _, ident, message in reversed(rows)}


async def request_pulse(chat: Chat, model: ChatModel | PulseModel, messages: list[dict]) -> PulseVerdict | None:
    try:
        binding = chat.config.binding('pulse')
        effort = binding.quick_reasoning_effort
        effective = model.settings.with_effort(effort) if effort is not None else model.settings
        budget = effective.thinking_budget_tokens
        output_tokens = min(binding.max_output_tokens, 160 if budget is None else budget + 160)
        reply = await request_model(chat.config, chat.store, model, messages, [], scene=chat.config.scene,
                                    role='pulse', slots=chat.slots, direct=False, output_tokens=output_tokens, quick=True)
        body = reply.text.strip()
        fence = re.fullmatch(r'```(?:json\b)?\s*(.*?)\s*```', body, flags=re.IGNORECASE | re.DOTALL)
        return PulseVerdict.model_validate_json(fence.group(1) if fence else body)
    except Exception as error:
        log_event(logger, 'semantic_pulse_failed', level=logging.WARNING, error=error)
        return None
