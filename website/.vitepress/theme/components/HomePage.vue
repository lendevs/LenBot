<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import CardImage from './CardImage.vue'
import ChatDemo from './ChatDemo.vue'
import DeployPicker from './DeployPicker.vue'
import Icon from './Icon.vue'
import PanelShowcase from './PanelShowcase.vue'
import StepRail from './StepRail.vue'

const words = ['何时开口', '回复谁', '先查什么', '何时跟进']
const word = ref(words[0])
let timer = 0

function typeLoop(index: number, length: number, deleting: boolean) {
  const target = words[index]
  word.value = target.slice(0, length)
  if (!deleting && length < target.length) timer = window.setTimeout(() => typeLoop(index, length + 1, false), 110)
  else if (!deleting) timer = window.setTimeout(() => typeLoop(index, length, true), 1900)
  else if (length > 0) timer = window.setTimeout(() => typeLoop(index, length - 1, true), 55)
  else timer = window.setTimeout(() => typeLoop((index + 1) % words.length, 0, false), 260)
}

const capabilities = [
  { name: 'listen', alt: '何时开口', link: '/use/chatting' },
  { name: 'lookup', alt: '先查再答', link: '/connect/web' },
  { name: 'follow', alt: '定时提醒', link: '/use/tasks' },
  { name: 'memory', alt: '长期记忆', link: '/use/memory' },
  { name: 'persona', alt: '角色包', link: '/use/personas' },
  { name: 'plugin', alt: 'Python 插件', link: '/use/plugins' },
]

const playground = [
  { icon: 'user-plus', text: '添加群友，设置昵称和身份' },
  { icon: 'at-sign', text: '以任一群友的身份发言、@ 或回复' },
  { icon: 'copy', text: '复制群内最近 20、50、100 条消息作为初始上下文' },
  { icon: 'shield-check', text: '独立的空白记忆，回复不发送到 QQ' },
]

const map = [
  { icon: 'rocket', title: '开始', links: [
    ['认识 LenBot', '/start/introduction'], ['快速开始', '/start/quick-start'], ['首次配置', '/start/first-setup'], ['对话测试', '/start/playground'],
  ] },
  { icon: 'plug', title: '接入', links: [
    ['QQ（OneBot）', '/connect/onebot'], ['模型与用量', '/connect/models'], ['联网与工具', '/connect/web'],
  ] },
  { icon: 'layout-dashboard', title: '使用', links: [
    ['面板一览', '/use/panel'], ['在群里聊天', '/use/chatting'], ['角色管理', '/use/personas'], ['记忆与学习', '/use/memory'], ['插件管理', '/use/plugins'],
  ] },
  { icon: 'puzzle', title: '开发', links: [
    ['写角色包', '/develop/personas'], ['写插件', '/develop/plugins'], ['参与开发', '/develop/contributing'],
  ] },
]

function spotlight(event: PointerEvent) {
  const target = event.currentTarget as HTMLElement
  const box = target.getBoundingClientRect()
  target.style.setProperty('--mx', `${event.clientX - box.left}px`)
  target.style.setProperty('--my', `${event.clientY - box.top}px`)
}

