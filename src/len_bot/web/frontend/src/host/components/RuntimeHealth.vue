<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../../api.js'
import { formatAgo } from '../time.js'
import Panel from '../ui/Panel.vue'
import Fold from '../ui/Fold.vue'
import StatusBadge from '../ui/StatusBadge.vue'

const loop = ref(null), loopError = ref('')
async function read() {
  try { loop.value = await api('/api/host/event-loop'); loopError.value = '' } catch (error) { loopError.value = error?.message || '读取失败' }
}
let timer = 0
onMounted(() => { read(); timer = setInterval(() => { if (document.visibilityState === 'visible') read() }, 10000) })
onBeforeUnmount(() => clearInterval(timer))

const recentStall = computed(() => loop.value?.recent?.[0] || null)
const loopTone = computed(() => {
  if (!loop.value) return { text: loopError.value ? '读取失败' : '读取中', tone: loopError.value ? 'error' : 'neutral' }
  if (!loop.value.running) return { text: '未在监测', tone: 'neutral' }
  if (recentStall.value && Date.now() / 1000 - recentStall.value.at < 600) return { text: '最近卡顿过', tone: 'warning' }
  return { text: '流畅', tone: 'success' }
})
const stallText = item => `${item.task || '未知任务'} 卡住 ${item.lag_ms} 毫秒`
</script>

<template>
  <Panel title="运行健康" flush>
    <ul class="plain-list rows">
      <li class="row">
        <div class="row-text">
          <span class="line"><strong>主循环</strong><StatusBadge dot :text="loopTone.text" :tone="loopTone.tone" /></span>
          <span v-if="loop" class="muted small">卡顿 {{ loop.stalls }} 次<template v-if="loop.pauses"> · 系统休眠 {{ loop.pauses }} 次（不算卡顿）</template> · 最长 {{ loop.max_lag_ms }} 毫秒 · 每 {{ loop.interval_ms }} 毫秒检查一次</span>
          <Fold v-if="recentStall" :label="`最近一次：${stallText(recentStall)}，${formatAgo(recentStall.at)}`" code>{{ recentStall.stack || '卡顿太短，没有抓到现场' }}</Fold>
        </div>
      </li>
    </ul>
  </Panel>
</template>

<style scoped>
.rows{border-top:1px solid var(--line)}
.row{display:flex;align-items:center;gap:var(--sp-3);padding:var(--sp-3) 0;border-bottom:1px solid var(--line);min-width:0}
.row:last-child{border-bottom:0}
.row-text{display:grid;gap:var(--sp-1);flex:1;min-width:0}
.line{display:flex;align-items:center;gap:var(--sp-3)}
</style>
