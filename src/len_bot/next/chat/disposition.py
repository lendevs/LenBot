"""Optional per-turn participation state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..configuration.chat import TurnDisposition

ENDING_TOOLS = {'say', 'react', 'message_reaction', 'attention', 'end_turn'}


class DispositionArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    state: Literal['open', 'closed']
    minutes: float = Field(gt=0, allow_inf_nan=False)
    people: list[str] | None = Field(default=None, description='open 时只继续关注这些账号；不填表示不限。')

    @model_validator(mode='after')
    def valid_people(self) -> DispositionArguments:
        if self.state == 'closed' and self.people is not None:
            raise ValueError('closed 不接受 people')
        if self.people is not None and any(':' not in person or not person.split(':', 1)[1] for person in self.people):
            raise ValueError('people 必须是平台账号，例如 onebot:70001')
        return self


@dataclass
class Disposition:
    state: Literal['open', 'closed']
    people: list[str]
    until: float
    turn_id: str | None


def parse_disposition(raw: object, settings: TurnDisposition, now: float, turn_id: str) -> Disposition | None:
    if raw is None:
        return None
    args = DispositionArguments.model_validate(raw)
    if args.minutes > settings.max_minutes:
        raise ValueError(f'disposition.minutes 不能超过 {settings.max_minutes:g}')
    people = list(dict.fromkeys(args.people or []))
    if len(people) > settings.max_people:
        raise ValueError(f'disposition.people 最多 {settings.max_people} 个账号')
    return Disposition(args.state, people, now + args.minutes * 60, turn_id)


def allows(disposition: Disposition | None, candidate: str, sender: str, now: float) -> bool:
    if disposition is None or disposition.until <= now:
        return True
    if disposition.state == 'closed':
        return False
    return candidate != 'focus' or not disposition.people or sender in disposition.people


def schema(settings: TurnDisposition) -> dict:
    parameters = DispositionArguments.model_json_schema()
    parameters['properties']['minutes']['maximum'] = settings.max_minutes
    parameters['properties']['people']['anyOf'][0]['maxItems'] = settings.max_people
    parameters['description'] = ('可选的本轮收尾：open 让基线关注窗口内的对话继续，minutes 最长到基线窗口结束；'
        '等待稍后补充或跨话题的结果用 attention 的 intend 创建持续意图。closed 暂停 focus 和 ambient，'
        '持续意图、私聊、@、回复机器人和点名照常唤醒。'
        '可附在最后一次表达或 attention 调用上，或用 end_turn 沉默收尾；省略则本轮结束后按基线规则。'
        '下一轮的收尾会替换本轮的设置。')
    return parameters


def with_disposition(tool: dict, settings: TurnDisposition) -> dict:
    if tool['function']['name'] not in ENDING_TOOLS:
        return tool
    parameters = tool['function']['parameters']
    return {**tool, 'function': {**tool['function'], 'parameters': {
        **parameters, 'properties': {**parameters['properties'], 'disposition': schema(settings)}}}}


def end_turn_tool(settings: TurnDisposition) -> dict:
    return {'type': 'function', 'function': {'name': 'end_turn', 'description': '结束本轮，可说明是否继续参与当前交互。',
        'parameters': {'type': 'object', 'properties': {'disposition': schema(settings)}, 'additionalProperties': False}}}