onMounted(() => {
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) typeLoop(0, words[0].length, false)
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="home">
    <div class="aurora" aria-hidden="true"><i /><i /><i /></div>
    <div class="grid-bg" aria-hidden="true" />

    <section class="hero">
      <div class="hero-copy">
        <img class="hero-mark" :src="withBase('/lenbot-mark-animated.svg')" alt="" />
        <h1><span class="name">LenBot</span><span class="tag">自主决策的群聊 Agent</span></h1>
        <p class="typed">
          <span class="word">{{ word }}<i class="caret" /></span>
          <span class="rest">由同一个聊天模型决定</span>
        </p>
        <p class="fact">接入 QQ（OneBot v11），需要一个聊天模型和它的 API Key。</p>
        <div class="actions">
          <a class="btn primary" :href="withBase('/start/quick-start')">快速开始<Icon name="arrow-right" :size="16" /></a>
          <a class="btn" :href="withBase('/start/playground')">对话测试</a>
          <a class="btn ghost" href="https://github.com/lendevs/LenBot"><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z"/></svg>GitHub</a>
        </div>
      </div>
      <div class="hero-demo"><ChatDemo /></div>
    </section>

    <section class="section">
      <h2 class="reveal">能力</h2>
      <div class="caps">
        <a
          v-for="(item, index) in capabilities"
          :key="item.name"
          class="cap reveal"
          :style="{ '--i': index % 3 }"
          :href="withBase(item.link)"
          @pointermove="spotlight"
        >
          <CardImage :name="item.name" :alt="item.alt" />
        </a>
      </div>
    </section>

    <section class="section playground">
      <div class="pg-copy reveal">
        <h2>对话测试</h2>
        <ul>
          <li v-for="item in playground" :key="item.icon"><span><Icon :name="item.icon" :size="17" /></span>{{ item.text }}</li>
        </ul>
        <a class="btn primary" :href="withBase('/start/playground')">对话测试<Icon name="arrow-right" :size="16" /></a>
      </div>
      <div class="pg-card reveal" @pointermove="spotlight">
        <CardImage name="playground" alt="对话测试页：依次以老周、橘子、小满的身份发言，小然在左侧回复，右侧列出每个回合" />
      </div>
    </section>

    <section class="section">
      <h2 class="reveal">网页面板</h2>
      <div class="reveal"><PanelShowcase /></div>
    </section>

    <section class="section">
      <h2 class="reveal">快速开始</h2>
      <StepRail />
      <div class="reveal picker"><DeployPicker /></div>
    </section>

    <section class="section">
      <h2 class="reveal">文档</h2>
      <div class="map">
        <div v-for="(group, index) in map" :key="group.title" class="map-col reveal" :style="{ '--i': index }" @pointermove="spotlight">
          <h3><span><Icon :name="group.icon" :size="17" /></span>{{ group.title }}</h3>
          <a v-for="[label, link] in group.links" :key="link" :href="withBase(link)">{{ label }}<Icon name="arrow-right" :size="14" /></a>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home { position: relative; overflow: hidden; margin-top: calc(-1 * var(--vp-nav-height)); padding: var(--vp-nav-height) 0 32px; }
.aurora { position: absolute; inset: -120px 0 auto; height: 900px; pointer-events: none; z-index: 0; filter: blur(70px); opacity: var(--lb-aurora-opacity); }
.aurora i { position: absolute; border-radius: 50%; mix-blend-mode: var(--lb-aurora-blend); }
.aurora i:nth-child(1) { width: 560px; height: 560px; left: 8%; top: 40px; background: var(--lb-brand); animation: drift-a 22s ease-in-out infinite; }
.aurora i:nth-child(2) { width: 520px; height: 520px; right: 6%; top: 0; background: var(--lb-peach); animation: drift-b 26s ease-in-out infinite; }
.aurora i:nth-child(3) { width: 460px; height: 460px; left: 40%; top: 260px; background: var(--lb-lilac); animation: drift-c 30s ease-in-out infinite; }
.grid-bg {
  position: absolute; inset: 0 0 auto; height: 960px; pointer-events: none; z-index: 0;
  background-image: radial-gradient(circle at 1px 1px, var(--lb-dot) 1px, transparent 0); background-size: 26px 26px;
  mask-image: radial-gradient(ellipse 70% 60% at 50% 30%, #000 30%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse 70% 60% at 50% 30%, #000 30%, transparent 75%);
}
section { position: relative; z-index: 1; }

.hero {
  display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 56px; align-items: center;
  max-width: 1200px; margin: 0 auto; padding: 72px 32px 40px;
}
.hero-copy > * { animation: rise 0.8s var(--lb-ease) both; }
.hero-copy > :nth-child(2) { animation-delay: 0.08s; }
.hero-copy > :nth-child(3) { animation-delay: 0.16s; }
.hero-copy > :nth-child(4) { animation-delay: 0.24s; }
.hero-copy > :nth-child(5) { animation-delay: 0.32s; }
.hero-demo { animation: rise 1s var(--lb-ease) 0.2s both; }
.hero-mark { width: 76px; height: 84px; margin-bottom: 18px; filter: drop-shadow(0 14px 24px rgb(226 128 159 / 0.45)); }
h1 { margin: 0; display: flex; flex-direction: column; gap: 10px; }
.name {
  font-size: clamp(56px, 8vw, 92px); line-height: 1; font-weight: 800; letter-spacing: -0.045em;
  background: linear-gradient(120deg, var(--lb-primary) 5%, var(--lb-brand) 45%, var(--lb-peach) 90%);
  background-size: 200% 100%; -webkit-background-clip: text; background-clip: text; color: transparent;
  animation: sheen 8s ease-in-out infinite;
}
.tag { font-size: clamp(26px, 3.4vw, 40px); line-height: 1.2; font-weight: 700; letter-spacing: -0.02em; color: var(--vp-c-text-1); }
.typed { margin: 22px 0 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; font-size: clamp(18px, 2vw, 22px); font-weight: 600; color: var(--vp-c-text-2); }
.word {
  display: inline-flex; align-items: center; min-width: 5em; padding: 2px 12px; border-radius: 10px;
  color: var(--lb-primary); background: var(--lb-soft); border: 1px solid color-mix(in srgb, var(--lb-primary) 22%, transparent);
}
.caret { width: 2px; height: 1em; margin-left: 3px; background: currentColor; animation: blink 1s steps(1) infinite; }
.fact { margin: 14px 0 0; font-size: 15px; line-height: 1.7; color: var(--vp-c-text-2); }
.actions { margin-top: 30px; display: flex; flex-wrap: wrap; gap: 12px; }
.btn {
  display: inline-flex; align-items: center; gap: 8px; height: 44px; padding: 0 20px; border-radius: 999px; font-size: 15px; font-weight: 600;
  color: var(--vp-c-text-1); background: var(--vp-c-bg); border: 1px solid var(--vp-c-divider); text-decoration: none;
  transition: transform 0.25s var(--lb-ease), box-shadow 0.25s, border-color 0.25s, background-color 0.25s;
}
.btn:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--lb-primary) 40%, var(--vp-c-divider)); }
.btn.primary {
  color: var(--lb-on-primary); border-color: transparent;
  background: linear-gradient(135deg, var(--lb-primary), color-mix(in srgb, var(--lb-primary) 70%, var(--lb-peach)));
  box-shadow: 0 12px 28px -12px color-mix(in srgb, var(--lb-primary) 80%, transparent);
}
.btn.primary:hover { box-shadow: 0 18px 36px -14px color-mix(in srgb, var(--lb-primary) 90%, transparent); }
.btn.primary .lb-icon { transition: transform 0.25s; }
.btn.primary:hover .lb-icon { transform: translateX(3px); }
.btn.ghost { background: transparent; }

