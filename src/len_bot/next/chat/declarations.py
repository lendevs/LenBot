"""Persistent attention intents. Structural matches are candidates, never completion decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..configuration.chat import AttentionDeclarations
from ..platform.messages import ChatMessage, plain_text


class Condition(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    type: Literal['person', 'thread', 'open_question', 'topic', 'at'] = Field(
        description='条件种类。例：{"type":"person","people":["onebot:70001"]} 或 {"type":"at","minutes":5}。')
    people: list[str] | None = Field(default=None, min_length=1)
    message_id: str | None = Field(default=None, min_length=1)
    keywords: list[str] | None = Field(default=None, min_length=1)
    minutes: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def fields_for_type(self) -> Condition:
        required = {'person': {'people'}, 'thread': {'message_id'}, 'open_question': {'message_id'},
                    'topic': {'keywords'}, 'at': {'minutes'}}[self.type]
        allowed = required | ({'keywords'} if self.type == 'open_question' else set())
        supplied = {key for key in ('people', 'message_id', 'keywords', 'minutes') if getattr(self, key) is not None}
        if not required <= supplied or supplied - allowed:
            raise ValueError(f'{self.type} 需要 {sorted(required)}，只接受 {sorted(allowed)}')
        if self.people is not None and any(':' not in person or not person.split(':', 1)[1] for person in self.people):
            raise ValueError('people 必须是平台账号，例如 onebot:70001 或 telegram:7001')
        if self.keywords is not None:
            self.keywords = list(dict.fromkeys(word.strip().casefold() for word in self.keywords))
            if any(not word for word in self.keywords):
                raise ValueError('keywords 不能为空白')
        return self


class AttentionArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    action: Literal['intend', 'keep', 'resolve', 'drop']
    id: str | None = Field(default=None, min_length=1, description='已有意图 ID；intend 带 ID 时修改该意图。')
    when: list[Condition] | None = Field(default=None, min_length=1,
        description='intend 的条件数组。例如等待成员：[ {"type":"person","people":["onebot:70001"]} ]。')
    match: Literal['any', 'all'] | None = Field(default=None, description='任一条件或全部条件，默认 any。')
    minutes: float | None = Field(default=None, gt=0, allow_inf_nan=False, description='从现在开始的有效分钟数。')
    reason: str | None = Field(default=None, min_length=1, description='仍在等待或关注什么。')
    end_turn: bool = False

    @model_validator(mode='after')
    def action_fields(self) -> AttentionArguments:
        supplied = {key for key in ('id', 'when', 'match', 'minutes', 'reason') if getattr(self, key) is not None}
        if self.action == 'intend':
            if not {'when', 'minutes', 'reason'} <= supplied:
                raise ValueError('intend 需要 when、minutes 和 reason')
            if not self.reason.strip():
                raise ValueError('reason 不能为空白')
            timers = [condition for condition in self.when if condition.type == 'at']
            if any(condition.minutes >= self.minutes for condition in timers):
                raise ValueError('at.minutes 必须小于意图的 minutes；到期时意图不再触发')
            if timers and self.match == 'all' and len(self.when) > 1:
                raise ValueError('at 只支持独立计时或 match=any，不支持与消息条件作 all 组合')
        elif supplied != {'id'}:
            raise ValueError(f'{self.action} 只接受必填的 id')
        return self


ATTENTION_TOOL = {'type': 'function', 'function': {
    'name': 'attention',
    'description': '持续关注未来事件或等待补充。intend 创建意图，带 id 修改；keep 保持；resolve 确认已完成；drop 放弃。'
        '意图跨无关回合保留，不受 open/closed 影响。person 匹配指定账号，thread 匹配回复链，'
        'open_question 匹配回复链或关键词，topic 匹配关键词；这些都只是候选，醒来后自行判断是否完成。'
        'at 在指定分钟后检查一次，必须早于意图到期；没有新消息也可触发。'
        'any 是任一条件满足，all 是全部消息条件满足。遗漏 keep 不会删除意图；只有 resolve、drop 或到期才结束。'
        '当前事情已结束且没有后续需要时不必创建意图。end_turn=true 可在操作后结束本轮。',
    'parameters': AttentionArguments.model_json_schema(),
}}


@dataclass
class Intent:
    id: str
    conditions: list[dict]
    match: Literal['any', 'all']
    reason: str
    created: float
    until: float
    source_turn: str | None
    source_call: str | None


@dataclass
class Declared:
    intents: list[Intent] = field(default_factory=list)
    next_id: int = 1
    # One latest candidate per intent in the pending batch; all are shown on the next turn.
    matches: list[dict] = field(default_factory=list)
    turn_matches: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, saved: dict) -> Declared:
        return cls(**{**saved, 'intents': [Intent(**item) for item in saved['intents']]})

    def find(self, identifier: str) -> Intent:
        for intent in self.intents:
            if intent.id == identifier:
                return intent
        raise ValueError(f'没有生效中的意图：{identifier!r}')

    def expire(self, now: float) -> list[str]:
        ended = [intent.id for intent in self.intents if intent.until <= now]
        self.intents = [intent for intent in self.intents if intent.until > now]
        self.matches = [match for match in self.matches if match['intent'] not in ended]
        return ended

    def view(self, now: float) -> list[dict]:
        return [{'id': intent.id, 'reason': intent.reason, 'match': intent.match,
                 'minutes_left': round((intent.until - now) / 60, 2),
                 'when': [{key: value for key, value in condition.items() if key != 'chain'}
                          for condition in intent.conditions]}
                for intent in self.intents if intent.until > now]

    def candidate(self, intent: Intent, at: float, message_id: str | None) -> dict:
        match = {'intent': intent.id, 'reason': intent.reason, 'message_id': message_id, 'at': at}
        self.matches = [item for item in self.matches if item['intent'] != intent.id] + [match]
        return match

    def consume(self, *, new_turn: bool) -> None:
        previous = [] if new_turn else self.turn_matches
        identifiers = {item['intent'] for item in self.matches}
        self.turn_matches = [item for item in previous if item['intent'] not in identifiers] + self.matches
        self.matches = []


def declare(declared: Declared, args: AttentionArguments, settings: AttentionDeclarations, now: float,
            find_message, *, source_turn: str | None = None, source_call: str | None = None) -> dict:
    """Called on the runner's copy; invalid model arguments leave its saved state unchanged."""
    declared.expire(now)
    previous = declared.find(args.id) if args.id is not None else None
    if args.action != 'intend':
        if args.action in {'resolve', 'drop'}:
            declared.intents.remove(previous)
            declared.matches = [match for match in declared.matches if match['intent'] != previous.id]
        return {'action': args.action, 'id': previous.id}
    if args.minutes > settings.max_minutes:
        raise ValueError(f'minutes 不能超过 {settings.max_minutes:g}')
    if len(args.when) > settings.max_conditions:
        raise ValueError(f'最多 {settings.max_conditions} 个条件')
    if previous is None and len(declared.intents) >= settings.max_intents:
        raise ValueError(f'最多 {settings.max_intents} 个意图，请先完成或撤销已有意图')
    conditions = []
    for condition in args.when:
        item = condition.model_dump(exclude_none=True)
        if condition.people is not None and len(condition.people) > settings.max_people:
            raise ValueError(f'最多 {settings.max_people} 个账号')
        if condition.keywords is not None and len(condition.keywords) > settings.max_keywords:
            raise ValueError(f'最多 {settings.max_keywords} 个关键词')
        if condition.message_id is not None:
            if find_message(condition.message_id) is None:
                raise ValueError(f'当前场景不存在消息：{condition.message_id!r}')
            item['chain'] = [condition.message_id]
        if condition.type == 'at':
            item['due'] = now + item.pop('minutes') * 60
            item['fired'] = False
        conditions.append(item)
    identifier = f'i{declared.next_id}' if previous is None else previous.id
    intent = Intent(identifier, conditions, args.match or 'any', args.reason, now, now + args.minutes * 60,
                    source_turn, source_call)
    if previous is None:
        declared.next_id += 1
        declared.intents.append(intent)
    else:
        declared.intents[declared.intents.index(previous)] = intent
        declared.matches = [match for match in declared.matches if match['intent'] != identifier]
    return {'action': 'intend', 'id': identifier, 'updated': previous is not None}


