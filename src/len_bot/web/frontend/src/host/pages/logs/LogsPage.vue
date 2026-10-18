<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { mdiMagnify, mdiContentCopy, mdiDownload, mdiPause, mdiPlay } from '@mdi/js'
import { useRoute, useRouter } from 'vue-router'
import { api, sceneName } from '../../../api.js'
import { useResource } from '../../../composables/useResource.js'
import { host } from '../../store.js'
import { useCurrentScene } from '../../../composables/useCurrentScene.js'
import { useHostEvents } from '../../events.js'
import { formatTime } from '../../time.js'
import HostPage from '../../ui/HostPage.vue'
import PageTabs from '../../ui/PageTabs.vue'
import Panel from '../../ui/Panel.vue'
import ResourceState from '../../ui/ResourceState.vue'
import MasterDetail from '../../ui/MasterDetail.vue'
import ObjectList from '../../ui/ObjectList.vue'
import ObjectRow from '../../ui/ObjectRow.vue'
import StatusBadge from '../../ui/StatusBadge.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import LiveStatus from '../../ui/LiveStatus.vue'
import TurnDetail from '../../components/TurnDetail.vue'
import DevOnly from '../../ui/DevOnly.vue'

const route = useRoute(), router = useRouter()
const tab = computed(() => route.query.tab === 'system' ? 'system' : 'turns')
const { scene } = useCurrentScene()
const selected = computed(() => typeof route.query.turn === 'string' ? route.query.turn : '')
const base = () => `/api/host/scenes/${encodeURIComponent(scene.value)}`

const sceneState = useResource(() => api(base()), { immediate: false })
const detail = useResource(() => api(`${base()}/turns/${encodeURIComponent(selected.value)}`), { immediate: false })
const events = useHostEvents(async () => {
  if (tab.value !== 'turns' || !scene.value) return
  await sceneState.reload()
  if (selected.value) await detail.reload()
})
watch(scene, value => { if (value) sceneState.reload() }, { immediate: true })
watch([scene, selected], ([value, turn]) => { detail.data.value = null; if (value && turn) detail.reload() }, { immediate: true })
const turns = computed(() => [...(sceneState.data.value?.turns || [])].sort((a, b) => b.started - a.started))
const timezone = computed(() => sceneState.data.value?.timezone || host.state?.timezone)
const open = turn => router.replace({ query: { ...route.query, turn: turn ? turn.id : undefined } })

const level = ref('all')
const onlyScene = ref(false)
const traceTurn = computed(() => typeof route.query.trace === 'string' ? route.query.trace : '')
const plugin = ref(''), task = ref('')
function logQuery() {
  const query = new URLSearchParams({ limit: '300' })
  if (level.value !== 'all') query.set('level', level.value)
  if (onlyScene.value && scene.value) query.set('scene', scene.value)
  if (traceTurn.value) query.set('turn_id', traceTurn.value)
  if (plugin.value.trim()) query.set('plugin', plugin.value.trim())
  if (task.value.trim()) query.set('task_id', task.value.trim())
  return query.toString()
}
const system = useResource(() => Promise.all([api(`/api/host/logs?${logQuery()}`), api('/api/host/log-files')]), { immediate: false })
watch([tab, level, onlyScene, traceTurn], ([value]) => { if (value === 'system') system.reload() }, { immediate: true })
const trace = turn => router.replace({ query: { ...route.query, tab: 'system', trace: turn || undefined } })
const logLabels = {
  runtime: '运行状态', receipt: '收到消息', turn_start: '开始一轮', turn: '一轮结束', tool_call: '调用工具',
  tool_failed: '工具出错', model_call: '模型调用', message_sent: '发出消息', platform_error: '平台连接出错',
  platform_event: '平台事件', schedule: '定时安排', notice: '提醒', limit_notice: '额度提醒', retention: '数据清理',
  plugin_error: '插件出错', mcp_error: 'MCP 出错', task_created: '登记任务', task_started: '任务开始',
  task_input: '任务补充', task_finished: '任务结束', task_service_failed: '任务执行器出错',
  event_loop_stall: '主循环卡顿', release_check: '检查新版本',
}
const idFields = [['turn_id', '轮'], ['tool', '工具'], ['plugin', '插件'], ['task_id', '任务'], ['message_seq', '消息'], ['job', '后台']]
const logItems = computed(() => system.data.value?.[0].items || [])
const errorText = error => error.type ? `${error.type}: ${error.message}` : error.message
const seconds = ts => Date.parse(ts) / 1000

