<script setup>
import { computed, ref, watch } from 'vue'
import { pluginsApi } from '../../api/plugins.js'
import { useAction, useResource } from '../../../composables/useResource.js'
import { formatTime } from '../../time.js'
import Panel from '../../ui/Panel.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import EmptyState from '../../ui/EmptyState.vue'
import FormDialog from '../../ui/FormDialog.vue'
import Fold from '../../ui/Fold.vue'

const props = defineProps({ snapshot: Object, busy: Boolean })
const emit = defineEmits(['dirty', 'install', 'configure', 'update'])
const catalog = useResource(() => pluginsApi.catalog()), source = ref(''), search = ref(''), category = ref('')
const market = useResource(() => pluginsApi.market(search.value.trim(), category.value))
const selected = ref(null), sourceAction = useAction(), refresh = useAction()
watch(() => catalog.data.value?.url, value => { source.value = value || '' })
const dirty = computed(() => catalog.data.value !== null && source.value.trim() !== (catalog.data.value.url || ''))
watch(dirty, value => emit('dirty', value), { immediate: true })
// Filtering happens on the server so installed/update/compatibility stay in one place; debounce typing.
let timer = 0
watch(search, () => { clearTimeout(timer); timer = setTimeout(market.reload, 250) })
watch(category, () => market.reload())
// Installing, removing or updating changes the snapshot; re-annotate the catalog against it.
watch(() => props.snapshot, () => market.reload())
const categories = computed(() => [{ title: '全部分类', value: '' }, ...(market.data.value?.categories || []).map(value => ({ title: value, value }))])
const entries = computed(() => market.data.value?.entries || [])
const updates = computed(() => entries.value.filter(entry => entry.update_available).length)
const manifest = name => props.snapshot.available[name]?.length === 1 ? props.snapshot.available[name][0] : null
const running = name => props.snapshot.running.plugins.find(item => item.name === name)
const configured = name => name in props.snapshot.saved.plugins
const state = entry => !entry.installed ? (entry.compatible ? ['未安装', undefined] : ['不兼容', 'error'])
  : props.snapshot.saved.disabled.includes(entry.name) ? ['已停用', undefined]
    : running(entry.name)?.status === 'failed' ? ['加载失败', 'error'] : running(entry.name)?.status === 'running' ? ['运行中', 'success']
      : configured(entry.name) ? ['已配置', 'info'] : ['已安装', 'info']
async function reload() {
  const result = await refresh.run(() => pluginsApi.refreshCatalog())
  if (result) { catalog.data.value = result; await market.reload() }
}
async function saveSource() {
  const result = await sourceAction.run(() => pluginsApi.catalogSource(source.value.trim() || null))
  if (!result) return
  catalog.data.value = result
  await reload()
}
function configure(name) { selected.value = null; emit('configure', name) }
function install(entry) { selected.value = null; emit('install', entry) }
function update(entry) { selected.value = null; emit('update', entry) }
</script>

