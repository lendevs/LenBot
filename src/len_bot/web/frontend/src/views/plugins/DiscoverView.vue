<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { refDebounced } from '@vueuse/core'
import { ArrowUpRight, RefreshCw, Search, Settings2, Store } from '@lucide/vue'
import { pluginsApi, type MarketEntry, type PluginsSnapshot } from '../../api/plugins'
import { keys } from '../../api/query'
import { formatDateTime } from '../../i18n/format'
import Avatar from '../../ui/Avatar.vue'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { toast } from '../../ui/toast'
import type { InstallRequest } from './InstallDialog.vue'
import { usePluginsState } from './state'
import { disabledIn, manifestOf, runningOf } from './view'

const props = defineProps<{ snapshot: PluginsSnapshot }>()
const emit = defineEmits<{ open: [name: string]; install: [request: InstallRequest] }>()

const { t } = useI18n()
const client = useQueryClient()
const state = usePluginsState()
const search = ref('')
const query = refDebounced(search, 250)
const ALL = '*'
const category = ref(ALL)
const catalog = useQuery({
  queryKey: keys.plugins.catalog(),
  queryFn: ({ signal }) => pluginsApi.catalog(signal),
})
const market = useQuery({
  queryKey: computed(() =>
    keys.plugins.market(query.value.trim(), category.value === ALL ? null : category.value),
  ),
  queryFn: ({ signal }) =>
    pluginsApi.market(query.value.trim(), category.value === ALL ? null : category.value, signal),
  placeholderData: keepPreviousData,
})
// Installing, removing or updating changes what the catalog marks as installed.
watch(
  () => props.snapshot,
  () => void client.invalidateQueries({ queryKey: [...keys.plugins.catalog(), 'market'] }),
)
const categories = computed(() => [
  { value: ALL, label: t('plugins.discover.allCategories') },
  ...(market.data.value?.categories ?? []).map((value) => ({ value, label: value })),
])
const entries = computed(() => market.data.value?.entries ?? [])

const refresh = useMutation({
  mutationFn: () => pluginsApi.refreshCatalog(),
  onSuccess: (view) => {
    client.setQueryData(keys.plugins.catalog(), view)
    void client.invalidateQueries({ queryKey: [...keys.plugins.catalog(), 'market'] })
  },
})
// A remote catalog is only read on request; opening this view is that request.
watch(
  () => catalog.data.value,
  (value, previous) => {
    if (value && !previous && !value.loaded_at) refresh.mutate()
  },
  { immediate: true },
)

function stateOf(entry: MarketEntry): { key: string; tone: 'neutral' | 'error' | 'success' | 'info' } | null {
  if (!entry.installed) return entry.compatible ? null : { key: 'incompatible', tone: 'error' }
  if (disabledIn(props.snapshot, entry.name)) return { key: 'disabled', tone: 'neutral' }
  const running = runningOf(props.snapshot, entry.name)
  if (running?.status === 'failed') return { key: 'failed', tone: 'error' }
  if (running?.status === 'running') return { key: 'running', tone: 'success' }
  return { key: entry.name in props.snapshot.saved.plugins ? 'configured' : 'installed', tone: 'info' }
}
const managed = (name: string) => Boolean(manifestOf(props.snapshot, name)?.managed)

const selected = ref<MarketEntry | null>(null)
const detailOpen = computed({
  get: () => selected.value !== null,
  set: (value: boolean) => {
    if (!value) selected.value = null
  },
})
async function install(entry: MarketEntry) {
  selected.value = null
  const result = await state.run('install', () => pluginsApi.installEntry(entry.name), {
    failure: t('plugins.install.failed'),
  })
  if (!result) return
  toast.success(
    result.operation?.needs_config ? t('plugins.install.readyConfigure') : t('plugins.install.ready'),
  )
  emit('open', entry.name)
}
function configure(entry: MarketEntry) {
  selected.value = null
  emit('open', entry.name)
}
function update(entry: MarketEntry) {
  selected.value = null
  emit('install', { kind: 'update', name: entry.name, ref: entry.ref })
}
const permissionText = (entry: MarketEntry) => {
  if (entry.permissions === undefined) return ''
  if (entry.permissions === null) return t('plugins.permissions.undeclared')
  if (!entry.permissions.length) return t('plugins.permissions.none')
  return t('plugins.permissions.needs', {
    list: entry.permissions
      .map((name) => t(`plugins.permissions.names.${name}`))
      .join(t('personas.separator')),
  })
}

