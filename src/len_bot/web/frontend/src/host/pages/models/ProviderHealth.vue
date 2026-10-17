<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { api } from '../../../api.js'
import { useResource } from '../../../composables/useResource.js'
import { formatAgo } from '../../time.js'
import Panel from '../../ui/Panel.vue'
import ResourceState from '../../ui/ResourceState.vue'
import StatusBadge from '../../ui/StatusBadge.vue'

const props = defineProps({ roleTitles: { type: Object, default: () => ({}) } })
const health = useResource(() => api('/api/host/model-providers/health'))
// Breaker state changes on its own as cooldowns run out, so keep it fresh while the tab is open.
let timer = 0
onMounted(() => { timer = setInterval(() => { if (document.visibilityState === 'visible' && !health.loading.value) health.reload() }, 5000) })
onBeforeUnmount(() => clearInterval(timer))

const states = {
  closed: { text: '正常', tone: 'success' },
  half_open: { text: '试探中', tone: 'warning' },
  open: { text: '冷却中', tone: 'error' },
}
const roles = computed(() => Object.entries(health.data.value?.roles || {}).map(([name, value]) => ({ name, ...value })))
const rate = item => {
  const total = item.successes + item.failures
  return total ? `${Math.round(item.successes / total * 100)}%` : '—'
}
const served = (role, item) => role.last_served && role.last_served.provider === item.provider && role.last_served.model === item.model
</script>

<template>
  <Panel title="备用模型与熔断" :description="health.data.value ? `连续失败 ${health.data.value.failure_threshold} 次暂停使用 ${health.data.value.cooldown_seconds} 秒，之后试探一次` : ''">
    <template #actions><v-btn size="small" variant="text" :loading="health.loading.value" @click="health.reload()">刷新</v-btn></template>
    <ResourceState :resource="health" error-title="读取模型可用性失败" :empty="!roles.length" empty-text="还没有用途配置备用模型，或者配置了但还没被调用过。" compact>
      <template #empty>
        <div class="empty">
          <p class="small">在 <code>lenbot.config.json</code> 的 <code>models.roles.&lt;用途&gt;.fallbacks</code> 里按顺序写备用的服务商和模型（协议要和主模型一样），主模型连续出错时会自动换下一个。不写就和以前一样，只用主模型。</p>
        </div>
      </template>
      <section v-for="role in roles" :key="role.name" class="role">
        <header class="role-head">
          <strong>{{ props.roleTitles[role.name] || role.name }}</strong>
          <span v-if="role.last_served" class="muted small">最近由 {{ role.last_served.provider }} · {{ role.last_served.model }} 回答，{{ formatAgo(role.last_served.at) }}
            <template v-if="role.last_served.failed_before?.length">（前面 {{ role.last_served.failed_before.length }} 个失败了）</template></span>
        </header>
        <table class="chain">
          <colgroup><col style="width:9%"><col style="width:30%"><col style="width:16%"><col style="width:14%"><col></colgroup>
          <thead><tr><th>顺序</th><th>服务商 · 模型</th><th>状态</th><th>成功率</th><th>最近错误</th></tr></thead>
          <tbody>
            <tr v-for="item in role.candidates" :key="item.priority" :class="{ served: served(role, item) }">
              <td>{{ item.priority === 0 ? '主' : `备 ${item.priority}` }}</td>
              <td><span class="mono">{{ item.provider }}</span> · {{ item.model }}<span v-if="served(role, item)" class="tag">正在用</span></td>
              <td><StatusBadge dot :text="states[item.state]?.text || item.state" :tone="states[item.state]?.tone || 'neutral'" />
                <div v-if="item.state === 'open' && item.reopens_in_seconds !== null" class="muted small">{{ Math.ceil(item.reopens_in_seconds) }} 秒后试探</div></td>
              <td class="num">{{ rate(item) }}<div class="muted small">{{ item.successes }} 成 / {{ item.failures }} 败</div></td>
              <td class="err"><template v-if="item.last_error"><span :title="item.last_error">{{ item.last_error }}</span>
                <div class="muted small">{{ formatAgo(item.last_error_at) }}</div></template><span v-else class="muted">—</span></td>
            </tr>
          </tbody>
        </table>
      </section>
    </ResourceState>
  </Panel>
</template>

<style scoped>
.empty{display:grid;gap:var(--sp-2);padding:var(--sp-3) 0}
.empty p{margin:0}
.role{display:grid;gap:var(--sp-2);padding:var(--sp-3) 0}
.role + .role{border-top:1px solid var(--line)}
.role-head{display:flex;flex-wrap:wrap;gap:var(--sp-3);align-items:baseline}
.chain{width:100%;table-layout:fixed;border-collapse:collapse;font-size:var(--fs-sm)}
.chain th{text-align:left;font-weight:500;color:var(--muted);padding:6px 8px;border-bottom:1px solid var(--line)}
.chain td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
.chain tr.served td{background:var(--selected)}
.num{font-variant-numeric:tabular-nums}
.err{max-width:280px}
.err span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mono{font-family:var(--font-mono, ui-monospace, monospace)}
.tag{margin-left:6px;font-size:11px;padding:0 6px;border-radius:99px;background:var(--primary-bg);color:var(--primary)}
@media(max-width:700px){.chain th:nth-child(5),.chain td:nth-child(5){display:none}}
</style>
