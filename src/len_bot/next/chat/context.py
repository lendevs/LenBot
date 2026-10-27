"""Assemble scene prompt material from role files and existing conversation records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime
import json
import math
from pathlib import Path
import re
from string import Template
from zoneinfo import ZoneInfo

from ..media.audio_store import AudioStore
from ..config import LabConfig
from .declarations import Declared
from .recap import project_history
from ..models.limits import speech_quota
from ..models.projection import project_messages, project_old_results
from ..tools.discovery import deferred_names, discovery_view
from ..learning.jargon_store import JargonStore
from ..memory.service import MemoryService
from ..platform.messages import ChatMessage, plain_text, render_batch, render_message, render_text
from ..persona.profile import EXPRESSION_FILES, Persona, Style, select_examples
from .schedule import describe
from ..tools.skills import Skill
from ..storage.store import Store, encode
from ..work.store import TaskStore
from .schedule_store import ScheduleStore
from ..prompt_files import read_prompt


PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def character_material(config: LabConfig | None, persona: Persona) -> str:
    """The persona section of the system text; ``config`` adds what one scene says about it."""
    scene_details = {}
    if config is not None and config.persona_aliases:
        scene_details["本场景对你的称呼"] = config.persona_aliases
    if config is not None and config.relationships:
        scene_details["关系说明（账号 → 描述）"] = dict(sorted(config.relationships.items()))
    if config is not None and config.behavior_addendum is not None:
        scene_details["本场景行为补充"] = config.behavior_addendum
    scene_material = (Template(read_prompt("next_scene_persona.md")).substitute(
        details=encode(scene_details)) if scene_details else "")
    return Template(read_prompt("next_character.md")).substitute(
        brief=persona.brief, self_reference="、".join(persona.self_reference),
        aliases="、".join(persona.aliases), behavior=persona.behavior, voice=persona.voice,
        boundaries=persona.boundaries,
        examples="\n\n".join(f"{e.context}\n台词：{e.line}" for e in select_examples(persona)),
        scene_material=scene_material,
    )


def expression_rule(persona: Persona, name: str) -> str:
    """One expression rule file: the persona's own version, otherwise the framework's.

    A persona's file may use ``$name`` like the framework's, and any other ``$`` stays as written. The
    framework's chat examples are not a template.
    """
    own = persona.expression.get(name)
    if own is not None:
        return Template(own).safe_substitute(name=persona.name)
    text = read_prompt(EXPRESSION_FILES[name])
    return text if name == "chat_examples.md" else Template(text).substitute(name=persona.name)


def style_text(style: Style) -> str:
    """How one sampled style is added to a turn's reference material."""
    return Template(read_prompt("next_style.md")).substitute(name=style.name, note="" if style.note is None else style.note)