const sourceOpen = ref(false)
const sourceUrl = ref('')
watch(sourceOpen, (value) => {
  if (value) sourceUrl.value = catalog.data.value?.url ?? ''
})
const setSource = useMutation({
  mutationFn: () => pluginsApi.setCatalog(sourceUrl.value.trim() || null),
  onSuccess: (view) => {
    client.setQueryData(keys.plugins.catalog(), view)
    sourceOpen.value = false
    refresh.mutate()
  },
})
const sourceDirty = computed(() => sourceUrl.value.trim() !== (catalog.data.value?.url ?? ''))
const readError = computed(() => market.error.value ?? catalog.error.value ?? refresh.error.value)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <Input
        v-model="search"
        type="search"
        size="sm"
        :icon="Search"
        :placeholder="t('plugins.discover.search')"
        :aria-label="t('plugins.discover.search')"
        clearable
        class="w-full sm:w-72"
      />
      <div class="w-full sm:w-44"><Select v-model="category" :options="categories" size="sm" /></div>
      <div class="ml-auto flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          :icon="RefreshCw"
          :loading="refresh.isPending.value"
          @click="refresh.mutate()"
        >
          {{ t('plugins.discover.refresh') }}
        </Button>
        <Button size="sm" variant="ghost" :icon="Settings2" @click="sourceOpen = true">
          {{ t('plugins.discover.source') }}
        </Button>
      </div>
    </div>
    <p v-if="catalog.data.value?.loaded_at" class="text-xs text-muted">
      {{
        t(`plugins.discover.loaded.${catalog.data.value.source}`, {
          time: formatDateTime(catalog.data.value.loaded_at),
          n: market.data.value?.total ?? 0,
        })
      }}
    </p>

    <ErrorNote
      v-if="readError"
      :title="t('plugins.discover.readFailed')"
      :error="readError"
      :retry="() => refresh.mutate()"
    />
    <Skeleton v-if="market.isPending.value || (refresh.isPending.value && !entries.length)" :lines="6" />
    <EmptyState
      v-else-if="market.data.value && !market.data.value.loaded_at"
      :icon="Store"
      :title="t('plugins.discover.notLoaded')"
      compact
    />
    <EmptyState v-else-if="!entries.length" :icon="Search" :title="t('common.noResults')" compact />
    <div v-else class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))] gap-4">
      <article
        v-for="entry in entries"
        :key="entry.name"
        class="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 shadow-card transition-[border-color,box-shadow] duration-150 hover:border-line-strong hover:shadow-hover"
        :class="!entry.compatible && !entry.installed && 'opacity-75'"
      >
        <div class="flex items-center gap-3">
          <Avatar :name="entry.name" shape="square" :size="40" />
          <div class="min-w-0 flex-1">
            <h3 class="truncate text-base font-semibold text-ink">{{ entry.title }}</h3>
            <p class="truncate text-xs text-subtle">
              {{ entry.authors.join(t('personas.separator')) }} · v{{ entry.version }}
            </p>
          </div>
          <Badge v-if="stateOf(entry)" :tone="stateOf(entry)!.tone" dot>
            {{ t(`plugins.discover.state.${stateOf(entry)!.key}`) }}
          </Badge>
        </div>
        <p class="line-clamp-3 text-sm text-muted">{{ entry.description }}</p>
        <p
          v-if="entry.update_available"
          class="self-start rounded-sm bg-warning-bg px-2 py-0.5 text-xs text-warning"
        >
          {{ t('plugins.discover.updatable', { now: entry.installed_version ?? '?', next: entry.version }) }}
        </p>
        <p
          v-else-if="!entry.compatible"
          class="self-start rounded-sm bg-error-bg px-2 py-0.5 text-xs text-error"
        >
          {{ entry.incompatible_reason }}
        </p>
        <div v-if="entry.capabilities.length" class="flex flex-wrap gap-1.5">
          <Badge v-for="item in entry.capabilities" :key="item">{{ item }}</Badge>
        </div>
        <div class="mt-auto flex items-center gap-1 border-t border-line pt-3">
          <Button size="sm" variant="ghost" class="-ml-2" @click="selected = entry">
            {{ t('plugins.discover.details') }}
          </Button>
          <Button
            v-if="entry.update_available && managed(entry.name)"
            size="sm"
            variant="ghost"
            :disabled="state.busy.value !== null"
            @click="update(entry)"
          >
            {{ t('plugins.discover.updateTo', { version: entry.version }) }}
          </Button>
          <Button v-if="entry.installed" size="sm" class="ml-auto" @click="configure(entry)">
            {{ t('plugins.discover.configure') }}
          </Button>
          <Button
            v-else
            size="sm"
            variant="primary"
            class="ml-auto"
            :disabled="state.busy.value !== null || !entry.compatible"
            :loading="state.busy.value === 'install'"
            @click="install(entry)"
          >
            {{ t('plugins.discover.install') }}
          </Button>
        </div>
      </article>
    </div>

    <Dialog v-model:open="detailOpen" :title="selected?.title ?? ''" size="md">
      <div v-if="selected" class="flex flex-col gap-4">
        <p class="text-sm text-ink-2">{{ selected.description }}</p>
        <section v-if="selected.usage.length" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold">{{ t('plugins.discover.usage') }}</h3>
          <ol class="flex list-decimal flex-col gap-1 pl-5 text-sm text-ink-2">
            <li v-for="item in selected.usage" :key="item">{{ item }}</li>
          </ol>
        </section>
        <div v-if="selected.capabilities.length" class="flex flex-wrap gap-1.5">
          <Badge v-for="item in selected.capabilities" :key="item">{{ item }}</Badge>
        </div>
        <p
          v-if="permissionText(selected)"
          class="text-sm"
          :class="selected.permissions === null ? 'text-warning' : 'text-muted'"
        >
          {{ permissionText(selected) }}
        </p>
        <dl class="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
          <dt class="text-muted">{{ t('plugins.discover.name') }}</dt>
          <dd class="font-mono">{{ selected.name }}</dd>
          <dt class="text-muted">{{ t('plugins.discover.version') }}</dt>
          <dd>
            v{{ selected.version }}
            <template v-if="selected.ref">
              ·
              <span class="font-mono">{{ selected.ref }}</span>
            </template>
          </dd>
          <dt class="text-muted">{{ t('plugins.discover.license') }}</dt>
          <dd>{{ selected.license }}</dd>
          <template v-if="selected.requires_lenbot">
            <dt class="text-muted">{{ t('plugins.discover.host') }}</dt>
            <dd class="font-mono">{{ selected.requires_lenbot }}</dd>
          </template>
          <template v-if="selected.installed">
            <dt class="text-muted">{{ t('plugins.discover.here') }}</dt>
            <dd>v{{ selected.installed_version ?? '?' }}</dd>
          </template>
        </dl>
        <p v-if="!selected.compatible" class="rounded-md bg-error-bg px-3 py-2 text-sm text-error">
          {{ selected.incompatible_reason }}
        </p>
        <p class="flex flex-wrap gap-4 text-sm">
          <a
            :href="selected.repository"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            {{ t('plugins.detail.repository') }}
            <ArrowUpRight :size="13" aria-hidden="true" />
          </a>
          <a
            v-if="selected.homepage"
            :href="selected.homepage"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            {{ t('plugins.detail.homepage') }}
            <ArrowUpRight :size="13" aria-hidden="true" />
          </a>
        </p>
      </div>
      <template v-if="selected" #footer>
        <Button variant="ghost" @click="selected = null">{{ t('common.close') }}</Button>
        <Button v-if="selected.installed" variant="primary" @click="configure(selected)">
          {{ t('plugins.discover.configure') }}
        </Button>
        <Button
          v-else
          variant="primary"
          :disabled="state.busy.value !== null || !selected.compatible"
          @click="install(selected)"
        >
          {{ t('plugins.discover.install') }}
        </Button>
      </template>
    </Dialog>

    <Dialog
      v-model:open="sourceOpen"
      :title="t('plugins.discover.source')"
      size="sm"
      :busy="setSource.isPending.value"
    >
      <form
        id="catalog-source"
        class="flex flex-col gap-4"
        @submit.prevent="sourceDirty && setSource.mutate()"
      >
        <Field :label="t('plugins.discover.sourceUrl')">
          <Input v-model="sourceUrl" type="url" mono :placeholder="t('plugins.discover.sourceBuiltin')" />
        </Field>
        <ErrorNote
          v-if="setSource.isError.value"
          :title="t('plugins.discover.sourceFailed')"
          :error="setSource.error.value"
        />
      </form>
      <template #footer>
        <Button variant="ghost" :disabled="setSource.isPending.value" @click="sourceOpen = false">
          {{ t('common.cancel') }}
        </Button>
        <Button
          variant="primary"
          type="submit"
          form="catalog-source"
          :loading="setSource.isPending.value"
          :disabled="!sourceDirty"
        >
          {{ t('plugins.discover.sourceSave') }}
        </Button>
      </template>
    </Dialog>
  </div>
</template>
