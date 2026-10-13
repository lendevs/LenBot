<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { mdiAlertCircleOutline, mdiChevronDown, mdiFolderCogOutline, mdiForumOutline, mdiGit, mdiMagnify, mdiPlus, mdiStorefrontOutline, mdiToolboxOutline, mdiZipBoxOutline } from '@mdi/js'
import { api } from '../../../api.js'
import { useAction, useResource } from '../../../composables/useResource.js'
import { confirm } from '../../../composables/useConfirm.js'
import { notify, readPendingRestart } from '../../store.js'
import { same } from '../../forms.js'
import { initialField, configValue } from '../../pluginConfig.js'
import { pluginsApi } from '../../api/plugins.js'
import PageTabs from '../../ui/PageTabs.vue'
import ResourceState from '../../ui/ResourceState.vue'
import Panel from '../../ui/Panel.vue'
import ObjectList from '../../ui/ObjectList.vue'
import ObjectRow from '../../ui/ObjectRow.vue'
import StatusBadge from '../../ui/StatusBadge.vue'
import FormDialog from '../../ui/FormDialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import EmptyState from '../../ui/EmptyState.vue'
import PluginCatalog from './PluginCatalog.vue'
import PluginDetail from './PluginDetail.vue'
import PluginMark from './PluginMark.vue'
import { enabledIn, featureCount, healthNote, isolationOf, manifestOf, permissionsOf, runningOf, scenesUsing, statusIn, versionOf } from './pluginView.js'

const emit = defineEmits(['dirty'])
const route = useRoute(), router = useRouter()
const plugins = useResource(() => pluginsApi.read())
const save = useAction()
const active = ref('')
const drafts = ref({}), paths = ref(null), pathsOpen = ref(false)
const zipImport = ref(false), zipFile = ref(null), switchSource = ref(false)
const installing = ref(false), repository = ref(''), repositoryRef = ref('')
const catalogDirty = ref(false), updating = ref(null), updateRef = ref('')
const switching = ref('')
const snapshot = computed(() => plugins.data.value)

const view = computed(() => route.query.view === 'discover' ? 'discover' : 'installed')
const selected = computed(() => typeof route.query.item === 'string' ? route.query.item : null)
const open = name => router.push({ query: { ...route.query, view: undefined, item: name } })
const back = () => router.push({ query: { ...route.query, item: undefined, part: undefined } })

const names = computed(() => snapshot.value ? [...new Set([...Object.keys(snapshot.value.available),
  ...Object.keys(snapshot.value.saved.plugins), ...snapshot.value.running.plugins.map(item => item.name)])].sort() : [])
const detail = computed(() => Boolean(selected.value && names.value.includes(selected.value)))
const runningCount = computed(() => snapshot.value?.running.plugins.filter(item => item.status === 'running').length || 0)
const manifest = name => manifestOf(snapshot.value, name)

function initial(name) {
  const saved = snapshot.value.saved.plugins[name], values = {}
  for (const field of manifest(name)?.fields || []) {
    const item = saved?.[field.key]
    values[field.key] = initialField(field, item && 'value' in item ? item.value : field.default)
  }
  return values
}
const initialPaths = () => ({ paths: snapshot.value.saved.paths.join('\n'), data_directory: snapshot.value.saved.data_directory })
function reset(part) {
  if (part === 'paths') paths.value = initialPaths()
  else drafts.value[part] = initial(part)
}
watch(() => plugins.data.value, (value, previous) => {
  if (!value) return
  for (const name of names.value) if (!drafts.value[name]) reset(name)
  if (!previous) reset('paths')
})
watch(selected, (_, previous) => { if (previous && snapshot.value && names.value.includes(previous)) reset(previous) })
watch(pathsOpen, value => { if (!value && snapshot.value) reset('paths') })

const pluginDirty = name => Boolean(drafts.value[name]) && !same(drafts.value[name], initial(name))
const pathsDirty = computed(() => paths.value !== null && !same(paths.value, initialPaths()))
const dirty = computed(() => Boolean(snapshot.value) && (names.value.some(pluginDirty) || pathsDirty.value || catalogDirty.value))
watch(dirty, value => emit('dirty', value), { immediate: true })