def build_system(config: LabConfig, persona: Persona, allowed: list[dict], *, platform: bool,
                 skills: tuple[Skill, ...] = (),
                 external: list[dict] = (), discovered: Sequence[str] = (),
                 external_info: Sequence[dict] = ()) -> str:
    """Render the actual stable mind system text for this scene and outlet."""
    allowed_names = {tool["function"]["name"] for tool in allowed}
    deferred = deferred_names(allowed_names, config)
    names = (allowed_names - deferred) | (set(discovered) & allowed_names)
    info_by_name = {info["discovery"]["name"]: info for info in external_info}
    deferred = [tool for tool in allowed if tool["function"]["name"] in deferred] + list(external)
    system = Template(read_prompt("next_mind.md")).substitute(
        name=persona.name, scene=config.scene, bot_id=config.bot_id,
        character=character_material(config, persona),
        response_choice=expression_rule(persona, "response_choice.md"),
        expression_principles=expression_rule(persona, "expression_principles.md"),
        outlet=read_prompt(("next_platform_outlet.md" if platform else
                           "next_simulated_outlet.md")).strip(),
    )
    system += "\n" + expression_rule(persona, "chat_examples.md")
    if "react" in names:
        system += "\n" + read_prompt("next_react.md")
    if "schedule" in names:
        system += "\n" + read_prompt("next_schedule.md")
    if "memory" in names:
        system += "\n" + Template(read_prompt("next_memory.md")).substitute(
            backend=config.memory.backend,
            backend_details=read_prompt(f"next_memory_{config.memory.backend}.md"),
        )
    elif config.memory is not None and config.memory.auto_recall:
        system += "\n" + read_prompt("next_memory_recall.md")
    if "task" in names:
        system += "\n" + Template(read_prompt("next_tasks.md")).substitute(
            network=encode({"enabled": config.worker.egress.enabled,
                           "max_task_bytes": (config.worker.egress.max_task_bytes
                               if config.tasks.egress_max_task_bytes is None else config.tasks.egress_max_task_bytes),
                           "max_daily_bytes": (config.worker.egress.max_scene_daily_bytes
                               if config.tasks.egress_max_daily_bytes is None else config.tasks.egress_max_daily_bytes)}),
        )
    if "send_file" in names:
        system += "\n" + read_prompt("next_files.md")
    if 'host_manage' in names:
        system += '\n' + read_prompt('next_host_manage.md')
    if "delegate" in names and skills:
        system += "\n" + Template(read_prompt("next_skills.md")).substitute(
            catalog=encode([{"name": skill.name, "description": skill.description}
                            for skill in skills if not skill.disable_model_invocation]),
        )
    if "tool_search" in names:
        system += "\n" + Template(read_prompt("next_tools.md")).substitute(
            catalog="\n".join(f"- {item['name']} [{item['source']}]：{item['description']}"
                for item in [info_by_name[tool["function"]["name"]]["discovery"]
                             if tool["function"]["name"] in info_by_name else discovery_view(tool)
                             for tool in deferred]) or "（当前没有允许发现的低频工具）")
    guides = {}
    discovered_names = set(discovered)
    for info in external_info:
        item = info["discovery"]
        if item["name"] in discovered_names and info["instructions"]:
            guides[item["source"]] = info["instructions"]
    for source, guide in guides.items():
        system += f"\n<{source}工具指南>\n{guide}\n</{source}工具指南>"
    return system


def jargon_context(config: LabConfig, store: Store, messages: list[ChatMessage], *,
                   intent: str | None = None) -> str | None:
    if config.learning is None:
        return None
    excluded = (config.bot_id, *config.attention.other_bot_ids)
    texts = [plain_text(message) for message in messages
             if not message.is_self and message.send_status == "received"
             and message.sender.uid not in excluded]
    if intent is not None:
        texts.append(intent)
    terms = JargonStore(store).matches(config.scene, texts, limit=10)
    if not terms:
        return None
    return Template(read_prompt("next_jargon_context.md")).substitute(
        jargon=encode([{"词": item["term"], "含义": item["meaning"], "来源": item["source"]} for item in terms]),
    )


def turn_state(config: LabConfig, store: Store, *, now: float,
               expression_style: str | None = None, recalled: str | None = None) -> dict:
    """Read the current scene's pending work and per-request reference material."""
    moment = datetime.fromtimestamp(now, ZoneInfo(config.timezone)).isoformat(timespec="seconds")
    state = {"role": "user", "content": f"本轮开始时间：{moment}"}
    muted_until = store.bot_muted_until(config.scene, config.bot_id)
    if muted_until is not None:
        state["content"] += "\n平台通知：当前 Bot 禁言至 " + datetime.fromtimestamp(
            muted_until, ZoneInfo(config.timezone)).isoformat(timespec="seconds")
    quota = speech_quota(store, config)
    if quota.limit is not None and quota.remaining * 5 <= quota.limit:
        state["content"] += f"\n本群最近一小时已发言 {quota.used} 条，上限 {quota.limit} 条"
        if quota.remaining:
            state["content"] += f"，还剩 {quota.remaining} 条。"
        else:
            back = datetime.fromtimestamp(quota.until(direct=False), ZoneInfo(config.timezone)).strftime("%H:%M")
            state["content"] += (f"，已用完，{back} 起恢复；被 @、被回复、私聊、处理提醒或任务结果时还能说 {quota.reserve_left} 条。"
                                 if quota.reserve_left else f"，已用完，{back} 起恢复。")
    schedules = ScheduleStore(store).list_schedules(config.scene, limit=21)
    if schedules:
        state["content"] += "\n<未完成安排>\n" + "\n\n".join(
            describe(item, preview=True) for item in schedules[:20]) + "\n</未完成安排>"
        if len(schedules) > 20:
            state["content"] += "\n这里只列前 20 条；schedule_list 可继续查看。"
    tasks = TaskStore(store).list(config.scene, limit=21)
    if tasks:
        state["content"] += "\n<未完成工作>\n" + encode([
            {"id": item.id, "requester": item.requester, "status": item.status,
             **({"question": item.question} if item.question is not None else {})}
            for item in tasks[:20]]) + "\n</未完成工作>"
        if len(tasks) > 20:
            state["content"] += "\n这里只列前20项；task可继续查看。"
    if expression_style is not None:
        state["content"] += "\n" + expression_style
    if recalled is not None:
        state["content"] += "\n<相关长期记忆>\n" + recalled + "\n</相关长期记忆>"
    jargon = jargon_context(config, store, store.recent_context_messages(config.scene))
    if jargon is not None:
        state["content"] += "\n" + jargon
    state["content"] = Template(read_prompt("next_turn_state.md")).substitute(state=state["content"])
    return state


