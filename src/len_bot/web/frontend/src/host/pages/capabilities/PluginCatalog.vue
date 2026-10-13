<script setup>
import { computed, ref, watch } from 'vue'
import { mdiMagnify, mdiOpenInNew, mdiRefresh, mdiTuneVariant } from '@mdi/js'
import { pluginsApi } from '../../api/plugins.js'
import { useAction, useResource } from '../../../composables/useResource.js'
import { formatTime } from '../../time.js'
import ErrorNote from '../../ui/ErrorNote.vue'
import EmptyState from '../../ui/EmptyState.vue'
import FormDialog from '../../ui/FormDialog.vue'
import StatusBadge from '../../ui/StatusBadge.vue'
import FactList from '../../ui/FactList.vue'
import { permissionSummary } from '../../pluginPermissions.js'
import PluginMark from './PluginMark.vue'

const props = defineProps({ snapshot: Object, busy: Boolean })
const emit = defineEmits(['dirty', 'install', 'configure', 'update'])
const catalog = useResource(() => pluginsApi.catalog()), source = ref(''), search = ref(''), category = ref('')
const market = useResource(() => pluginsApi.market(search.value.trim(), category.value))
const selected = ref(null), sourceOpen = ref(false), sourceAction = useAction(), refresh = useAction()
watch(() => catalog.data.value?.url, value => { source.value = value || '' })
const dirty = computed(() => catalog.data.value !== null && source.value.trim() !== (catalog.data.value.url || ''))
watch(dirty, value => emit('dirty', value), { immediate: true })
watch(sourceOpen, value => { if (!value) source.value = catalog.data.value?.url || '' })
// Filtering happens on the server so installed/update/compatibility stay in one place; debounce typing.
let timer = 0
watch(search, () => { clearTimeout(timer); timer = setTimeout(market.reload, 250) })
watch(category, () => market.reload())
// Installing, removing or updating changes the snapshot; re-annotate the catalog against it.
watch(() => props.snapshot, () => market.reload())
const categories = computed(() => [{ title: '全部分类', value: '' }, ...(market.data.value?.categories || []).map(value => ({ title: value, value }))])
const entries = computed(() => market.data.value?.entries || [])
const manifest = name => props.snapshot.available[name]?.length === 1 ? props.snapshot.available[name][0] : null
const running = name => props.snapshot.running.plugins.find(item => item.name === name)
const configured = name => name in props.snapshot.saved.plugins
const state = entry => !entry.installed ? (entry.compatible ? ['', 'neutral'] : ['不兼容', 'error'])
  : props.snapshot.saved.disabled.includes(entry.name) ? ['已停用', 'neutral']
    : running(entry.name)?.status === 'failed' ? ['加载失败', 'error'] : running(entry.name)?.status === 'running' ? ['运行中', 'success']
      : configured(entry.name) ? ['已配置', 'info'] : ['已安装', 'info']
async function reload() {
  const result = await refresh.run(() => pluginsApi.refreshCatalog())
  if (result) { catalog.data.value = result; await market.reload() }
}
// A remote catalog is only read on request; opening this view is that request.
watch(() => catalog.data.value, (value, previous) => { if (value && !previous && !value.loaded_at) reload() })
async function saveSource() {
  const result = await sourceAction.run(() => pluginsApi.catalogSource(source.value.trim() || null))
  if (!result) return
  catalog.data.value = result
  sourceOpen.value = false
  await reload()
}
function configure(name) { selected.value = null; emit('configure', name) }
function install(entry) { selected.value = null; emit('install', entry) }
function update(entry) { selected.value = null; emit('update', entry) }
</script>

