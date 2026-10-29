<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import Icon from './Icon.vue'

// One turn from the demo instance, replayed on a clock: wake, judge, look up, reply.
const T = {
  typing: 500, wake: 1300, card: 2000, think1: 2500, tool: 4300, toolDone: 5300, think2: 5700,
  reply: 6700, say1: 7300, say2: 8300, done: 8600, after1: 9600, after2: 10400, fade: 13200, end: 13800,
}
const thought1 = '小满在问零食，大家之前说过口味，先翻翻群里的记录'
const thought2 = '老周不吃辣，橘子点名要抹茶饼干'
const steps = [
  { label: '唤醒', icon: 'zap', at: T.wake },
  { label: '判断', icon: 'sparkles', at: T.think1 },
  { label: '查询', icon: 'search', at: T.tool },
  { label: '回复', icon: 'message-circle', at: T.reply },
]
const mark = withBase('/lenbot-mark.svg')
const colors: Record<string, string> = { 小满: '#e2809f', 老周: '#6f9fd8', 橘子: '#f0a868' }

const t = ref(T.after2 + 600)
const reduced = ref(false)
const root = ref<HTMLElement>()
let frame = 0
let origin = 0
let visible = true
let observer: IntersectionObserver | undefined

const stage = computed(() => steps.reduce((found, step, index) => (t.value >= step.at ? index : found), -1))
const at = (moment: number) => t.value >= moment
const typed = (text: string, start: number) => text.slice(0, Math.max(0, Math.floor((t.value - start) / 32)))
const progress = computed(() => Math.min(1, t.value / T.done))

function tick(now: number) {
  if (visible && !document.hidden) {
    t.value = now - origin
    if (t.value >= T.end) origin = now
  } else origin = now - t.value
  frame = requestAnimationFrame(tick)
}

function jump(index: number) {
  if (reduced.value) return
  origin = performance.now() - steps[index].at + 1
  t.value = steps[index].at
}

onMounted(() => {
  reduced.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced.value) return
  t.value = 0
  origin = performance.now()
  observer = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting))
  if (root.value) observer.observe(root.value)
  frame = requestAnimationFrame(tick)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  observer?.disconnect()
})
</script>

