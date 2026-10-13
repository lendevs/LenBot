<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { mdiArrowLeft, mdiCubeOutline, mdiDotsHorizontal, mdiOpenInNew, mdiShieldAlertOutline, mdiShieldCheckOutline } from '@mdi/js'
import { sceneName, sceneSubtitle } from '../../../api.js'
import { formatAgo, formatTime } from '../../time.js'
import SchemaForm from '../../components/SchemaForm.vue'
import PageTabs from '../../ui/PageTabs.vue'
import StatusBadge from '../../ui/StatusBadge.vue'
import FactList from '../../ui/FactList.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import EmptyState from '../../ui/EmptyState.vue'
import SaveBar from '../../ui/SaveBar.vue'
import SceneAvatar from '../../ui/SceneAvatar.vue'
import DevOnly from '../../ui/DevOnly.vue'
import PluginMark from './PluginMark.vue'
import { candidateChange, enabledIn, factsOf, featureCount, healthNote, isolationOf, manifestOf, permissionsOf, runningOf, scenesUsing, statusIn, versionOf } from './pluginView.js'
import { formProblem } from '../../pluginConfig.js'

const props = defineProps({
  name: { type: String, required: true },
  snapshot: { type: Object, required: true },
  draft: { type: Object, default: null },
  dirty: Boolean,
  busy: Boolean,
  saving: Boolean,
  error: { type: [Object, String], default: null },
  sceneError: { type: [Object, String], default: null },
  switching: { type: String, default: '' },
  health: { type: Object, default: null },
})
const emit = defineEmits(['save', 'discard', 'enable', 'disable', 'scene', 'manage', 'remove', 'update'])
const route = useRoute()

const manifest = computed(() => manifestOf(props.snapshot, props.name))
const running = computed(() => runningOf(props.snapshot, props.name))
const enabled = computed(() => enabledIn(props.snapshot, props.name))
const loaded = computed(() => Boolean(props.snapshot.saved.plugins[props.name]))
const status = computed(() => statusIn(props.snapshot, props.name))
const version = computed(() => versionOf(props.snapshot, props.name))
const used = computed(() => scenesUsing(props.snapshot, props.name))
const scenes = computed(() => Object.keys(props.snapshot.scenes))
const source = computed(() => manifest.value?.source)
const entries = computed(() => props.snapshot.available[props.name] || [])
const configured = computed(() => Object.fromEntries(Object.entries(props.snapshot.saved.plugins[props.name] || {})
  .map(([key, item]) => [key, Boolean(item.configured)])))
const problem = computed(() => manifest.value && props.draft ? formProblem(manifest.value.fields, props.draft) : '')
const permissions = computed(() => permissionsOf(props.snapshot, props.name))
const isolation = computed(() => isolationOf(props.snapshot, props.name))
const unstable = computed(() => healthNote(props.health))
const change = computed(() => candidateChange(props.snapshot, props.name))
const recent = computed(() => (running.value?.errors.length || 0) + (running.value?.model_calls.filter(call => call.error).length || 0))

const tabs = computed(() => [
  { value: 'settings', title: '设置' },
  { value: 'scenes', title: '使用的群', count: used.value.length || undefined },
  { value: 'features', title: '功能', count: featureCount(running.value) || undefined },
  { value: 'activity', title: '运行记录', count: recent.value || undefined },
  { value: 'version', title: '版本' },
])
const tab = computed(() => tabs.value.some(item => item.value === route.query.part) ? route.query.part : 'settings')
const back = computed(() => ({ query: { ...route.query, item: undefined, part: undefined } }))
const every = seconds => seconds % 3600 === 0 ? `每 ${seconds / 3600} 小时` : seconds % 60 === 0 ? `每 ${seconds / 60} 分钟` : `每 ${seconds} 秒`
</script>

