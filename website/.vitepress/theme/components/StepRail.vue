<script setup lang="ts">
import { withBase } from 'vitepress'
import Icon from './Icon.vue'

const steps = [
  { icon: 'package', title: '部署', text: 'Docker、部署包或源码', link: '/start/quick-start' },
  { icon: 'settings', title: '首次配置', text: '五步向导', link: '/start/first-setup' },
  { icon: 'users', title: '对话测试', text: '模拟一个群', link: '/start/playground' },
  { icon: 'plug', title: '接入群聊', text: '发送到 QQ', link: '/start/playground#接入群聊' },
]
</script>

<template>
  <ol class="step-rail reveal">
    <li v-for="(step, index) in steps" :key="step.title" :style="{ '--i': index }">
      <a :href="withBase(step.link)">
        <span class="dot"><Icon :name="step.icon" :size="20" /></span>
        <span class="no">0{{ index + 1 }}</span>
        <strong>{{ step.title }}</strong>
        <span class="text">{{ step.text }}</span>
      </a>
    </li>
  </ol>
</template>

<style scoped>
.step-rail { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; grid-template-columns: repeat(4, 1fr); position: relative; }
.step-rail::before, .step-rail::after {
  content: ''; position: absolute; left: 12.5%; right: 12.5%; top: 31px; height: 2px; border-radius: 1px;
  background: var(--vp-c-divider);
}
.step-rail::after {
  background: linear-gradient(90deg, var(--lb-primary), var(--lb-brand), var(--lb-peach));
  transform: scaleX(0); transform-origin: left; transition: transform 1.6s var(--lb-ease) 0.2s;
}
.step-rail.is-visible::after { transform: scaleX(1); }
.step-rail li { margin: 0; position: relative; z-index: 1; }
.step-rail a {
  display: flex; flex-direction: column; align-items: center; text-align: center; gap: 4px; padding: 8px 6px 10px;
  border-radius: 16px; color: inherit; text-decoration: none; transition: background-color 0.25s;
}
.step-rail a:hover { background: var(--vp-c-bg-soft); }
.dot {
  width: 48px; height: 48px; border-radius: 16px; display: grid; place-items: center; margin-bottom: 8px;
  background: var(--vp-c-bg); color: var(--lb-primary); border: 1px solid var(--vp-c-divider);
  box-shadow: 0 6px 18px -8px rgb(180 71 106 / 0.35);
  opacity: 0; transform: translateY(10px) scale(0.9);
  transition: opacity 0.5s var(--lb-ease), transform 0.5s var(--lb-ease), border-color 0.3s;
  transition-delay: calc(0.25s + var(--i) * 0.4s);
}
.step-rail.is-visible .dot { opacity: 1; transform: none; border-color: color-mix(in srgb, var(--lb-primary) 45%, transparent); }
.step-rail a:hover .dot { transform: translateY(-3px); }
.no { font: 600 11px/1 var(--vp-font-family-mono); color: var(--vp-c-text-3); letter-spacing: 0.08em; }
strong { font-size: 15px; color: var(--vp-c-text-1); }
.text { font-size: 13px; color: var(--vp-c-text-2); }
@media (max-width: 640px) {
  .step-rail { grid-template-columns: 1fr 1fr; row-gap: 8px; }
  .step-rail::before, .step-rail::after { display: none; }
}
</style>