function configBody(name) {
  const draft = drafts.value[name], config = {}
  for (const field of manifest(name).fields) {
    const value = draft[field.key]
    if (field.type === 'secret') {
      if (value !== '') config[field.key] = value
      else if (snapshot.value.saved.plugins[name]?.[field.key]?.configured) config[field.key] = null
    } else {
      const parsed = configValue(field, value)
      if (parsed !== undefined) config[field.key] = parsed
    }
  }
  return config
}
async function send(part, path, body) {
  active.value = part
  const result = await save.run(async () => api(path, { method: 'PUT', body: JSON.stringify(typeof body === 'function' ? body() : body) }))
  if (result) {
    plugins.data.value = result
    if (part !== 'scene') reset(part)
    readPendingRestart()
    notify('已保存')
  } else await plugins.reload()
  return result
}
// The host saves parameters only together with enabling, so saving a stopped plugin also starts it.
const savePlugin = name => send(name, `/api/host/plugins/${encodeURIComponent(name)}`, () => ({ enabled: true, config: configBody(name) }))
const disablePlugin = name => send(name, `/api/host/plugins/${encodeURIComponent(name)}`, { enabled: false })
async function toggleScene(name, scene, on) {
  const current = snapshot.value.scenes[scene].saved || []
  switching.value = scene
  try {
    await send('scene', `/api/host/scenes/${encodeURIComponent(scene)}/plugins`,
      { plugins: on ? [...current, name] : current.filter(item => item !== name) })
  } finally { switching.value = '' }
}
async function savePaths() {
  const result = await send('paths', '/api/host/plugin-paths', {
    paths: paths.value.paths.split('\n').map(item => item.trim()).filter(Boolean), data_directory: paths.value.data_directory.trim(),
  })
  if (result) pathsOpen.value = false
}
async function operate(part, action) {
  active.value = part
  const result = await save.run(action)
  if (result) {
    const keepPathsDraft = pathsDirty.value
    plugins.data.value = result
    if (part === 'install') {
      repository.value = ''
      repositoryRef.value = ''
      installing.value = false
      zipImport.value = false
      zipFile.value = null
      switchSource.value = false
      if (!keepPathsDraft) reset('paths')
      reset(result.operation.name)
      notify(result.operation.needs_config ? '候选已准备，请填写参数后应用' : '候选已准备，可以应用')
      open(result.operation.name)
    } else {
      if (names.value.includes(part)) reset(part)
      else delete drafts.value[part]
      notify(result.running.plugins.some(item => item.name === part && item.status === 'failed') ? '操作未完成，请看插件错误' : '操作完成')
    }
    readPendingRestart()
  } else await plugins.reload()
  return result
}
const install = () => operate('install', () => pluginsApi.install(repository.value.trim(), repositoryRef.value.trim() || null, switchSource.value))
const importZip = () => operate('install', () => pluginsApi.importZip(zipFile.value, switchSource.value))
const manage = (name, action) => operate(name, () => api(`/api/host/plugins/${encodeURIComponent(name)}/${action}`, { method: 'POST' }))
function installEntry(entry) {
  if ('compatible' in entry) return operate('install', () => pluginsApi.marketInstall(entry.name))
  repository.value = entry.repository
  repositoryRef.value = entry.ref || ''
  installing.value = true
}
function chooseUpdate(name, selectedRef = null) {
  updating.value = name
  updateRef.value = selectedRef ?? manifest(name)?.source?.ref ?? ''
}
async function update() {
  const name = updating.value
  const result = await operate(name, () => pluginsApi.update(name, updateRef.value.trim() || null))
  if (result) updating.value = null
}
const removals = {
  source: { title: name => `卸载插件 ${name}？`, text: '停止它的处理器和后台，移除源码和启用配置；插件自己的数据保留。', confirmLabel: '卸载并保留数据' },
  data: { title: name => `删除插件 ${name} 的数据？`, text: '删除这个插件的数据目录，包括它保存的设置和素材，聊天记录不受影响。删除后不能恢复。', confirmLabel: '删除数据' },
}
async function remove(name, kind) {
  const question = removals[kind]
  if (!await confirm({ title: question.title(name), text: question.text, confirmLabel: question.confirmLabel, danger: true })) return
  const result = await operate(name, () => api(kind === 'source' ? `/api/host/plugins/${encodeURIComponent(name)}`
    : `/api/host/plugin-data/${encodeURIComponent(name)}`, { method: 'DELETE' }))
  if (result && kind === 'source') back()
}
// Health is cheap to read (no disk access), so poll it while the page is open and overlay it on the full snapshot.
const healthByName = ref({})
async function readHealth() {
  try { healthByName.value = Object.fromEntries((await pluginsApi.health()).plugins.map(item => [item.name, item])) } catch { /* the full snapshot still has health */ }
}
let healthTimer = 0
onMounted(() => { readHealth(); healthTimer = setInterval(() => { if (document.visibilityState === 'visible') readHealth() }, 10000) })
onBeforeUnmount(() => clearInterval(healthTimer))
watch(() => plugins.data.value, readHealth)
const health = name => healthByName.value[name]?.health || runningOf(snapshot.value, name)?.health || null