<template>
  <div class="plugin-detail">
    <RouterLink :to="back" class="back"><v-icon :icon="mdiArrowLeft" size="16" />全部插件</RouterLink>

    <header class="detail-head">
      <PluginMark :name="name" :size="56" :muted="!enabled" />
      <div class="head-text">
        <div class="head-title">
          <h1>{{ name }}</h1>
          <span v-if="version" class="version">v{{ version }}</span>
          <StatusBadge dot v-bind="status" />
        </div>
        <p v-if="manifest?.description" class="description">{{ manifest.description }}</p>
        <div v-if="manifest" class="head-meta">
          <span v-if="manifest.authors?.length">{{ manifest.authors.join('、') }}</span>
          <span v-if="manifest.license">{{ manifest.license }}</span>
          <a v-if="manifest.repository" :href="manifest.repository" target="_blank" rel="noopener noreferrer">源码仓库<v-icon :icon="mdiOpenInNew" size="13" /></a>
          <a v-if="manifest.homepage" :href="manifest.homepage" target="_blank" rel="noopener noreferrer">使用说明<v-icon :icon="mdiOpenInNew" size="13" /></a>
        </div>
      </div>
      <div class="head-actions">
        <v-btn v-if="enabled" variant="outlined" :disabled="busy" @click="emit('disable')">停用</v-btn>
        <v-tooltip v-else-if="manifest" :text="problem" :disabled="!problem" location="bottom">
          <template #activator="{ props: tip }">
            <span v-bind="tip"><v-btn color="primary" :disabled="busy || Boolean(problem)" :loading="saving" @click="emit('enable')">{{ dirty ? '保存并启用' : '启用' }}</v-btn></span>
          </template>
        </v-tooltip>
        <v-menu location="bottom end">
          <template #activator="{ props: menu }"><v-btn v-bind="menu" :icon="mdiDotsHorizontal" variant="outlined" size="36" aria-label="更多操作" /></template>
          <v-list density="compact" min-width="200">
            <v-list-item v-if="loaded" title="重载" :disabled="busy || dirty" @click="emit('manage', 'reload')" />
            <v-list-item v-if="source?.installed?.kind === 'git'" title="更新／选择版本" :disabled="busy || dirty" @click="emit('update')" />
            <v-divider v-if="manifest?.managed || snapshot.saved.disabled.includes(name)" class="my-1" />
            <v-list-item v-if="manifest?.managed" title="卸载（保留数据）" base-color="error" :disabled="busy" @click="emit('remove', 'source')" />
            <v-list-item v-if="snapshot.saved.disabled.includes(name)" title="删除插件数据" base-color="error" :disabled="busy" @click="emit('remove', 'data')" />
          </v-list>
        </v-menu>
      </div>
    </header>

    <v-alert v-if="source?.candidate" type="info" :title="`候选版本 v${source.candidate.version} 已准备好`">
      {{ source.application === 'host' ? '应用后需要重启' : '应用时重载这个插件' }}<template v-if="change">；生效后{{ change }}</template>
      <template #append>
        <div class="alert-actions">
          <v-btn size="small" variant="text" :disabled="busy" @click="emit('manage', 'cancel')">取消候选</v-btn>
          <v-btn size="small" color="primary" :loading="saving" :disabled="dirty" @click="emit('manage', 'apply')">{{ source.application === 'host' ? '应用并等待重启' : '应用' }}</v-btn>
        </div>
      </template>
    </v-alert>
    <p v-if="unstable" class="health-warn small">最近不太稳定：{{ unstable }}<template v-if="health?.failing?.length">，失败的后台任务：{{ health.failing.join('、') }}</template>。详细原因见运行记录或日志页。</p>
    <ErrorNote v-if="source?.error" title="版本应用失败" :error="source.error" />
    <ErrorNote v-if="running?.error" title="插件没有启动成功" :error="running.error" @retry="emit('manage', 'reload')" />
    <ErrorNote v-for="entry in entries.filter(item => item.error)" :key="entry.directory" title="插件说明文件读不了" :error="entry.error" />
    <v-alert v-if="entries.length > 1" type="warning">有多个目录提供了同名插件，需要删掉多余的一份才能加载。</v-alert>

    <PageTabs :tabs="tabs" :model-value="tab" param="part" :clear="[]" label="插件详情" />

    <form v-if="tab === 'settings'" class="tab-body" @submit.prevent="emit('save')">
      <template v-if="manifest && draft">
        <SchemaForm v-if="manifest.fields.length" :model-value="draft" :fields="manifest.fields" :scene-choices="snapshot.scene_choices" :configured="configured" />
        <EmptyState v-else text="这个插件没有可填的参数" />
      </template>
      <SaveBar :on-save="() => emit('save')" :dirty="dirty" :saving="saving" :error="error" :problem="problem" :restart="false" :label="enabled ? '保存' : '保存并启用'" @discard="emit('discard')" />
    </form>

    <div v-else-if="tab === 'scenes'" class="tab-body">
      <ErrorNote v-if="sceneError" title="群的启用设置没有保存" :error="sceneError" />
      <template v-if="loaded">
        <div class="scene-head"><span class="muted small">{{ used.length }} / {{ scenes.length }} 个群在用</span></div>
        <div class="scene-grid">
          <div v-for="scene in scenes" :key="scene" class="scene-row" :class="{ on: used.includes(scene) }">
            <SceneAvatar :scene="scene" :size="36" />
            <span class="scene-text"><strong>{{ sceneName(scene) }}</strong><span v-if="sceneSubtitle(scene)" class="muted small">{{ sceneSubtitle(scene) }}</span></span>
            <v-progress-circular v-if="switching === scene" indeterminate size="16" width="2" />
            <v-switch :model-value="used.includes(scene)" :disabled="busy || snapshot.scenes[scene].saved === null" :aria-label="`在 ${sceneName(scene)} 使用`"
              @update:model-value="value => emit('scene', scene, value)" />
          </div>
        </div>
        <EmptyState v-if="!scenes.length" text="还没有配置群" />
      </template>
      <EmptyState v-else text="插件启用后可以选择群" />
    </div>

    <div v-else-if="tab === 'features'" class="tab-body">
      <section v-if="manifest || running" class="feature-card trust">
        <div class="trust-row">
          <v-icon :icon="permissions === null ? mdiShieldAlertOutline : mdiShieldCheckOutline" size="18" :class="permissions === null ? 'text-warning' : 'text-success'" />
          <div>
            <strong>权限</strong>
            <p v-if="permissions === null" class="muted small">这个插件没有在 plugin.toml 里声明 permissions，按旧插件处理，可以使用全部宿主能力。</p>
            <p v-else-if="!permissions.length" class="muted small">只用不需要权限的能力（自己的数据、命令、日志等），不能发消息、读历史或调模型。</p>
            <div v-else class="inline perm-chips"><v-chip v-for="item in permissions" :key="item.name" size="small" variant="tonal">{{ item.title }}</v-chip></div>
          </div>
        </div>
        <div class="trust-row">
          <v-icon :icon="mdiCubeOutline" size="18" class="text-medium-emphasis" />
          <div>
            <strong>{{ isolation === 'process' ? '独立进程' : '和主程序同进程' }}</strong>
            <p class="muted small">{{ isolation === 'process'
              ? '插件崩溃只影响它自己，重载就是重启它的进程。这不是安全沙箱，插件仍能访问本机文件和网络。'
              : '插件和 LenBot 跑在同一个进程里，响应最快，但插件卡住或崩溃会影响主程序。' }}</p>
          </div>
        </div>
      </section>
      <EmptyState v-if="!running" text="插件运行后显示它提供的命令和工具" />
      <template v-else>
        <section v-if="running.commands.length || running.rules.length" class="feature-card">
          <h3>命令与消息规则</h3>
          <ul class="feature-list">
            <li v-for="item in running.commands" :key="item.name"><code class="pill">/{{ item.name }}</code><span>{{ item.description }}</span></li>
            <li v-for="item in running.rules" :key="`${item.kind}:${item.pattern}`">
              <span class="kind">{{ item.kind === 'fullmatch' ? '全文' : '正则' }}</span><code class="pill">{{ item.pattern }}</code><span>{{ item.description }}</span></li>
          </ul>
        </section>
        <section v-if="running.tools.length" class="feature-card">
          <h3>模型工具</h3>
          <ul class="feature-list">
            <li v-for="item in running.tools" :key="item.name"><code class="pill">{{ item.name }}</code><span>{{ item.summary }}</span></li>
          </ul>
        </section>
        <section v-if="running.crons.length" class="feature-card">
          <h3>定点播报</h3>
          <ul class="feature-list">
            <li v-for="job in running.crons" :key="`${job.scene}:${job.name}`" class="stacked">
              <span><strong>{{ job.name }}</strong> · {{ sceneName(job.scene) }}</span>
              <span class="muted small"><code>{{ job.expression }}</code> · {{ job.timezone }} · 下次 {{ formatTime(job.next_run) }}</span>
              <ErrorNote v-if="job.last_error" title="上次播报失败" :error="job.last_error" />
            </li>
          </ul>
        </section>
        <section v-if="running.skills.length || running.notices.length" class="feature-card">
          <h3>其他</h3>
          <FactList :items="[['附带技能', running.skills.join('、')], ['处理的通知', running.notices.join('、')]]" />
        </section>
        <EmptyState v-if="!featureCount(running) && !running.crons.length && !running.skills.length && !running.notices.length" text="这个插件没有登记命令或工具" />
      </template>
    </div>

    <div v-else-if="tab === 'activity'" class="tab-body">
      <EmptyState v-if="!running" text="插件运行后显示运行记录" />
      <template v-else>
        <section v-if="running.backgrounds.length" class="feature-card">
          <h3>后台任务</h3>
          <ul class="feature-list">
            <li v-for="item in running.backgrounds" :key="item.method" class="stacked">
              <span><code class="pill">{{ item.method }}</code> {{ every(item.every_seconds) }}</span>
              <span class="muted small">{{ item.last_finished ? `上次完成 ${formatAgo(item.last_finished)}` : item.last_started ? `${formatAgo(item.last_started)}开始运行` : '还没有运行' }}</span>
              <ErrorNote v-if="item.last_error" title="上次运行失败" :error="item.last_error" />
            </li>
          </ul>
        </section>
        <section class="feature-card">
          <h3>最近报错</h3>
          <ul v-if="running.errors.length" class="feature-list">
            <li v-for="(item, index) in running.errors" :key="index" class="stacked">
              <span class="muted small">{{ formatTime(item.at) }}</span><ErrorNote title="插件报错" :error="item.error" />
            </li>
          </ul>
          <p v-else class="muted small">没有报错</p>
        </section>
        <section v-if="running.model_calls.length" class="feature-card">
          <h3>最近的单次生成</h3>
          <ul class="feature-list">
            <li v-for="call in running.model_calls" :key="call.id" class="stacked">
              <span class="small">{{ formatTime(call.started) }} · {{ sceneName(call.scene) }} · {{ call.role }}
                <StatusBadge dot :text="call.ended === null ? '进行中' : call.error ? '失败' : '已返回'" :tone="call.ended === null ? 'info' : call.error ? 'error' : 'success'" /></span>
              <ErrorNote v-if="call.error" title="生成失败" :error="call.error" />
              <DevOnly label="用量与 token" :json="{ usage: call.usage, tokens: call.tokens }" />
            </li>
          </ul>
        </section>
      </template>
    </div>

    <div v-else class="tab-body">
      <section class="feature-card">
        <FactList :items="factsOf(snapshot, name)" />
        <div v-if="source?.previous && !source?.candidate || source?.installed?.kind === 'git'" class="inline">
          <v-btn v-if="source?.installed?.kind === 'git'" variant="outlined" :disabled="busy || dirty" @click="emit('update')">更新／选择版本</v-btn>
          <v-btn v-if="source?.previous && !source?.candidate" variant="text" :disabled="busy" @click="emit('manage', 'rollback')">回到上一版本 v{{ source.previous.version }}</v-btn>
        </div>
      </section>
      <DevOnly label="插件详情" :json="{ available: entries, running }" />
    </div>
  </div>