.section { max-width: 1200px; margin: 0 auto; padding: 72px 32px 0; }
.section h2 { margin: 0 0 24px; font-size: clamp(26px, 3vw, 34px); font-weight: 800; letter-spacing: -0.025em; color: var(--vp-c-text-1); border: 0; padding: 0; }

.caps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.cap, .pg-card, .map-col { position: relative; border-radius: 18px; isolation: isolate; }
.cap { display: block; transition: transform 0.35s var(--lb-ease), box-shadow 0.35s; }
.cap::after, .pg-card::after, .map-col::after {
  content: ''; position: absolute; inset: -1px; border-radius: inherit; pointer-events: none; opacity: 0; transition: opacity 0.3s;
  padding: 1.5px; -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude;
  background: radial-gradient(260px circle at var(--mx, 50%) var(--my, 50%), var(--lb-primary), transparent 70%);
}
.cap:hover, .pg-card:hover, .map-col:hover { box-shadow: 0 30px 60px -36px rgb(120 40 70 / 0.5); }
.cap:hover::after, .pg-card:hover::after, .map-col:hover::after { opacity: 1; }
.cap:hover { transform: translateY(-4px); }
.cap :deep(img) { border-radius: 18px; }

.playground { display: grid; grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.4fr); gap: 48px; align-items: center; }
.pg-copy ul { list-style: none; margin: 0 0 28px; padding: 0; display: grid; gap: 14px; }
.pg-copy li { display: flex; align-items: center; gap: 12px; font-size: 15px; line-height: 1.6; color: var(--vp-c-text-2); }
.pg-copy li span { flex: none; width: 34px; height: 34px; border-radius: 11px; display: grid; place-items: center; color: var(--lb-primary); background: var(--lb-soft); }
.pg-card :deep(img) { border-radius: 18px; }

.picker { margin-top: 28px; }

.map { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.map-col { padding: 20px; border: 1px solid var(--vp-c-divider); background: color-mix(in srgb, var(--vp-c-bg) 85%, transparent); display: flex; flex-direction: column; gap: 4px; }
.map-col h3 { display: flex; align-items: center; gap: 10px; margin: 0 0 10px; font-size: 16px; font-weight: 700; color: var(--vp-c-text-1); }
.map-col h3 span { width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; color: var(--lb-primary); background: var(--lb-soft); }
.map-col a {
  display: flex; align-items: center; justify-content: space-between; padding: 7px 10px; margin: 0 -10px; border-radius: 9px;
  font-size: 14px; color: var(--vp-c-text-2); text-decoration: none; transition: color 0.2s, background-color 0.2s;
}
.map-col a .lb-icon { opacity: 0; transform: translateX(-4px); transition: opacity 0.2s, transform 0.2s; }
.map-col a:hover { color: var(--lb-primary); background: var(--vp-c-bg-soft); }
.map-col a:hover .lb-icon { opacity: 1; transform: none; }

@keyframes rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
@keyframes sheen { 0%, 100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@keyframes blink { 50% { opacity: 0; } }
@keyframes drift-a { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(120px, 60px) scale(1.12); } }
@keyframes drift-b { 0%, 100% { transform: translate(0, 0) scale(1.05); } 50% { transform: translate(-140px, 90px) scale(0.92); } }
@keyframes drift-c { 0%, 100% { transform: translate(0, 0) scale(0.95); } 50% { transform: translate(60px, -80px) scale(1.1); } }

@media (max-width: 1024px) {
  .hero { grid-template-columns: 1fr; gap: 40px; padding-top: 48px; }
  .playground { grid-template-columns: 1fr; gap: 28px; }
  .caps { grid-template-columns: repeat(2, 1fr); }
  .map { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .hero { padding: 32px 16px 24px; }
  .section { padding: 56px 16px 0; }
  .caps, .map { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .aurora i, .name, .caret, .hero-copy > *, .hero-demo { animation: none; }
}
</style>
