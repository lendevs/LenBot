"""How members reacted to the bot's own recent lines reaches the model as reference material, before the persona's
own prohibitions, which stay last."""

import asyncio
import json

import pytest

from len_bot.next.chat.attention import SceneRunner
from len_bot.next.chat.session import Chat
from len_bot.next.configuration.learning import LearningSettings
from len_bot.next.models.client import ChatModel
from len_bot.next.platform.messages import ChatMessage, Segment, Sender
from len_bot.next.storage.store import Store
from test_attention_protocol import START, message, response
from test_next_native_models import peer_server
from test_next_persona_avoid import _persona
from test_next_persona_permissions import SCENE, _config

OTHER = 'onebot:group:80002'
HEAD = '<群友对你最近几句话的反应>'
TAIL = '</群友对你最近几句话的反应>'


def own_line(store, scene, text, at):
    sent = ChatMessage(id=f'own-{at}', platform='onebot', bot_id='onebot:90001', scene=scene,
                       platform_message_id=f'p{at}', sender=Sender('onebot:90001', '合成角色', None, None),
                       time=at, segments=[Segment('text', {'text': text})], reply_to=None, mentions_bot=False,
                       is_self=True, send_status='sent')
    return store.start_outgoing(sent, persona_id='plain')


def judged(store, scene, text, at, reaction, reason):
    seq = own_line(store, scene, text, at)
    with store.db:
        entry = store.db.execute("SELECT COALESCE(MAX(entry_seq),0)+1 FROM reply_effects").fetchone()[0]
        store.db.execute(
            "INSERT INTO reply_effects(scene,entry_seq,turn_id,channels,message_seqs,planned_parts,first_sent_at,"
            "last_sent_at,deadline,observed_seqs,closed_at,reaction,reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (scene, entry, None, '["ambient"]', json.dumps([seq]), 1, at, at, at + 180, '[1]', at + 180,
             reaction, reason))


def instance(tmp_path):
    package, persona = _persona(tmp_path)
    config = _config(tmp_path / 'instance', package)
    config.compaction.input_tokens = 20000
    config.models.roles.mind.context_window_tokens = 64000
    config.limits.messages_per_hour = None
    config.attention.speech_interval_seconds = 0
    config.learning = LearningSettings(extract=False, reply_effects=True)
    return config, persona


def fill(store):
    now = START
    judged(store, SCENE, '三天前的一句', now - 3 * 86400 - 1, 'negative', '过期')
    judged(store, SCENE, '最早的一句，会被挤掉', now - 600, 'continue', '挤掉')
    judged(store, SCENE, '周末一起去爬山吧', now - 500, 'continue', '群友接着问几点出发')
    judged(store, SCENE, '快去睡觉啦，不然明天起不来哦~', now - 400, 'negative', '群友说别管我')
    judged(store, SCENE, '突然联想到这个像极了小时候在外婆家院子里追着蝴蝶跑一下午最后摔进泥坑里的样子，哈哈哈哈哈哈',
           now - 300, 'unrelated', '群友在聊别的游戏')
    judged(store, SCENE, '说不准是不是在接我', now - 250, 'uncertain', '看不出')
    judged(store, SCENE, '这首歌是周三发的', now - 200, 'correct', '群友说是周四')
    judged(store, SCENE, '哈哈哈对', now - 100, 'agree', '')
    judged(store, SCENE, '新游戏开服了吗', now - 50, 'agree', '群友说开了还发了截图')
    judged(store, OTHER, '别的群里的话', now - 10, 'agree', '别的群')


@pytest.mark.asyncio
async def test_reactions_to_own_lines_reach_the_model_before_the_persona_prohibitions(tmp_path):
    config, persona = instance(tmp_path)
    requests, now = [], [START]
    server = await peer_server([response('say', {'content': '开了', 'end_turn': True}, 'call-0')], requests)
    async with server:
        config.models.providers['synthetic'].base_url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1'
        with Store(config.database, now=lambda: now[0]) as store:
            fill(store)
            async with ChatModel(config.model_settings('mind')) as model:
                live = SceneRunner(Chat(config, persona, store, model, now=lambda: now[0]), lambda _: None)
                live.closing = True
                live.receive(message(70001, 1, '新游戏开服了没', direct=True))
                now[0] += config.attention.direct_max_seconds
                await asyncio.wait_for(live.run(), 5)
    assert len(requests) == 1
    content = requests[0][2]['messages'][-1]['content']
    content = content if isinstance(content, str) else ''.join(block.get('text', '') for block in content)
    block = content[content.index(HEAD):content.index(TAIL)]
    taken, missed = block.split('有人接：')[1].split('没接上：')
    assert taken.strip().splitlines() == [
        '- 「新游戏开服了吗」附和：群友说开了还发了截图', '- 「哈哈哈对」附和', '- 「周末一起去爬山吧」接着聊：群友接着问几点出发']
    assert missed.strip().splitlines() == [
        '- 「这首歌是周三发的」被纠正：群友说是周四',
        # Long lines are cut, so the section stays short.
        '- 「突然联想到这个像极了小时候在外婆家院子里追着蝴蝶跑一下午最后摔进泥坑里的样子，哈…」没人接这句：群友在聊别的游戏',
        '- 「快去睡觉啦，不然明天起不来哦~」被嫌弃：群友说别管我']
    for absent in ('三天前', '挤掉', '说不准', '别的群'):
        assert absent not in block
    # The persona's own prohibitions still close the material.
    assert content.index(TAIL) < content.index('<角色材料里带否定的原句>')
    assert content.rstrip().endswith('</角色材料里带否定的原句>')


@pytest.mark.asyncio
async def test_no_section_without_reply_effects_or_judged_lines(tmp_path):
    config, persona = instance(tmp_path)
    from len_bot.next.chat.context import ChatContext
    from len_bot.next.chat.tools import build_tools
    state = {'role': 'user', 'content': '本轮开始时间：2026-10-21T00:00:00+00:00'}
    with Store(config.database, now=lambda: START) as store:
        context = ChatContext(config, persona, store, platform=False, memory=None)
        context.configure_tools(build_tools(config, persona, platform=False), [], skills=())
        judged(store, SCENE, '说不准是不是在接我', START - 60, 'uncertain', '看不出')
        assert HEAD not in (await context.project(None, [], state))[-1]['content']
        judged(store, SCENE, '新游戏开服了吗', START - 30, 'agree', '群友说开了')
        assert HEAD in (await context.project(None, [], state))[-1]['content']
        config.learning = LearningSettings(extract=False, reply_effects=False)
        assert HEAD not in (await context.project(None, [], state))[-1]['content']
