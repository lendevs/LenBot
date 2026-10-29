<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'

const shots = [
  { label: '总览', file: 'home', path: '#/overview', alt: '面板总览，显示 QQ 连接状态、今天的消息量和群列表' },
  { label: '群聊现场', file: 'scenes', path: '#/groups/onebot:group:80001/live', alt: '群聊页的现场页签：左侧选择群，右侧是群消息和 Bot 的回合' },
  { label: '角色', file: 'persona', path: '#/personas?persona=companion&tab=effect', alt: '角色 → 效果 → 对话试聊：左侧是在所选群环境中的试聊对话，右侧是试聊的回合列表' },
  { label: '记忆', file: 'memory', path: '#/groups/onebot:group:80001/memory', alt: '群聊 → 记忆 → 浏览：左侧是本群记忆的目录，右侧是打开的记忆文件' },
  { label: '资料', file: 'reference', path: '#/groups/onebot:group:80001/reference', alt: '群聊 → 资料：本群的三份资料文件，每份显示大小、字数、段数和已索引状态' },
  { label: '插件', file: 'plugins', path: '#/plugins?view=discover', alt: '插件 → 发现：可安装的插件目录' },
  { label: '用量', file: 'usage', path: '#/models?tab=usage', alt: '模型 → 用量与上限：今天的 token 合计，按模型、按群和用途的调用次数与 token' },
]
const DURATION = 6000
const active = ref(0)
const paused = ref(false)
const auto = ref(false)
let timer = 0
let observer: IntersectionObserver | undefined
let visible = false

function schedule() {
  clearTimeout(timer)
  if (!auto.value || paused.value || !visible) return
  timer = window.setTimeout(() => {
    active.value = (active.value + 1) % shots.length
    schedule()
  }, DURATION)
}
function pick(index: number) {
  active.value = index
  schedule()
}
function hold(value: boolean) {
  paused.value = value
  schedule()
}

const root = ref<HTMLElement>()
onMounted(() => {
  auto.value = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  observer = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting
    schedule()
  }, { threshold: 0.3 })
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => {
  clearTimeout(timer)
  observer?.disconnect()
})
</script>

<template>
  <div ref="root" class="showcase" @mouseenter="hold(true)" @mouseleave="hold(false)">
    <div class="chrome">
      <span class="lights"><i /><i /><i /></span>
      <span class="address">127.0.0.1:8088/{{ shots[active].path }}</span>
    </div>
    <div class="tabs" role="tablist" aria-label="面板页面">
      <button
        v-for="(shot, index) in shots"
        :key="shot.file"
        role="tab"
        :aria-selected="index === active"
        :class="{ on: index === active }"
        @click="pick(index)"
      >
        {{ shot.label }}
        <span
          v-if="index === active && auto"
          :key="`${active}-${paused}`"
          class="timer"
          :class="{ hold: paused }"
          :style="{ animationDuration: `${DURATION}ms` }"
        />
      </button>
    </div>
    <div class="viewport">
      <img
        v-for="(shot, index) in shots"
        :key="shot.file"
        :src="withBase(`/screenshots/${shot.file}.png`)"
        :alt="shot.alt"
        :class="{ on: index === active }"
        :aria-hidden="index !== active"
        loading="lazy"
        decoding="async"
      />
    </div>
  </div>
</template>

<style scoped>
.showcase {
  border-radius: 20px; overflow: hidden; background: var(--vp-c-bg); border: 1px solid var(--vp-c-divider);
  box-shadow: 0 50px 100px -50px rgb(120 40 70 / 0.5), 0 0 0 1px rgb(255 255 255 / 0.03) inset;
}
.chrome { display: flex; align-items: center; gap: 14px; padding: 10px 14px; background: var(--vp-c-bg-alt); border-bottom: 1px solid var(--vp-c-divider); }
.lights { display: flex; gap: 6px; }
.lights i { width: 11px; height: 11px; border-radius: 50%; background: #ff5f57; }
.lights i:nth-child(2) { background: #febc2e; }
.lights i:nth-child(3) { background: #28c840; }
.address {
  flex: 1; max-width: 420px; margin: 0 auto; padding: 4px 12px; border-radius: 8px; text-align: center;
  font: 12px/1.6 var(--vp-font-family-mono); color: var(--vp-c-text-2); background: var(--vp-c-bg);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tabs { display: flex; gap: 2px; padding: 6px 8px 0; overflow-x: auto; scrollbar-width: none; background: var(--vp-c-bg-alt); border-bottom: 1px solid var(--vp-c-divider); }
.tabs::-webkit-scrollbar { display: none; }
.tabs button {
  position: relative; flex: none; padding: 8px 14px 10px; font-size: 13px; font-weight: 500; color: var(--vp-c-text-2);
  border-radius: 10px 10px 0 0; transition: color 0.2s, background-color 0.2s;
}
.tabs button:hover { color: var(--vp-c-text-1); }
.tabs button.on { color: var(--lb-primary); background: var(--vp-c-bg); font-weight: 600; }
.timer {
  position: absolute; left: 12px; right: 12px; bottom: 0; height: 2px; border-radius: 1px; transform-origin: left;
  background: linear-gradient(90deg, var(--lb-primary), var(--lb-peach)); animation: fill linear both;
}
.timer.hold { animation: none; transform: scaleX(1); opacity: 0.5; }
.viewport { position: relative; aspect-ratio: 16 / 10; background: var(--vp-c-bg); }
.viewport img {
  position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: top left;
  opacity: 0; transform: scale(1.015); transition: opacity 0.6s var(--lb-ease), transform 0.9s var(--lb-ease);
  border: 0; border-radius: 0;
}
.viewport img.on { opacity: 1; transform: none; }
@keyframes fill { from { transform: scaleX(0); } to { transform: scaleX(1); } }
</style>
