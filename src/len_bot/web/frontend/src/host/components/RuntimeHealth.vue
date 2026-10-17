<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { mdiArrowRight } from '@mdi/js'
import { api } from '../../api.js'
import { formatAgo } from '../time.js'
import Panel from '../ui/Panel.vue'
import Fold from '../ui/Fold.vue'
import StatusBadge from '../ui/StatusBadge.vue'

// Two read-only probes; each one fails on its own so an older backend without one still shows the other.
const loop = ref(null), models = ref(null), loopError = ref(''), modelsError = ref('')
async function read() {
  const [a, b] = await Promise.allSettled([api('/api/host/event-loop'), api('/api/host/model-providers/health')])
  if (a.status === 'fulfilled') { loop.value = a.value; loopError.value = '' } else loopError.value = a.reason?.message || '读取失败'
  if (b.status === 'fulfilled') { models.value = b.value; modelsError.value = '' } else modelsError.value = b.reason?.message || '读取失败'
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
const candidates = computed(() => Object.values(models.value?.roles || {}).flatMap(role => role.candidates))
const cooling = computed(() => candidates.value.filter(item => item.state !== 'closed'))
const modelTone = computed(() => {
  if (!models.value) return { text: modelsError.value ? '读取失败' : '读取中', tone: modelsError.value ? 'error' : 'neutral' }
  if (!candidates.value.length) return { text: '未配置备用', tone: 'neutral' }
  return cooling.value.length ? { text: `${cooling.value.length} 个在冷却`, tone: 'warning' } : { text: '全部可用', tone: 'success' }
})
const stallText = item => `${item.task || '未知任务'} 卡住 ${item.lag_ms} 毫秒`
</script>

<template>
  <Panel title="运行健康" flush>
    <ul class="plain-list rows">
      <li class="row">
        <div class="row-text">
          <span class="line"><strong>主循环</strong><StatusBadge dot :text="loopTone.text" :tone="loopTone.tone" /></span>
          <span v-if="loop" class="muted small">卡顿 {{ loop.stalls }} 次 · 最长 {{ loop.max_lag_ms }} 毫秒 · 每 {{ loop.interval_ms }} 毫秒检查一次</span>
          <Fold v-if="recentStall" :label="`最近一次：${stallText(recentStall)}，${formatAgo(recentStall.at)}`" code>{{ recentStall.stack || '卡顿太短，没有抓到现场' }}</Fold>
        </div>
      </li>
      <li class="row">
        <div class="row-text">
          <span class="line"><strong>备用模型</strong><StatusBadge dot :text="modelTone.text" :tone="modelTone.tone" /></span>
          <span v-if="cooling.length" class="muted small">{{ cooling.map(item => `${item.provider} · ${item.model}`).join('、') }}</span>
        </div>
        <v-btn size="small" variant="text" :append-icon="mdiArrowRight" :to="{ name: 'host-models', query: { tab: 'health' } }">详情</v-btn>
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