<template>
  <Panel title="发现插件" :description="market.data.value ? `${market.data.value.total} 个插件${updates ? `，${updates} 个可更新` : ''} · ${market.data.value.source === 'builtin' ? '本版本随附目录' : market.data.value.url}${market.data.value.loaded_at ? ` · 读取于 ${formatTime(market.data.value.loaded_at)}` : ''}` : catalog.data.value ? `${catalog.data.value.source === 'builtin' ? '本版本随附目录' : catalog.data.value.url}${catalog.data.value.loaded_at ? ` · 读取于 ${formatTime(catalog.data.value.loaded_at)}` : ''}` : ''">
    <template #actions><v-btn size="small" variant="text" :loading="refresh.busy.value" :disabled="dirty || sourceAction.busy.value" @click="reload">刷新目录</v-btn></template>
    <ErrorNote v-if="market.error.value || catalog.error.value || sourceAction.error.value || refresh.error.value" title="目录读取或保存失败" :error="market.error.value || catalog.error.value || sourceAction.error.value || refresh.error.value" />
    <div class="filters">
      <v-text-field v-model="search" label="搜索名称、用途、作者或能力" />
      <v-select v-model="category" :items="categories" label="分类" />
    </div>
    <Fold label="目录来源">
      <v-text-field v-model="source" label="远程目录地址" placeholder="本版本随附目录" :disabled="sourceAction.busy.value || refresh.busy.value" />
      <v-btn size="small" variant="outlined" class="start" :disabled="!dirty || refresh.busy.value" :loading="sourceAction.busy.value" @click="saveSource">保存并读取</v-btn>
    </Fold>
  </Panel>
  <EmptyState v-if="!market.data.value?.loaded_at && !market.loading.value" text="点击刷新目录读取插件列表" />
  <EmptyState v-else-if="!entries.length" text="没有匹配的插件" />
  <div class="cards">
    <article v-for="entry in entries" :key="entry.name" class="plugin-card" :class="{ off: !entry.compatible && !entry.installed }">
      <div class="inline"><h3>{{ entry.title }}</h3><v-chip :color="state(entry)[1]" class="ml-auto">{{ state(entry)[0] }}</v-chip></div>
      <p>{{ entry.description }}</p>
      <p class="muted small">{{ entry.authors.join('、') }} · v{{ entry.version }} · {{ entry.license }}<template v-if="entry.category"> · {{ entry.category }}</template></p>
      <p v-if="entry.update_available" class="note warn small">已装 v{{ entry.installed_version }}，目录里有 v{{ entry.version }}</p>
      <p v-else-if="!entry.compatible" class="note bad small">{{ entry.incompatible_reason }}</p>
      <div class="inline"><v-chip v-for="capability in entry.capabilities" :key="capability" variant="outlined">{{ capability }}</v-chip></div>
      <div class="inline actions">
        <v-btn size="small" variant="text" @click="selected = entry">详情与用法</v-btn>
        <template v-if="entry.installed">
          <v-btn size="small" variant="outlined" @click="configure(entry.name)">去配置</v-btn>
          <v-btn v-if="entry.update_available && manifest(entry.name)?.managed" size="small" color="primary" variant="flat" :disabled="busy" @click="update(entry)">更新到 v{{ entry.version }}</v-btn>
        </template>
        <v-btn v-else size="small" :variant="entry.compatible ? 'flat' : 'outlined'" :color="entry.compatible ? 'primary' : undefined" :disabled="busy || !entry.compatible" @click="install(entry)">一键安装</v-btn>
      </div>
    </article>
  </div>
  <FormDialog :model-value="selected !== null" :title="selected?.title || ''" size="md" cancel-label="关闭" @update:model-value="value => { if (!value) selected = null }">
    <template v-if="selected">
      <p>{{ selected.description }}</p>
      <ol class="usage"><li v-for="item in selected.usage" :key="item">{{ item }}</li></ol>
      <p>{{ selected.capabilities.join(' · ') }}</p>
      <p class="muted small">{{ selected.name }} · v{{ selected.version }} · 接口 {{ selected.interface }} · {{ selected.license }}<template v-if="selected.ref"> · 版本 {{ selected.ref }}</template></p>
      <p v-if="selected.requires_lenbot">宿主兼容范围：{{ selected.requires_lenbot }}<template v-if="!selected.compatible">（{{ selected.incompatible_reason }}）</template></p>
      <p v-if="selected.installed">本机已装 v{{ selected.installed_version || '未知' }}<template v-if="selected.update_available">，可以更新到 v{{ selected.version }}</template>。</p>
      <p>安装后填写参数，再选择在哪些群使用。</p>
      <div class="inline"><a v-if="selected.repository" :href="selected.repository" target="_blank" rel="noopener noreferrer">源码仓库</a><a v-if="selected.homepage" :href="selected.homepage" target="_blank" rel="noopener noreferrer">项目说明</a></div>
    </template>
    <template v-if="selected" #actions>
      <v-btn v-if="selected.installed" color="primary" @click="configure(selected.name)">去配置</v-btn>
      <v-btn v-else color="primary" :disabled="busy || !selected.compatible" @click="install(selected)">一键安装</v-btn>
    </template>
  </FormDialog>
</template>

<style scoped>
.filters{display:grid;grid-template-columns:2fr 1fr;gap:var(--sp-3)}
.start{justify-self:start}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:var(--sp-4)}
.plugin-card{border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);padding:var(--sp-4);display:grid;gap:var(--sp-2);align-content:start}
.plugin-card p{margin:0;overflow-wrap:anywhere}
.actions{margin-top:auto;padding-top:var(--sp-2)}
.plugin-card.off{opacity:.72}
.note{padding:2px var(--sp-2);border-radius:var(--radius);justify-self:start}
.note.warn{background:var(--warning-bg);color:var(--warning)}
.note.bad{background:var(--error-bg);color:var(--error)}
.usage{padding-left:var(--sp-5);margin:0;display:grid;gap:var(--sp-2)}
@media(max-width:700px){.filters{grid-template-columns:1fr}}
</style>