<template>
  <div ref="root" class="chat-demo" :class="{ fading: at(T.fade) }">
    <div class="rail" role="list">
      <button
        v-for="(step, index) in steps"
        :key="step.label"
        role="listitem"
        class="rail-step"
        :class="{ on: index === stage, past: index < stage }"
        @click="jump(index)"
      >
        <Icon :name="step.icon" :size="14" />
        <span>{{ step.label }}</span>
      </button>
      <span class="rail-bar" :style="{ transform: `scaleX(${progress})` }" />
    </div>

    <div class="head">
      <span class="group-avatar">桌</span>
      <span class="title">周末桌游局</span>
      <span class="meta">42 人 · 小然</span>
      <span class="live"><i />实时</span>
    </div>

    <div class="stream">
      <div class="msg"><span class="avatar" :style="{ background: colors['小满'] }">满</span><div>
        <div class="who">小满 <span class="time">14:37</span><Icon name="moon" :size="12" class="verdict" /></div>
        <div class="bubble">这周六还是老地方吗</div></div></div>
      <div class="msg"><span class="avatar" :style="{ background: colors['老周'] }">周</span><div>
        <div class="who">老周 <span class="time">14:38</span><Icon name="moon" :size="12" class="verdict" /></div>
        <div class="bubble">我带新到的那盒卡坦岛扩展</div></div></div>

      <div v-if="at(T.typing) && !at(T.wake)" class="msg"><span class="avatar" :style="{ background: colors['小满'] }">满</span>
        <div class="bubble typing"><i /><i /><i /></div></div>
      <div v-if="at(T.wake)" class="msg pop"><span class="avatar" :style="{ background: colors['小满'] }">满</span><div>
        <div class="who">小满 <span class="time">14:38</span><Icon name="zap" :size="12" class="verdict wake" /></div>
        <div class="bubble"><b class="mention">@小然</b> 周六带什么零食好</div></div></div>

      <div v-if="at(T.card)" class="turn pop">
        <div class="turn-head">
          <Icon name="sparkles" :size="15" class="spark" />
          <template v-if="at(T.done)"><span class="summary">被 @ 或回复 · 3 步 · 2 条发言</span></template>
          <template v-else><span class="summary">被 @ 或回复</span><span class="running"><i class="spinner" />进行中</span></template>
        </div>
        <div class="recall"><Icon name="brain" :size="13" />召回记忆 1 条</div>
        <div v-if="at(T.think1)" class="step pop">
          <span class="step-no">第 1 步</span>
          <p class="thought"><b>想法</b>{{ typed(thought1, T.think1) }}<i v-if="!at(T.tool)" class="caret" /></p>
          <div v-if="at(T.tool)" class="chip pop">
            <Icon name="search" :size="13" />
            <span class="tool">查询聊天记录</span>
            <code>零食 辣</code>
            <Icon v-if="at(T.toolDone)" name="check" :size="13" class="ok" />
            <i v-else class="spinner" />
          </div>
          <ul v-if="at(T.toolDone)" class="results pop">
            <li>老周 · 10 月 26 日：我一点辣都不吃</li>
            <li>橘子 · 10 月 26 日：零食我要抹茶饼干</li>
          </ul>
        </div>
        <div v-if="at(T.think2)" class="step pop">
          <span class="step-no">第 2 步</span>
          <p class="thought"><b>想法</b>{{ typed(thought2, T.think2) }}<i v-if="!at(T.reply)" class="caret" /></p>
        </div>
        <div v-if="at(T.reply)" class="step pop">
          <span class="step-no">第 3 步</span>
          <div class="says">
            <span class="chip small"><Icon name="message-circle" :size="12" />发言<Icon v-if="at(T.say1)" name="check" :size="12" class="ok" /><i v-else class="spinner" /></span>
            <span v-if="at(T.say1)" class="chip small pop"><Icon name="message-circle" :size="12" />发言<Icon v-if="at(T.say2)" name="check" :size="12" class="ok" /><i v-else class="spinner" /></span>
          </div>
        </div>
        <div v-if="at(T.done)" class="foot pop">首句 2.4 秒 · 6.1k 入 · 240 出</div>
      </div>

      <div v-if="at(T.reply) && !at(T.say1)" class="msg me"><div class="bubble typing"><i /><i /><i /></div><span class="avatar bot"><img :src="mark" alt="" /></span></div>
      <div v-if="at(T.say1)" class="msg me pop"><div>
        <div class="who">小然 <span class="time">14:39</span></div>
        <div class="bubble">我带薯片和果干吧 老周不吃辣 辣条就不拿啦</div></div><span class="avatar bot"><img :src="mark" alt="" /></span></div>
      <div v-if="at(T.say1) && !at(T.say2)" class="msg me"><div class="bubble typing"><i /><i /><i /></div><span class="avatar bot"><img :src="mark" alt="" /></span></div>
      <div v-if="at(T.say2)" class="msg me pop"><div>
        <div class="bubble">橘子要的抹茶饼干我也带一盒</div></div><span class="avatar bot"><img :src="mark" alt="" /></span></div>

      <div v-if="at(T.after1)" class="msg pop"><span class="avatar" :style="{ background: colors['橘子'] }">橘</span><div>
        <div class="who">橘子 <span class="time">14:39</span><Icon name="moon" :size="12" class="verdict" /></div>
        <div class="bubble">懂我</div></div></div>
      <div v-if="at(T.after2)" class="msg pop"><span class="avatar" :style="{ background: colors['老周'] }">周</span><div>
        <div class="who">老周 <span class="time">14:40</span><Icon name="moon" :size="12" class="verdict" /></div>
        <div class="bubble">那饮料我来</div></div></div>
    </div>
  </div>
</template>

<style scoped>
.chat-demo {
  position: relative; display: flex; flex-direction: column; height: 560px; border-radius: 22px; overflow: hidden;
  background: color-mix(in srgb, var(--vp-c-bg) 82%, transparent); border: 1px solid var(--lb-glass-line);
  box-shadow: 0 40px 80px -40px rgb(120 40 70 / 0.45), 0 0 0 1px rgb(255 255 255 / 0.04) inset;
  backdrop-filter: blur(18px) saturate(1.3); -webkit-backdrop-filter: blur(18px) saturate(1.3);
  font-size: 13.5px; text-align: left;
}

.rail { position: relative; display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; padding: 10px 10px 12px; border-bottom: 1px solid var(--vp-c-divider); }
.rail-step {
  display: flex; align-items: center; justify-content: center; gap: 6px; padding: 7px 0; border-radius: 10px;
  font-size: 12.5px; font-weight: 600; color: var(--vp-c-text-3); transition: color 0.3s, background-color 0.3s;
}
.rail-step.past { color: var(--vp-c-text-2); }
.rail-step.on { color: var(--lb-primary); background: var(--lb-soft); }
.rail-bar {
  position: absolute; left: 10px; right: 10px; bottom: 0; height: 2px; transform-origin: left;
  background: linear-gradient(90deg, var(--lb-primary), var(--lb-brand), var(--lb-peach));
}

.head { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--vp-c-divider); }
.group-avatar { width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center; font-size: 12px; font-weight: 700; color: #fff; background: linear-gradient(135deg, var(--lb-brand), var(--lb-peach)); }
.title { font-weight: 700; color: var(--vp-c-text-1); }
.meta { color: var(--vp-c-text-3); font-size: 12px; }
.live { margin-left: auto; display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--vp-c-text-2); }
.live i { width: 7px; height: 7px; border-radius: 50%; background: var(--lb-success); box-shadow: 0 0 0 0 var(--lb-success); animation: ping 2s infinite; }