HABIT_WINDOW = 8
# Interjections: the only single characters worth naming as a habit. Sentence-final particles such
# as 吧、呢、啊 are ordinary grammar and stay out.
HABIT_CHARACTERS = frozenset("草哼呜哇诶欸嘿喵捏哈噢嗷嘻")
HAN_RUN = re.compile(r"[\u4e00-\u9fff]+")


def recent_habits(entries: Sequence[tuple[int, dict]], heard: Sequence[str] = ()) -> str | None:
    """Name what the latest own expressions in the history keep repeating, for the next one to vary.

    The model reads its earlier lines as the strongest example of how it talks, so a phrase that
    slipped in a few times tends to stay. ``heard`` is what others said recently; words they use
    belong to the topic and are not named. Punctuation and pictures sent with text are part of the
    persona's voice and are not counted.
    """
    expressions = []
    for _, message in reversed(entries):
        if message["role"] != "assistant":
            continue
        for call in reversed(message.get("tool_calls") or []):
            if call["function"]["name"] not in ("say", "react"):
                continue
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except ValueError:
                continue
            if isinstance(arguments, dict):
                expressions.append((call["function"]["name"], arguments))
        if len(expressions) >= HABIT_WINDOW:
            break
    expressions = expressions[:HABIT_WINDOW]
    if len(expressions) < 5:
        return None
    texts = [arguments["content"] for name, arguments in expressions
             if name == "say" and isinstance(arguments.get("content"), str)]
    habits = []
    if texts:
        enough = max(4, math.ceil(len(texts) * 0.6))
        frequency = Counter()
        for text in texts:
            grams = set()
            for run in HAN_RUN.findall(text):
                for size in range(1, 5):
                    grams.update(run[start:start + size] for start in range(len(run) - size + 1)
                                 if size > 1 or run[start] in HABIT_CHARACTERS)
            frequency.update(grams)
        others = "\n".join(heard)
        chosen = []
        for gram, count in sorted(frequency.items(), key=lambda item: (-item[1], -len(item[0]), item[0])):
            if count < enough or len(chosen) == 3:
                break
            if gram in others or any(gram in other or other in gram for other, _ in chosen):
                continue
            chosen.append((gram, count))
        habits.extend(f"{count} 条用了「{gram}」" for gram, count in chosen)
    files = Counter()
    for name, arguments in expressions:
        choice = arguments.get("sticker") if name == "say" else arguments
        if isinstance(choice, dict) and isinstance(choice.get("file"), str):
            files[choice["file"]] += 1
    if files and (uses := files.most_common(1)[0][1]) >= 3:
        habits.append(f"同一张图用了 {uses} 次")
    if not habits:
        return None
    return Template(read_prompt("next_recent_habits.md")).substitute(
        count=len(expressions), habits="，".join(habits))