// Client-side narrowing over what the server already returned: free text plus one event kind.
const search = ref(''), kind = ref('')
const eventKey = item => item.event || '_other'
const haystack = item => [item.event, logLabels[item.event], item.message, item.source, item.scene, item.plugin, item.tool, item.task_id,
  item.turn_id, item.error?.type, item.error?.message].filter(Boolean).join(' ').toLowerCase()
const kinds = computed(() => {
  const counts = new Map()
  for (const item of logItems.value) { const key = eventKey(item); counts.set(key, (counts.get(key) || 0) + 1) }
  return [...counts].sort((a, b) => b[1] - a[1])
})
const shown = computed(() => {
  const words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return logItems.value.filter(item => (!kind.value || eventKey(item) === kind.value)
    && (!words.length || words.every(word => haystack(item).includes(word))))
})
watch(logItems, items => { if (kind.value && !items.some(item => eventKey(item) === kind.value)) kind.value = '' })
const severity = item => item.error || item.level === 'ERROR' || item.level === 'CRITICAL' ? 'error' : item.level === 'WARNING' ? 'warning' : ''

// Live follow: re-read every few seconds while the system tab is open and the page is visible.
const follow = ref(false)
let timer = 0
function tick() { if (tab.value === 'system' && document.visibilityState === 'visible' && !system.loading.value) system.reload() }
watch([follow, tab], ([on, value]) => {
  clearInterval(timer)
  timer = on && value === 'system' ? setInterval(tick, 4000) : 0
})
onBeforeUnmount(() => clearInterval(timer))

async function copyRow(item) {
  try { await navigator.clipboard.writeText(JSON.stringify(item, null, 2)); host.toast = '已复制这条记录' }
  catch { host.toast = '浏览器不允许复制' }
}
function exportShown() {
  const blob = new Blob([shown.value.map(item => JSON.stringify(item)).join('\n') + '\n'], { type: 'application/x-ndjson' })
  const link = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `lenbot-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.jsonl` })
  link.click()
  setTimeout(() => URL.revokeObjectURL(link.href), 1000)
}
</script>