def match_message(declared: Declared, message: ChatMessage, now: float) -> list[dict]:
    text = plain_text(message).casefold()
    matched = []
    for intent in declared.intents:
        values = []
        for condition in intent.conditions:
            kind = condition['type']
            if kind == 'person':
                value = message.sender.uid in condition['people']
            elif kind in {'thread', 'open_question'}:
                value = message.reply_to is not None and message.reply_to in condition['chain']
                if value and message.platform_message_id is not None:
                    condition['chain'] = (condition['chain'] + [message.platform_message_id])[-50:]
                if kind == 'open_question':
                    value = value or any(word in text for word in condition.get('keywords', []))
            elif kind == 'topic':
                value = any(word in text for word in condition['keywords'])
            else:
                value = False  # Timers only fire from tick, not from messages.
            values.append(value)
        if (any(values) if intent.match == 'any' else all(values)):
            matched.append(declared.candidate(intent, now, message.platform_message_id))
    return matched


def tick(declared: Declared, now: float) -> list[dict]:
    matched = []
    for intent in declared.intents:
        due = [condition for condition in intent.conditions
               if condition['type'] == 'at' and not condition['fired'] and condition['due'] <= now]
        if due:
            for condition in due:
                condition['fired'] = True
            matched.append(declared.candidate(intent, now, None))
    return matched


def next_due(declared: Declared) -> float | None:
    times = [intent.until for intent in declared.intents]
    times += [condition['due'] for intent in declared.intents for condition in intent.conditions
              if condition['type'] == 'at' and not condition['fired']]
    return min(times, default=None)


def persisted(state) -> dict:
    saved = asdict(state)
    for key in ('declared', 'disposition'):
        if saved[key] is None:
            del saved[key]
    return saved