.stream {
  flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: flex-end; gap: 10px; padding: 14px 16px 16px; overflow: hidden;
  transition: opacity 0.5s;
  mask-image: linear-gradient(to bottom, transparent 0, #000 56px);
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 56px);
}
.chat-demo.fading .stream { opacity: 0; }
.msg { display: flex; align-items: flex-end; gap: 8px; flex: none; }
.msg > div { min-width: 0; }
.msg.me { justify-content: flex-end; }
.msg.me .who { justify-content: flex-end; }
.avatar { flex: none; width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-size: 12px; font-weight: 700; }
.avatar.bot { background: var(--lb-soft); }
.avatar.bot img { width: 20px; height: 20px; }
.who { display: flex; align-items: center; gap: 6px; margin: 0 2px 4px; font-size: 12px; color: var(--vp-c-text-2); }
.time { color: var(--vp-c-text-3); font-size: 11px; }
.verdict { color: var(--vp-c-text-3); }
.verdict.wake { color: var(--lb-primary); }
.bubble { display: inline-block; padding: 8px 12px; border-radius: 4px 14px 14px 14px; background: var(--vp-c-bg-soft); color: var(--vp-c-text-1); line-height: 1.55; }
.msg.me .bubble { border-radius: 14px 4px 14px 14px; background: var(--lb-soft); }
.msg.me > div { display: flex; flex-direction: column; align-items: flex-end; }
.mention { color: var(--lb-primary); font-weight: 600; }
.typing { display: inline-flex; gap: 4px; padding: 12px 14px; }
.typing i { width: 6px; height: 6px; border-radius: 50%; background: var(--vp-c-text-3); animation: dot 1.2s infinite; }
.typing i:nth-child(2) { animation-delay: 0.15s; }
.typing i:nth-child(3) { animation-delay: 0.3s; }

.turn { flex: none; margin-left: 36px; padding: 10px 12px 12px; border-radius: 14px; border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg); display: grid; gap: 8px; }
.turn-head { display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 600; color: var(--vp-c-text-1); }
.spark { color: var(--lb-primary); }
.running { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; color: var(--vp-c-text-3); font-weight: 500; font-size: 12px; }
.recall { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--vp-c-text-2); }
.step { display: grid; gap: 6px; padding-left: 10px; border-left: 2px solid var(--vp-c-divider); }
.step-no { font-size: 11px; font-weight: 600; color: var(--vp-c-text-3); }
.thought { margin: 0; font-size: 12.5px; line-height: 1.6; color: var(--vp-c-text-2); }
.thought b { margin-right: 8px; color: var(--vp-c-text-1); font-weight: 600; }
.caret { display: inline-block; width: 1.5px; height: 13px; margin-left: 2px; vertical-align: -2px; background: var(--lb-primary); animation: blink 0.9s steps(1) infinite; }
.chip { display: inline-flex; align-items: center; gap: 6px; width: fit-content; padding: 5px 10px; border-radius: 999px; border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg-soft); font-size: 12px; color: var(--vp-c-text-2); }
.chip .tool { font-weight: 600; color: var(--vp-c-text-1); }
.chip code { font-size: 11.5px; padding: 1px 6px; border-radius: 5px; background: var(--vp-c-bg); color: var(--lb-primary); }
.chip.small { padding: 3px 9px; }
.ok { color: var(--lb-success); }
.results { margin: 0; padding: 0; list-style: none; display: grid; gap: 4px; }
.results li { font-size: 12px; padding: 5px 9px; border-radius: 8px; background: var(--vp-c-bg-soft); color: var(--vp-c-text-2); }
.says { display: flex; gap: 6px; flex-wrap: wrap; }
.foot { font-size: 11.5px; color: var(--vp-c-text-3); font-variant-numeric: tabular-nums; }
.spinner { width: 11px; height: 11px; border-radius: 50%; border: 1.6px solid color-mix(in srgb, var(--lb-primary) 25%, transparent); border-top-color: var(--lb-primary); animation: spin 0.8s linear infinite; }

.pop { animation: pop 0.42s var(--lb-ease) both; }
@keyframes pop { from { opacity: 0; transform: translateY(8px) scale(0.98); } to { opacity: 1; transform: none; } }
@keyframes dot { 0%, 60%, 100% { transform: translateY(0); opacity: 0.5; } 30% { transform: translateY(-3px); opacity: 1; } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes blink { 50% { opacity: 0; } }
@keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--lb-success) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 6px transparent; } }
@media (max-width: 520px) { .chat-demo { height: 600px; font-size: 13px; } .turn { margin-left: 0; } }
@media (prefers-reduced-motion: reduce) { .pop, .live i, .typing i, .spinner, .caret { animation: none; } }
</style>