<template>
  <div class="catalog">
    <div class="toolbar">
      <v-text-field v-model="search" :prepend-inner-icon="mdiMagnify" placeholder="搜索名称、用途、作者或能力" density="compact" class="search" />
      <v-select v-model="category" :items="categories" density="compact" class="category" aria-label="分类" />
      <v-btn variant="text" :prepend-icon="mdiRefresh" :loading="refresh.busy.value" :disabled="sourceAction.busy.value" @click="reload">刷新</v-btn>
      <v-btn variant="text" :prepend-icon="mdiTuneVariant" @click="sourceOpen = true">目录来源</v-btn>
    </div>
    <ErrorNote v-if="market.error.value || catalog.error.value || refresh.error.value" title="目录读取失败" :error="market.error.value || catalog.error.value || refresh.error.value" @retry="reload" />
    <EmptyState v-if="market.data.value && !market.data.value.loaded_at && !refresh.busy.value" text="目录还没有读取" />
    <EmptyState v-else-if="market.data.value?.loaded_at && !entries.length" text="没有匹配的插件" />
    <div class="cards">
      <article v-for="entry in entries" :key="entry.name" class="catalog-card" :class="{ off: !entry.compatible && !entry.installed }">
        <div class="card-head">
          <PluginMark :name="entry.name" :size="40" />
          <div class="card-title"><strong>{{ entry.title }}</strong><span class="muted small">{{ entry.authors.join('、') }} · v{{ entry.version }}</span></div>
          <StatusBadge v-if="state(entry)[0]" dot :text="state(entry)[0]" :tone="state(entry)[1]" />
        </div>
        <p class="description">{{ entry.description }}</p>
        <p v-if="entry.update_available" class="note warn small">已装 v{{ entry.installed_version }}，目录里有 v{{ entry.version }}</p>
        <p v-else-if="!entry.compatible" class="note bad small">{{ entry.incompatible_reason }}</p>
        <div v-if="entry.capabilities.length" class="caps"><span v-for="capability in entry.capabilities" :key="capability" class="cap">{{ capability }}</span></div>
        <div class="actions">
          <v-btn variant="text" size="small" @click="selected = entry">详情</v-btn>
          <v-btn v-if="entry.update_available && manifest(entry.name)?.managed" size="small" variant="text" :disabled="busy" @click="update(entry)">更新到 v{{ entry.version }}</v-btn>
          <v-btn v-if="entry.installed" size="small" variant="outlined" class="ml-auto" @click="configure(entry.name)">去配置</v-btn>
          <v-btn v-else size="small" color="primary" class="ml-auto" :disabled="busy || !entry.compatible" @click="install(entry)">安装</v-btn>
        </div>
      </article>
    </div>
  </div>

  <FormDialog :model-value="selected !== null" :title="selected?.title || ''" size="md" cancel-label="关闭" @update:model-value="value => { if (!value) selected = null }">
    <template v-if="selected">
      <p>{{ selected.description }}</p>
      <section v-if="selected.usage.length" class="usage-block">
        <h3>用法</h3>
        <ol class="usage"><li v-for="item in selected.usage" :key="item">{{ item }}</li></ol>
      </section>
      <div v-if="selected.capabilities.length" class="caps"><span v-for="capability in selected.capabilities" :key="capability" class="cap">{{ capability }}</span></div>
      <p v-if="'permissions' in selected" class="small" :class="selected.permissions == null ? 'note warn' : 'muted'">{{ permissionSummary(selected.permissions) }}</p>
      <FactList :items="[['插件名', selected.name], ['版本', `v${selected.version}${selected.ref ? ` · ${selected.ref}` : ''}`], ['接口', selected.interface],
        ['许可证', selected.license], ['宿主兼容范围', selected.requires_lenbot],
        ['本机版本', selected.installed ? `v${selected.installed_version || '未知'}` : '']]" />
      <p v-if="!selected.compatible" class="note bad small">{{ selected.incompatible_reason }}</p>
      <div class="inline">
        <a v-if="selected.repository" :href="selected.repository" target="_blank" rel="noopener noreferrer">源码仓库<v-icon :icon="mdiOpenInNew" size="13" /></a>
        <a v-if="selected.homepage" :href="selected.homepage" target="_blank" rel="noopener noreferrer">项目说明<v-icon :icon="mdiOpenInNew" size="13" /></a>
      </div>
    </template>
    <template v-if="selected" #actions>
      <v-btn v-if="selected.installed" color="primary" @click="configure(selected.name)">去配置</v-btn>
      <v-btn v-else color="primary" :disabled="busy || !selected.compatible" @click="install(selected)">一键安装</v-btn>
    </template>
  </FormDialog>
  <FormDialog v-model="sourceOpen" title="目录来源" :busy="sourceAction.busy.value">
    <v-text-field v-model="source" label="远程目录地址" placeholder="留空使用本版本随附目录" :disabled="sourceAction.busy.value" />
    <p v-if="catalog.data.value?.loaded_at" class="muted small">{{ catalog.data.value.source === 'builtin' ? '本版本随附目录' : '远程目录' }}，读取于 {{ formatTime(catalog.data.value.loaded_at) }}</p>
    <ErrorNote v-if="sourceAction.error.value" title="目录来源没有保存" :error="sourceAction.error.value" />
    <template #actions><v-btn color="primary" :disabled="!dirty" :loading="sourceAction.busy.value" @click="saveSource">保存并读取</v-btn></template>
  </FormDialog>
</template>

<style scoped>
.catalog{display:grid;gap:var(--sp-4);min-width:0}
.toolbar{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
.search{flex:1 1 320px}
.category{flex:0 0 200px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:var(--sp-4)}
.catalog-card{display:grid;grid-template-rows:auto auto 1fr auto;align-items:start;gap:var(--sp-3);padding:var(--sp-4) var(--sp-5);border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);
  transition:border-color var(--dur-2),box-shadow var(--dur-2) var(--ease-out)}
.catalog-card:hover{border-color:var(--line-strong);box-shadow:var(--shadow-hover)}
.catalog-card.off{opacity:.72}
.card-head{display:flex;align-items:center;gap:var(--sp-3);min-width:0}
.card-title{display:grid;flex:1;min-width:0;line-height:1.35}
.card-title strong{font-size:var(--fs-lg);font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-title span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.description{margin:0;color:var(--muted);font-size:var(--fs-sm);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.note{margin:0;padding:2px var(--sp-2);border-radius:var(--radius);justify-self:start;overflow-wrap:anywhere}
.note.warn{background:var(--warning-bg);color:var(--warning)}
.note.bad{background:var(--error-bg);color:var(--error)}
.caps{display:flex;flex-wrap:wrap;gap:6px}
.cap{padding:0 8px;border-radius:999px;background:var(--fill);color:var(--muted);font-size:var(--fs-xs);line-height:22px}
.actions{align-self:end;display:flex;align-items:center;gap:var(--sp-1);padding-top:var(--sp-3);border-top:1px solid var(--line)}
.usage-block{display:grid;gap:var(--sp-2)}
.usage-block h3{font-size:var(--fs-md)}
.usage{padding-left:var(--sp-5);margin:0;display:grid;gap:var(--sp-1)}
.inline a{display:inline-flex;align-items:center;gap:2px}
@media(max-width:700px){.category{flex:1 1 100%}}
</style>