</template>

<style scoped>
.plugin-detail{display:grid;gap:var(--sp-4);min-width:0}
.back{display:inline-flex;align-items:center;gap:4px;width:max-content;color:var(--muted);font-size:var(--fs-sm)}
.back:hover{color:var(--ink);text-decoration:none}
.detail-head{display:flex;align-items:flex-start;gap:var(--sp-4);min-width:0}
.head-text{display:grid;gap:6px;flex:1;min-width:0}
.head-title{display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap}
.head-title h1{font-size:var(--fs-2xl)}
.version{padding:0 8px;border-radius:999px;background:var(--fill);color:var(--muted);font-size:var(--fs-xs);font-weight:600;line-height:22px}
.description{margin:0;color:var(--muted);max-width:880px}
.head-meta{display:flex;flex-wrap:wrap;gap:var(--sp-1) var(--sp-4);font-size:var(--fs-sm);color:var(--muted)}
.head-meta a{display:inline-flex;align-items:center;gap:2px}
.head-actions{display:flex;align-items:center;gap:var(--sp-2);flex:none}
.alert-actions{display:flex;gap:var(--sp-2)}
.tab-body{display:grid;gap:var(--sp-4);min-width:0;padding-top:var(--sp-1)}
.scene-head{display:flex;align-items:center}
.scene-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:var(--sp-2)}
.scene-row{display:flex;align-items:center;gap:var(--sp-3);min-width:0;padding:var(--sp-2) var(--sp-2) var(--sp-2) var(--sp-3);border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);transition:border-color var(--dur-2),background-color var(--dur-2)}
.scene-row.on{border-color:color-mix(in srgb,var(--brand) 45%,var(--line))}
.scene-text{display:grid;flex:1;min-width:0;line-height:1.35}
.scene-text strong{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.scene-row .v-switch{flex:none}
.feature-card{display:grid;gap:var(--sp-3);padding:var(--sp-5);border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);min-width:0}
.feature-card h3{font-size:var(--fs-lg);font-weight:650}
.feature-card p{margin:0}
.feature-list{list-style:none;margin:0;padding:0;display:grid}
.feature-list li{display:flex;align-items:baseline;gap:var(--sp-3);padding:var(--sp-2) 0;border-top:1px solid var(--line);min-width:0}
.feature-list li:first-child{border-top:0;padding-top:0}
.feature-list li > span:last-child{overflow-wrap:anywhere}
.feature-list li.stacked{display:grid;gap:var(--sp-1)}
.pill{flex:none;padding:1px 8px;border-radius:6px;background:var(--code-bg);font-size:var(--fs-sm);white-space:nowrap}
.kind{flex:none;font-size:var(--fs-xs);color:var(--muted)}
.health-warn{margin:0;padding:var(--sp-2) var(--sp-3);border-radius:var(--radius);background:var(--warning-bg);color:var(--warning)}
.trust-row{display:flex;gap:var(--sp-3);align-items:flex-start}
.trust-row > div{display:grid;gap:var(--sp-1);min-width:0}
.perm-chips{flex-wrap:wrap}
@media(max-width:700px){
  .detail-head{flex-wrap:wrap}
  .head-actions{width:100%}
  .feature-list li{flex-wrap:wrap}
}
</style>