const query = ref(''), filter = ref('all')
const bucket = name => {
  if (snapshot.value.saved.disabled.includes(name)) return 'disabled'
  if (!snapshot.value.saved.plugins[name]) return 'idle'
  const level = health(name)?.level
  return runningOf(snapshot.value, name)?.status === 'failed' || level === 'failed' || level === 'degraded' ? 'attention' : 'on'
}
const filters = computed(() => {
  const counts = { all: names.value.length, on: 0, attention: 0, disabled: 0, idle: 0 }
  for (const name of names.value) counts[bucket(name)]++
  return [['all', '全部'], ['on', '已启用'], ['attention', '需要注意'], ['disabled', '已停用'], ['idle', '未启用']]
    .filter(([key]) => key === 'all' || counts[key]).map(([key, label]) => ({ key, label, count: counts[key] }))
})
watch(filters, list => { if (!list.some(item => item.key === filter.value)) filter.value = 'all' })
const shownNames = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return names.value.filter(name => (filter.value === 'all' || bucket(name) === filter.value)
    && words.every(word => `${name} ${manifest(name)?.description || ''} ${(manifest(name)?.authors || []).join(' ')}`.toLowerCase().includes(word)))
})
const errorOf = part => active.value === part ? save.error.value : null
</script>

<template>
  <PageTabs v-if="!detail" :tabs="[['installed', '已安装'], ['discover', '发现插件']]" :model-value="view" param="view" label="插件" />
  <ResourceState :resource="plugins" error-title="读取插件失败">
    <PluginDetail v-if="detail" :name="selected" :snapshot="snapshot" :draft="drafts[selected] || null" :dirty="pluginDirty(selected)"
      :health="health(selected)" :busy="save.busy.value" :saving="save.busy.value && active === selected" :error="errorOf(selected)" :scene-error="errorOf('scene')" :switching="switching"
      @save="savePlugin(selected)" @enable="savePlugin(selected)" @disable="disablePlugin(selected)" @discard="reset(selected)"
      @scene="(scene, on) => toggleScene(selected, scene, on)" @manage="action => manage(selected, action)" @remove="kind => remove(selected, kind)"
      @update="chooseUpdate(selected)" />

    <PluginCatalog v-else-if="view === 'discover'" :snapshot="snapshot" :busy="save.busy.value" @dirty="value => catalogDirty = value"
      @install="installEntry" @configure="open" @update="entry => chooseUpdate(entry.name, entry.ref)" />

    <div v-else class="installed">
      <div class="toolbar">
        <span class="muted">{{ names.length }} 个插件<template v-if="names.length"> · {{ runningCount }} 个运行中</template></span>
        <v-text-field v-if="names.length > 3" :model-value="query" @update:model-value="query = $event ?? ''" class="search" density="compact" hide-details clearable :prepend-inner-icon="mdiMagnify"
          placeholder="搜索名称、说明或作者" aria-label="搜索插件" />
        <v-btn class="ml-auto" variant="text" :prepend-icon="mdiFolderCogOutline" @click="pathsOpen = true">插件目录</v-btn>
        <v-menu location="bottom end">
          <template #activator="{ props: menu }">
            <v-btn v-bind="menu" color="primary" :prepend-icon="mdiPlus" :append-icon="mdiChevronDown">安装插件</v-btn>
          </template>
          <v-list density="compact" min-width="220">
            <v-list-item :prepend-icon="mdiStorefrontOutline" title="从插件目录挑选" :to="{ query: { ...route.query, view: 'discover' } }" />
            <v-list-item :prepend-icon="mdiGit" title="从 Git 仓库安装" @click="installing = true" />
            <v-list-item :prepend-icon="mdiZipBoxOutline" title="导入 ZIP 文件" @click="zipImport = true" />
          </v-list>
        </v-menu>
      </div>

      <div v-if="filters.length > 2" class="filter-chips" role="group" aria-label="按状态筛选">
        <v-chip v-for="item in filters" :key="item.key" size="small" :variant="filter === item.key ? 'flat' : 'outlined'"
          :color="filter === item.key ? (item.key === 'attention' ? 'error' : 'primary') : undefined" @click="filter = item.key">{{ item.label }} {{ item.count }}</v-chip>
      </div>
      <EmptyState v-if="names.length && !shownNames.length" text="没有符合条件的插件" />
      <div v-if="names.length" class="plugin-grid">
        <button v-for="name in shownNames" :key="name" type="button" class="plugin-card" :class="{ off: !enabledIn(snapshot, name) }" @click="open(name)">
          <span class="card-head">
            <PluginMark :name="name" :size="40" :muted="!enabledIn(snapshot, name)" />
            <span class="card-title"><strong>{{ name }}</strong><span v-if="versionOf(snapshot, name)" class="muted small">v{{ versionOf(snapshot, name) }}</span></span>
            <StatusBadge dot v-bind="statusIn(snapshot, name)" />
          </span>
          <span class="card-description">{{ manifest(name)?.description || '' }}</span>
          <span class="card-foot">
            <span><v-icon :icon="mdiForumOutline" size="15" />{{ scenesUsing(snapshot, name).length ? `${scenesUsing(snapshot, name).length} 个群` : '没有群在用' }}</span>
            <span v-if="featureCount(runningOf(snapshot, name))"><v-icon :icon="mdiToolboxOutline" size="15" />{{ featureCount(runningOf(snapshot, name)) }} 项功能</span>
            <span v-if="runningOf(snapshot, name)?.errors.length" class="problem"><v-icon :icon="mdiAlertCircleOutline" size="15" />最近报错 {{ runningOf(snapshot, name).errors.length }} 次</span>
            <span v-if="healthNote(health(name))" class="tag warn">{{ healthNote(health(name)) }}</span>
            <span v-if="isolationOf(snapshot, name) === 'process'" class="tag" title="跑在独立进程里，崩溃不影响主程序">独立进程</span>
            <span v-if="permissionsOf(snapshot, name) === null" class="tag dim" title="没有在 plugin.toml 里声明 permissions，保留全部能力">未声明权限</span>
            <span v-else class="tag" :title="permissionsOf(snapshot, name).map(item => item.title).join('、') || '不需要额外权限'">{{ permissionsOf(snapshot, name).length }} 项权限</span>
          </span>
        </button>
      </div>
      <EmptyState v-else text="还没有安装插件">
        <v-btn variant="outlined" :to="{ query: { ...route.query, view: 'discover' } }">去发现插件</v-btn>
      </EmptyState>

      <ErrorNote v-for="error in [...snapshot.discovery_errors, ...snapshot.running.discovery_errors]" :key="error" title="有插件目录读不了" :error="error" />
      <Panel v-if="snapshot.retained_data.length" title="已卸载插件留下的数据" flush>
        <ObjectList class="list" divided>
          <ObjectRow v-for="item in snapshot.retained_data" :key="item.name" :title="item.name" :subtitle="item.directory">
            <template #actions><v-btn variant="text" size="small" color="error" :disabled="save.busy.value" @click="remove(item.name, 'data')">删除数据</v-btn></template>
          </ObjectRow>
        </ObjectList>
      </Panel>
    </div>
  </ResourceState>

  <FormDialog v-if="paths" v-model="pathsOpen" title="插件目录" :busy="save.busy.value && active === 'paths'">
    <v-textarea v-model="paths.paths" rows="2" auto-grow label="插件目录（每行一个）" placeholder="plugins" />
    <v-text-field v-model="paths.data_directory" label="插件数据目录" />
    <ErrorNote v-if="errorOf('paths')" title="没有保存成功" :error="errorOf('paths')" />
    <template #actions><v-btn color="primary" :loading="save.busy.value && active === 'paths'" :disabled="!pathsDirty" @click="savePaths">保存</v-btn></template>
  </FormDialog>
  <FormDialog v-model="installing" title="从 Git 仓库安装" :busy="save.busy.value && active === 'install'">
    <v-text-field v-model="repository" label="插件仓库 URL" placeholder="https://example.com/author/plugin.git" />
    <v-text-field v-model="repositoryRef" label="版本（可选）" placeholder="标签、分支或提交" />
    <v-switch v-model="switchSource" label="替换同名插件的安装来源" />
    <ErrorNote v-if="errorOf('install')" title="插件准备没有完成" :error="errorOf('install')" />
    <template #actions><v-btn color="primary" :loading="save.busy.value && active === 'install'" :disabled="!repository.trim()" @click="install">准备候选</v-btn></template>
  </FormDialog>
  <FormDialog v-model="zipImport" title="导入 ZIP 文件" :busy="save.busy.value && active === 'install'">
    <v-file-input v-model="zipFile" accept=".zip,application/zip" label="插件 ZIP" />
    <p class="muted">ZIP 根目录或唯一顶层目录须包含 plugin.toml 和 __init__.py。</p>
    <v-switch v-model="switchSource" label="替换同名插件的安装来源" />
    <ErrorNote v-if="errorOf('install')" title="ZIP 准备没有完成" :error="errorOf('install')" />
    <template #actions><v-btn color="primary" :loading="save.busy.value" :disabled="!zipFile" @click="importZip">准备候选</v-btn></template>
  </FormDialog>
  <FormDialog :model-value="updating !== null" :title="`更新 ${updating || ''}`" :busy="save.busy.value" @update:model-value="value => { if (!value) updating = null }">
    <v-text-field v-model="updateRef" label="标签、分支或提交" />
    <v-alert v-if="updating && pluginDirty(updating)" type="warning">这个插件的参数还没保存，请先保存或放弃修改。</v-alert>
    <ErrorNote v-if="updating && errorOf(updating)" title="更新没有完成" :error="errorOf(updating)" />
    <template #actions><v-btn color="primary" :loading="save.busy.value" :disabled="!updating || pluginDirty(updating)" @click="update">准备候选</v-btn></template>
  </FormDialog>
