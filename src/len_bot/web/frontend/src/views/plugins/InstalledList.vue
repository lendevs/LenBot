<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Blocks, ChevronDown, FileArchive, FolderCog, GitBranch, Plus, Search, Store, Trash2 } from '@lucide/vue'
import { pluginsApi, type PluginsSnapshot } from '../../api/plugins'
import Button from '../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../ui/DropdownMenu.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Input from '../../ui/Input.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import { confirm } from '../../ui/confirm'
import type { InstallRequest } from './InstallDialog.vue'
import PathsDialog from './PathsDialog.vue'
import PluginCard from './PluginCard.vue'
import { usePluginsState } from './state'
import { bucketOf, descriptionOf, manifestOf, pluginNames, statusOf, type Bucket } from './view'

const props = defineProps<{ snapshot: PluginsSnapshot }>()
const emit = defineEmits<{ open: [name: string]; install: [request: InstallRequest]; discover: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const names = computed(() => pluginNames(props.snapshot))
const running = computed(() => props.snapshot.running.plugins.filter((item) => item.status === 'running').length)
const bucket = (name: string) => bucketOf(statusOf(props.snapshot, name, state.healthOf(name)))

type Filter = 'all' | Bucket
const filter = ref<Filter>('all')
const filters = computed(() => {
  const counts: Record<Filter, number> = { all: names.value.length, on: 0, attention: 0, disabled: 0, idle: 0 }
  for (const name of names.value) counts[bucket(name)]++
  return (['all', 'on', 'attention', 'disabled', 'idle'] as const)
    .filter((key) => key === 'all' || counts[key])
    .map((key) => ({ value: key, label: `${t(`plugins.filters.${key}`)} ${counts[key]}` }))
})
watch(filters, (list) => {
  if (!list.some((item) => item.value === filter.value)) filter.value = 'all'
})
const query = ref('')
const shown = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return names.value.filter((name) => {
    if (filter.value !== 'all' && bucket(name) !== filter.value) return false
    const text = [name, descriptionOf(props.snapshot, name), ...(manifestOf(props.snapshot, name)?.authors ?? [])]
      .join(' ')
      .toLowerCase()
    return words.every((word) => text.includes(word))
  })
})

const menu = computed<MenuEntry[]>(() => [
  { label: t('plugins.install.fromCatalog'), icon: Store, select: () => emit('discover') },
  { label: t('plugins.install.gitTitle'), icon: GitBranch, select: () => emit('install', { kind: 'git' }) },
  { label: t('plugins.install.zipTitle'), icon: FileArchive, select: () => emit('install', { kind: 'zip' }) },
])
const editingPaths = ref(false)
const errors = computed(() => [...props.snapshot.discovery_errors, ...props.snapshot.running.discovery_errors])

async function removeData(name: string) {
  const sure = await confirm({
    title: t('plugins.removeData.title', { name }),
    message: t('plugins.removeData.message'),
    confirmLabel: t('plugins.removeData.confirm'),
    tone: 'danger',
  })
  if (sure) await state.run(name, () => pluginsApi.removeData(name), { success: t('plugins.removeData.done') })
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <Input
        v-if="names.length > 3"
        v-model="query"
        type="search"
        size="sm"
        :icon="Search"
        :placeholder="t('plugins.search')"
        :aria-label="t('plugins.search')"
        clearable
        class="w-full sm:w-64"
      />
      <span class="text-sm text-muted">
        {{ t('plugins.count', { n: names.length }, names.length) }}<template v-if="names.length">
          · {{ t('plugins.running', { n: running }) }}</template
        >
      </span>
      <div class="ml-auto flex items-center gap-2">
        <Button size="sm" variant="ghost" :icon="FolderCog" @click="editingPaths = true">{{ t('plugins.paths.title') }}</Button>
        <DropdownMenu :items="menu">
          <Button variant="primary" size="sm" :icon="Plus">
            {{ t('plugins.install.title') }}<ChevronDown :size="14" aria-hidden="true" />
          </Button>
        </DropdownMenu>
      </div>
    </div>
    <div v-if="filters.length > 2" class="overflow-x-auto scrollbar-thin">
      <SegmentedControl v-model="filter" :options="filters" size="sm" :label="t('plugins.filters.label')" />
    </div>

    <ErrorNote v-for="error in errors" :key="error" :title="t('plugins.discoveryFailed')" :error="error" />

    <EmptyState v-if="!names.length" :icon="Blocks" :title="t('plugins.empty')">
      <Button variant="primary" :icon="Store" @click="emit('discover')">{{ t('plugins.goDiscover') }}</Button>
    </EmptyState>
    <EmptyState v-else-if="!shown.length" :icon="Search" :title="t('common.noResults')" compact />
    <div v-else class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))] gap-4">
      <PluginCard v-for="name in shown" :key="name" :name="name" :snapshot="snapshot" @open="emit('open', name)" />
    </div>

    <section v-if="snapshot.retained_data.length" class="flex flex-col gap-2">
      <h2 class="text-base font-semibold">{{ t('plugins.retained') }}</h2>
      <ul class="flex list-none flex-col divide-y divide-line rounded-xl border border-line bg-surface px-4">
        <li v-for="item in snapshot.retained_data" :key="item.name" class="flex items-center gap-3 py-2.5">
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-ink">{{ item.name }}</p>
            <p class="truncate font-mono text-xs text-subtle">{{ item.directory }}</p>
          </div>
          <Button size="sm" variant="danger-ghost" :icon="Trash2" :loading="state.busy.value === item.name" @click="removeData(item.name)">
            {{ t('plugins.removeData.confirm') }}
          </Button>
        </li>
      </ul>
    </section>

    <PathsDialog
      v-if="editingPaths"
      :paths="snapshot.saved.paths"
      :data-directory="snapshot.saved.data_directory"
      @close="editingPaths = false"
    />
  </div>
</template>