<template>
  <HostPage title="日志" :wide="tab === 'turns'">
    <PageTabs :tabs="[['turns', '回复记录'], ['system', '系统日志']]" :model-value="tab" label="日志" />

    <MasterDetail v-if="tab === 'turns'" :selected="Boolean(selected)" :empty="!turns.length" list-width="300px" @back="open(null)">
      <template #list>
        <Panel title="最近 20 次回复" flush>
          <template #actions><LiveStatus :status="events.status.value" @reconnect="events.reconnect" /></template>
          <div class="list">
            <ResourceState :resource="sceneState" error-title="读取回复记录失败" :empty="!turns.length" empty-text="还没有回复记录" compact>
              <ObjectList>
                <ObjectRow v-for="turn in turns" :key="turn.id" :title="formatTime(turn.started, timezone)" clickable
                  :active="selected === turn.id" @click="open(turn)">
                  <template #meta><StatusBadge dot kind="turn" :value="turn.status" /></template>
                </ObjectRow>
              </ObjectList>
            </ResourceState>
          </div>
        </Panel>
      </template>
      <template #placeholder>从左边选一次回复，看看 Bot 当时怎么想的。</template>
      <Panel title="经过">
        <template #actions>
          <v-btn size="small" variant="text" @click="trace(selected)">这一轮的运行日志</v-btn>
          <DevOnly><v-btn size="small" variant="text" :href="`${base()}/turns/${encodeURIComponent(selected)}/export`">下载诊断包</v-btn></DevOnly>
        </template>
        <ResourceState :resource="detail" error-title="读取这次回复失败" v-slot="{ data }">
          <TurnDetail :detail="data" :timezone="timezone" />
        </ResourceState>
      </Panel>
    </MasterDetail>

    <template v-else>
      <Panel title="运行日志" :description="traceTurn ? `只看一轮：${traceTurn}` : ''">
        <template #actions>
          <v-btn-toggle v-model="level" mandatory density="compact">
            <v-btn value="all">全部</v-btn><v-btn value="WARNING">警告以上</v-btn><v-btn value="ERROR">只看错误</v-btn>
          </v-btn-toggle>
          <v-btn v-if="traceTurn" variant="text" size="small" @click="trace(null)">取消只看这一轮</v-btn>
          <v-btn variant="text" size="small" :prepend-icon="follow ? mdiPause : mdiPlay" :color="follow ? 'primary' : undefined"
            :aria-pressed="follow" @click="follow = !follow">{{ follow ? '暂停跟随' : '实时跟随' }}</v-btn>
          <v-btn variant="text" size="small" :loading="system.loading.value && !follow" @click="system.reload()">刷新</v-btn>
        </template>
        <div class="filters">
          <v-switch v-model="onlyScene" density="compact" hide-details :label="scene ? `只看${sceneName(scene)}` : '只看当前群'" />
          <v-text-field v-model="plugin" density="compact" hide-details label="插件名" @keyup.enter="system.reload()" />
          <v-text-field v-model="task" density="compact" hide-details label="任务编号" @keyup.enter="system.reload()" />
        </div>
        <div class="search-row">
          <v-text-field :model-value="search" @update:model-value="search = $event ?? ''" density="compact" hide-details clearable :prepend-inner-icon="mdiMagnify"
            label="在结果里搜索：事件、消息、错误、编号…" />
          <v-btn variant="text" size="small" :prepend-icon="mdiDownload" :disabled="!shown.length" @click="exportShown">导出 {{ shown.length }} 条</v-btn>
        </div>
        <div v-if="kinds.length > 1" class="kinds" role="group" aria-label="按事件筛选">
          <v-chip size="small" :variant="kind ? 'outlined' : 'flat'" :color="kind ? undefined : 'primary'" @click="kind = ''">全部 {{ logItems.length }}</v-chip>
          <v-chip v-for="[key, count] in kinds" :key="key" size="small" :variant="kind === key ? 'flat' : 'outlined'"
            :color="kind === key ? 'primary' : undefined" @click="kind = kind === key ? '' : key">{{ key === '_other' ? '其他' : logLabels[key] || key }} {{ count }}</v-chip>
        </div>
        <ResourceState :resource="system" error-title="读取运行日志失败" :empty="!shown.length" empty-text="没有符合条件的记录" compact>
          <ObjectList divided>
            <li v-for="(item, index) in shown" :key="index" class="log-row" :class="severity(item)">
              <div class="inline"><v-btn class="copy" :icon="mdiContentCopy" size="x-small" variant="text" aria-label="复制这条记录" @click="copyRow(item)" /><strong>{{ logLabels[item.event] || item.event || item.message }}</strong>
                <span class="muted small">{{ formatTime(seconds(item.ts), host.state?.timezone) }} · {{ item.source }}<template v-if="item.scene"> · {{ sceneName(item.scene) }}</template></span></div>
              <div class="ids small muted">
                <template v-for="[key, label] in idFields" :key="key">
                  <a v-if="key === 'turn_id' && item[key] && item[key] !== traceTurn" href="#" @click.prevent="trace(item[key])">{{ label }} {{ item[key].slice(0, 8) }}</a>
                  <span v-else-if="item[key] !== undefined">{{ label }} {{ key === 'turn_id' ? item[key].slice(0, 8) : item[key] }}</span>
                </template>
              </div>
              <ErrorNote v-if="item.error" title="错误" :error="errorText(item.error)" />
              <DevOnly label="原始记录" :json="item" />
            </li>
          </ObjectList>
        </ResourceState>
      </Panel>
      <Panel v-if="system.data.value" title="日志文件">
        <ObjectList v-if="system.data.value[1].items.length" divided>
          <ObjectRow v-for="file in system.data.value[1].items" :key="file.name" :title="file.name" :subtitle="`${Math.ceil(file.bytes / 1024)} KB`">
            <template #actions><v-btn size="small" variant="text" :href="`/api/host/log-files/${encodeURIComponent(file.name)}`">下载</v-btn></template>
          </ObjectRow>
        </ObjectList>
      </Panel>
    </template>
  </HostPage>
</template>

<style scoped>
.list{padding:0 var(--sp-2) var(--sp-2)}
.log-row{padding:var(--sp-3) 0 var(--sp-3) var(--sp-3);display:grid;gap:var(--sp-2);border-left:3px solid transparent;position:relative}
.log-row.error{border-left-color:var(--error);background:linear-gradient(90deg,var(--error-bg),transparent 40%)}
.log-row.warning{border-left-color:var(--warning)}
.log-row .copy{position:absolute;right:0;top:var(--sp-2);opacity:0;transition:opacity .15s}
.log-row:hover .copy,.log-row .copy:focus-visible{opacity:1}
.search-row{display:flex;gap:var(--sp-3);align-items:center;margin-bottom:var(--sp-3)}
.kinds{display:flex;flex-wrap:wrap;gap:var(--sp-2);margin-bottom:var(--sp-3)}
.filters{display:grid;grid-template-columns:auto 1fr 1fr;gap:var(--sp-3);align-items:center;margin-bottom:var(--sp-3)}
@media(max-width:700px){.filters{grid-template-columns:1fr 1fr}.filters > :first-child{grid-column:1/-1}.search-row{flex-wrap:wrap}}
.ids{display:flex;flex-wrap:wrap;gap:var(--sp-3)}
</style>