</template>

<style scoped>
.installed{display:grid;gap:var(--sp-4);min-width:0}
.toolbar{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
.list{padding:0 var(--sp-2) var(--sp-2)}
.plugin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:var(--sp-4)}
.plugin-card{display:grid;grid-template-rows:auto 1fr auto;gap:var(--sp-3);text-align:left;padding:var(--sp-4) var(--sp-5) var(--sp-4);border:1px solid var(--line);border-radius:var(--radius-lg);
  background:var(--surface);color:inherit;font:inherit;cursor:pointer;transition:border-color var(--dur-2),box-shadow var(--dur-2) var(--ease-out),transform var(--dur-2) var(--ease-out)}
.plugin-card:hover,.plugin-card:focus-visible{border-color:var(--line-strong);box-shadow:var(--shadow-hover);transform:translateY(-1px);outline:none}
.plugin-card:focus-visible{box-shadow:0 0 0 2px var(--primary)}
.card-head{display:flex;align-items:center;gap:var(--sp-3);min-width:0}
.card-title{display:grid;flex:1;min-width:0;line-height:1.35}
.card-title strong{font-size:var(--fs-lg);font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-description{align-self:start;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:3.2em;color:var(--muted);font-size:var(--fs-sm)}
.card-foot{display:flex;flex-wrap:wrap;gap:var(--sp-1) var(--sp-4);padding-top:var(--sp-3);border-top:1px solid var(--line);font-size:var(--fs-sm);color:var(--muted)}
.card-foot span{display:inline-flex;align-items:center;gap:4px}
.card-foot .problem{color:var(--error)}
.plugin-card.off .card-title strong{color:var(--muted)}
.search{flex:0 1 280px}
.filter-chips{display:flex;flex-wrap:wrap;gap:var(--sp-2)}
.tag{font-size:11px;line-height:18px;padding:0 7px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
.tag.warn{border-color:transparent;background:var(--warning-bg);color:var(--warning)}
.tag.dim{border-style:dashed}
</style>