def current_attention(config: LabConfig, store: Store) -> str:
    attention = store.load_attention(config.scene)
    last = None if attention is None else attention.get('last_contact_at')
    closed = None if attention is None else attention.get('focus_closed_at')
    until = None if last is None else last + config.attention.focus_seconds
    active = (not config.attention.only_direct and until is not None and until > store.now()
              and (not config.attention.close_focus_on_silence or closed is None))
    zone = ZoneInfo(config.timezone)
    text = ('至 ' + datetime.fromtimestamp(until, zone).strftime('%H:%M:%S') if active else '已关闭')
    if config.attention.close_focus_on_silence and closed is not None:
        text += '（' + datetime.fromtimestamp(closed, zone).strftime('%H:%M:%S') + ' 沉默后关闭）'
    text = '对话继续：' + text
    if attention is not None:
        disposition = attention.get('disposition')
        if disposition is not None and disposition['until'] > store.now():
            text += '\n上次局部收尾：' + encode(disposition)
        settings = config.attention.declarations
        if settings is not None and settings.mode != 'context' and attention.get('declared') is not None:
            declared = Declared.load(attention['declared'])
            text += '\n持续关注：' + encode(declared.view(store.now()))
            text += '\n本轮候选：' + encode(declared.turn_matches)
    return '<当前关注>\n' + text + '\n</当前关注>'


class ChatContext:
    """Scene materials shared by model requests, expression and panel views."""

    def __init__(self, config: LabConfig, persona: Persona, store: Store, *,
                 platform: bool, memory: MemoryService | None):
        self.config, self.persona, self.store = config, persona, store
        self.platform, self.memory = platform, memory
        self.host_state: str | None = None
        self.system: str

    def configure_tools(self, allowed: list[dict], external: list[dict], *, skills: tuple[Skill, ...],
                        external_info: Sequence[dict] = ()) -> None:
        self.allowed, self.external, self.skills = allowed, external, skills
        self.external_info = external_info
        self.refresh_tools()

    def refresh_tools(self) -> None:
        self.system = build_system(self.config, self.persona, self.allowed, platform=self.platform,
                                   skills=self.skills, external=self.external, external_info=self.external_info,
                                   discovered=self.store.load_discovered_tools(self.config.scene))

    def render(self, message: ChatMessage) -> str:
        quote = (None if message.reply_to is None else
                 self.store.find_message(message.scene, message.reply_to))
        return render_message(message, timezone=self.config.timezone, reply=quote,
                              audio=AudioStore(self.store).captions(message.scene, message.platform_message_id))

    def batch(self, messages: Sequence[ChatMessage], *, reason: str | None = None) -> str:
        records = AudioStore(self.store)
        return render_batch([
            (message, None if message.reply_to is None else
             self.store.find_message(message.scene, message.reply_to),
             records.captions(message.scene, message.platform_message_id)) for message in messages
        ], timezone=self.config.timezone, reason=reason)

    def render_text(self, message: ChatMessage) -> str:
        quote = (None if message.reply_to is None else
                 self.store.find_message(message.scene, message.reply_to))
        return render_text(message, reply=quote,
                           audio=AudioStore(self.store).captions(message.scene, message.platform_message_id))

    @staticmethod
    def conversation_entries(entries: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
        return [(seq, message) for seq, message in entries
                if not (message['role'] == 'user' and isinstance(message['content'], str)
                        and message['content'].startswith('宿主启动状态：'))]

    def project_entries(self, entries: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
        entries = self.conversation_entries(entries)
        return [(seq, projected) for seq, message in project_old_results(
            entries, self.config.compaction.keep_recent_tokens)
            for projected in project_messages([message], self.config.models.roles.mind.history_policy)]

    async def project(self, recap: str | None, entries: list[tuple[int, dict]], state: dict) -> list[dict]:
        self.refresh_tools()
        entries = self.project_entries(entries)
        if self.host_state is not None:
            state = {**state, 'content': state['content'] + '\n<宿主恢复状态>\n' + self.host_state + '\n</宿主恢复状态>'}
        profile = None if self.memory is None else await self.memory.read_group_profile(self.config.scene)
        if profile is not None:
            state = {**state, "content": state["content"] + "\n" + Template(
                read_prompt("next_group_profile.md")).substitute(profile=profile.strip())}
        state = {**state, 'content': state['content'] + '\n' + current_attention(self.config, self.store)}
        heard = [plain_text(message) for message in self.store.recent_context_messages(self.config.scene, limit=50)
                 if not message.is_self]
        habits = recent_habits(entries, heard)
        if habits is not None:
            state = {**state, 'content': state['content'] + '\n' + habits}
        return [{"role": "system", "content": self.system}] + project_history(recap, entries) + [state]
