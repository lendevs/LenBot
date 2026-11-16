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
from .group_voice import describe as describe_group_voice
from .persona_avoid import avoidance_text
from .reply_feedback import reply_feedback
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
    if "attention" in names:
        system += "\n" + read_prompt("next_attention.md")
    if config.memory_plugin is not None:
        system += "\n" + Template(read_prompt("next_memory_plugin.md")).substitute(plugin=config.memory_plugin)
    elif "memory" in names:
        system += "\n" + Template(read_prompt("next_memory.md")).substitute(
            backend=config.memory.backend,
            backend_details=read_prompt(f"next_memory_{config.memory.backend}.md"),
        )
    elif config.memory is not None and config.memory.auto_recall:
        system += "\n" + Template(read_prompt("next_memory_recall.md")).substitute(
            read=read_prompt("next_memory_recall_read.md").strip() if "memory" in allowed_names else "")
    if "task" in names:
        system += "\n" + Template(read_prompt("next_tasks.md")).substitute(
            network=encode({"enabled": config.worker.egress.enabled, "mode": config.worker.egress.mode,
                           "allowed_hosts": (config.worker.egress.allowed_hosts
                                             if config.worker.egress.mode == "allowlist" else None),
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
        jargon=encode([{"词": item["term"], "群内用法": item["meaning"],
                        "适用语境": item["usage_condition"], "依据": item["evidence"], "来源": item["source"]} for item in terms]),
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
# Function characters too common to anchor a sentence template on their own.
TEMPLATE_FILLER = frozenset("的了是我你他她它在有和就也都不这那个一吧呢啊呀啦嘛哦么得地着过把被给让要会能说")
HAN_RUN = re.compile(r"[\u4e00-\u9fff]+")
HAN = re.compile(r"[\u4e00-\u9fff]")
SENTENCE_BREAK = re.compile(r"[。！？!?~～…\n]+")
CLAUSE_BREAK = re.compile(r"[，,。！？!?~～…；;：:、\s]+")
TEMPLATE_GRAM = 6


def _expressions(entries: Sequence[tuple[int, dict]]) -> list[tuple[str, dict]]:
    """The latest own ``say`` and ``react`` calls in the history, newest first."""
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
    return expressions[:HABIT_WINDOW]


def _common(values: Sequence[set[str]], enough: int) -> tuple[str, int] | None:
    """The longest value shared by the most texts, when at least ``enough`` share it."""
    frequency = Counter(value for found in values for value in found)
    best = sorted(frequency.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return best[0] if best and best[0][1] >= enough else None


def _prefixes(clause: str, shortest: int, longest: int) -> set[str]:
    run = HAN_RUN.match(clause)
    return set() if run is None else {run.group(0)[:size] for size in range(shortest, min(longest, len(run.group(0))) + 1)}


def _templates(texts: Sequence[str], enough: int, taken: Sequence[str], others: str) -> list[tuple[str, int]]:
    """Two fixed pieces with a changing middle that keep coming back in one sentence, such as 「越……越」."""
    occurrences = []
    for text in texts:
        found: dict[str, list[tuple[int, int, int]]] = {}
        for number, sentence in enumerate(SENTENCE_BREAK.split(text)):
            for run in HAN_RUN.finditer(sentence):
                for size in range(1, TEMPLATE_GRAM + 1):
                    for start in range(run.start(), run.end() - size + 1):
                        found.setdefault(sentence[start:start + size], []).append((number, start, start + size))
        occurrences.append((found, SENTENCE_BREAK.split(text)))
    frequency = Counter(gram for found, _ in occurrences for gram in found)
    usable = {gram for gram, count in frequency.items() if count >= enough
              and (len(gram) > 1 or gram not in TEMPLATE_FILLER)
              and not any(gram in word or word in gram for word in taken)
              and not (len(gram) > 1 and gram in others)}
    # A piece inside a longer one found in as many texts says nothing more.
    usable = {gram for gram in usable if not any(gram != longer and gram in longer and frequency[longer] == frequency[gram]
                                                 for longer in usable)}
    pairs: dict[tuple[str, str], tuple[int, set[str]]] = {}
    for found, sentences in occurrences:
        seen: dict[tuple[str, str], str] = {}
        grams = [(gram, place) for gram in usable for place in found.get(gram, ())]
        for first, (number, _, first_end) in grams:
            for second, (other, second_start, _) in grams:
                if other == number and second_start > first_end and len(first) + len(second) >= 3:
                    seen.setdefault((first, second), sentences[number][first_end:second_start])
        for pair, middle in seen.items():
            count, middles = pairs.get(pair, (0, set()))
            pairs[pair] = (count + 1, middles | {middle})
    chosen: list[tuple[str, int]] = []
    used: list[str] = []
    for (first, second), (count, middles) in sorted(
            pairs.items(), key=lambda item: (-item[1][0], -len(item[0][0]) - len(item[0][1]), item[0])):
        if count < enough or len(chosen) == 2:
            break
        # The same middle every time is one fixed phrase, which the word count already covers.
        if len(middles) < 2 or any(piece in other or other in piece for piece in (first, second) for other in used):
            continue
        chosen.append((f"{first}……{second}", count))
        used += [first, second]
    return chosen


def recent_habits(entries: Sequence[tuple[int, dict]], heard: Sequence[str] = ()) -> str | None:
    """Name what the latest own expressions in the history keep repeating, for the next one to vary.

    The model reads its earlier lines as the strongest example of how it talks, so a phrase or a
    sentence shape that slipped in a few times tends to stay. Words, the opening and ending of each
    line, the opening of its last clause and two-piece templates are counted; ``heard`` is what
    others said recently, and words they use belong to the topic and are not named. Pictures sent
    with text are part of the persona's voice and are not counted.
    """
    expressions = _expressions(entries)
    if len(expressions) < 5:
        return None
    texts = [arguments["content"] for name, arguments in expressions
             if name == "say" and isinstance(arguments.get("content"), str)]
    habits = []
    others = "\n".join(heard)
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
        chosen = []
        for gram, count in sorted(frequency.items(), key=lambda item: (-item[1], -len(item[0]), item[0])):
            if count < enough or len(chosen) == 3:
                break
            if gram in others or any(gram in other or other in gram for other, _ in chosen):
                continue
            chosen.append((gram, count))
        habits.extend(f"{count} 条用了「{gram}」" for gram, count in chosen)
        habits.extend(_shapes(texts, [gram for gram, _ in chosen], others))
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


def _shapes(texts: Sequence[str], words: Sequence[str], others: str) -> list[str]:
    """Sentence shapes shared by half of the texts: how they open, end and close, and templates."""
    enough = max(4, math.ceil(len(texts) / 2))
    taken = list(words)
    shapes = []
    openings = [{prefix for prefix in _prefixes(text.lstrip(), 2, TEMPLATE_GRAM) if prefix not in others} for text in texts]
    if (opening := _common(openings, enough)) is not None and not any(
            opening[0] in word or word in opening[0] for word in taken):
        shapes.append(f"{opening[1]} 条开头都是「{opening[0]}」")
        taken.append(opening[0])
    tails = []
    for text in texts:
        squeezed = re.sub(r"\s", "", text)
        last = None
        for last in HAN.finditer(squeezed):
            pass
        tail = squeezed if last is None else squeezed[last.end():]
        tails.append({tail[-size:] for size in range(1, min(6, len(tail)) + 1)})
    if (ending := _common(tails, enough)) is not None:
        shapes.append(f"{ending[1]} 条结尾都是「{ending[0]}」")
    closings = []
    for text in texts:
        clauses = [clause for clause in CLAUSE_BREAK.split(text) if HAN.search(clause)]
        closings.append(_prefixes(clauses[-1], 1, 3) if len(clauses) > 1 else set())
    if (closing := _common(closings, enough)) is not None:
        shapes.append(f"{closing[1]} 条最后一句都用「{closing[0]}」起头")
        taken.append(closing[0])
    shapes.extend(f"{count} 条用了「{template}」这样的句式" for template, count in _templates(texts, enough, taken, others))
    return shapes


RECENT_SECONDS = 600


def current_attention(config: LabConfig, store: Store) -> str:
    attention = store.load_attention(config.scene)
    now, zone = store.now(), ZoneInfo(config.timezone)
    window = config.attention.focus_seconds
    followups = ({} if attention is None or config.attention.only_direct
                 else attention.get('followups') or {})
    waiting = [('任何人' if who == '*' else who) + ' 至 ' + datetime.fromtimestamp(at + window, zone).strftime('%H:%M:%S')
               for who, at in followups.items() if at + window > now]
    text = '等接话：' + ('、'.join(waiting) if waiting else '无')
    if config.scene.split(':', 2)[1] == 'group':
        spoken = sum(at > now - RECENT_SECONDS for at in speech_quota(store, config).times)
        text += (f'\n最近 {RECENT_SECONDS // 60} 分钟：你说了 {spoken} 句，'
                 f'群里其他人 {store.count_received(config.scene, now - RECENT_SECONDS)} 条')
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
        # How members here write, measured by the latest upkeep pass; None until one ran.
        self.group_voice: dict | None = None
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
        return self.render_items(self.batch_items(messages), reason=reason)

    def batch_items(self, messages: Sequence[ChatMessage]) -> list[tuple[ChatMessage, ChatMessage | None, dict[int, str]]]:
        """Each message with its quoted message and audio captions, read once for repeated rendering."""
        records = AudioStore(self.store)
        return [(message, None if message.reply_to is None else
                 self.store.find_message(message.scene, message.reply_to),
                 records.captions(message.scene, message.platform_message_id)) for message in messages]

    def render_items(self, items: Sequence[tuple[ChatMessage, ChatMessage | None, dict[int, str]]], *,
                     reason: str | None = None) -> str:
        return render_batch(items, timezone=self.config.timezone, reason=reason)

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
        profile = (None if self.memory is None or self.config.memory_plugin is not None
                   else await self.memory.read_group_profile(self.config.scene))
        if profile is not None:
            state = {**state, "content": state["content"] + "\n" + Template(
                read_prompt("next_group_profile.md")).substitute(profile=profile.strip())}
        state = {**state, 'content': state['content'] + '\n' + current_attention(self.config, self.store)}
        state = {**state, 'content': '\n'.join([state['content'], *self.references(entries)])}
        return [{"role": "system", "content": self.system}] + project_history(recap, entries) + [state]

    def references(self, entries: list[tuple[int, dict]]) -> list[str]:
        """The turn's closing reference material, in order: how members here write, what the own
        latest lines keep repeating, how members reacted to the own recent lines, then the persona's own
        prohibitions, which always stay last, closest to what the model writes next. Material about the scene
        goes before them."""
        references = []
        if self.group_voice is not None:
            references.append(describe_group_voice(self.group_voice))
        heard = [plain_text(message) for message in self.store.recent_context_messages(self.config.scene, limit=50)
                 if not message.is_self]
        references.append(recent_habits(entries, heard))
        references.append(reply_feedback(self.config, self.store))
        references.append(avoidance_text(self.persona))
        return [text for text in references if text is not None]
