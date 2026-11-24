<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { refDebounced } from '@vueuse/core'
import { ArrowUpRight, RefreshCw, Search, Settings2 } from '@lucide/vue'
import { pluginsApi, type CatalogSourceKind, type MarketEntry, type PluginsSnapshot } from '../../api/plugins'
import { keys } from '../../api/query'
import { formatDateTime } from '../../i18n/format'
import Avatar from '../../ui/Avatar.vue'
import Badge, { type Tone } from '../../ui/Badge.vue'
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
import type { OpenOptions } from './PluginsView.vue'
import { usePluginsState } from './state'
import { disabledIn, enabledIn, manifestOf, runningOf } from './view'

const props = defineProps<{ snapshot: PluginsSnapshot }>()
const emit = defineEmits<{
  open: [name: string, options?: OpenOptions]
  install: [request: InstallRequest]
}>()

const { t, te } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const state = usePluginsState()

const ALL = '*'
const readQuery = (value: unknown) => (typeof value === 'string' ? value : '')
const search = ref(readQuery(route.query.q))
const query = refDebounced(search, 250)
const category = ref(readQuery(route.query.cat) || ALL)
const source = ref<CatalogSourceKind | typeof ALL>(ALL)

const catalog = useQuery({
  queryKey: keys.plugins.catalog(),
  queryFn: ({ signal }) => pluginsApi.catalog(signal),
})
const chosenCategory = computed(() => (category.value === ALL ? null : category.value))
const chosenSource = computed(() => (source.value === ALL ? null : source.value))
const market = useQuery({
  queryKey: computed(() => keys.plugins.market(query.value.trim(), chosenCategory.value, chosenSource.value)),
  queryFn: ({ signal }) =>
    pluginsApi.market(query.value.trim(), chosenCategory.value, chosenSource.value, signal),
  placeholderData: keepPreviousData,
})

// Keep search and category filters reflected in the URL so detail back-navigation restores them.
watch([query, category], ([nextQ, nextCat]) => {
  if (route.query.item || route.query.view !== 'discover') return
  const q = nextQ.trim()
  const cat = nextCat === ALL ? '' : nextCat
  if (q === readQuery(route.query.q).trim() && cat === readQuery(route.query.cat)) return
  const nextQuery: LocationQueryRaw = { view: 'discover' }
  if (q) nextQuery.q = q
  if (cat) nextQuery.cat = cat
  void router.replace({ query: nextQuery })
})
watch(
  () => [readQuery(route.query.q), readQuery(route.query.cat)] as const,
  ([urlQ, urlCat]) => {
    if (route.query.item || route.query.view !== 'discover') return
    if (urlQ !== search.value) search.value = urlQ
    const nextCat = urlCat || ALL
    if (nextCat !== category.value) category.value = nextCat
  },
)

// Installing, removing or updating changes what the catalog marks as installed.
watch(
  () => props.snapshot,
  () => void client.invalidateQueries({ queryKey: [...keys.plugins.catalog(), 'market'] }),
)
const categories = computed(() => {
  const list = market.data.value?.categories ?? []
  const extra = category.value !== ALL && !list.includes(category.value) ? [category.value] : []
  return [
    { value: ALL, label: t('plugins.discover.allCategories') },
    ...[...list, ...extra].map((value) => ({ value, label: value })),
  ]
})
const entries = computed(() => market.data.value?.entries ?? [])
const sources = computed(() => market.data.value?.sources ?? catalog.data.value?.sources ?? [])
const sourceOptions = computed(() => [
  { value: ALL, label: t('plugins.discover.allSources') },
  ...sources.value.map((item) => ({ value: item.kind, label: t(`plugins.discover.sources.${item.kind}`) })),
])
const sourceTone = { official: 'info', community: 'neutral', custom: 'neutral' } as const
const loadedText = computed(() => {
  const loaded = sources.value.filter((item) => item.loaded_at !== null)
  if (!loaded.length) return ''
  const counts = loaded
    .map((item) =>
      t('plugins.discover.sourceCount', { name: t(`plugins.discover.sources.${item.kind}`), n: item.total }),
    )
    .join(' · ')
  const time = Math.max(...loaded.map((item) => item.loaded_at!))
  return t('plugins.discover.loaded', { counts, time: formatDateTime(time) })
})
const failedSources = computed(() => sources.value.filter((item) => item.error))

const refresh = useMutation({
  mutationFn: () => pluginsApi.refreshCatalog(),
  onSuccess: (view) => {
    client.setQueryData(keys.plugins.catalog(), view)
    void client.invalidateQueries({ queryKey: [...keys.plugins.catalog(), 'market'] })
  },
})
// Remote catalogs are only read on request; opening this view is that request.
watch(
  () => catalog.data.value,
  (value, previous) => {
    if (value && !previous && value.sources.some((item) => item.loaded_at === null && !item.error))
      refresh.mutate()
  },
  { immediate: true },
)

const stagedCandidate = (name: string) => manifestOf(props.snapshot, name)?.source?.candidate ?? null
const installedOrStaged = (entry: MarketEntry) =>
  entry.installed || Boolean(stagedCandidate(entry.name)) || entry.name in props.snapshot.available
const needsEnable = (entry: MarketEntry) =>
  Boolean(stagedCandidate(entry.name)) || !enabledIn(props.snapshot, entry.name)
const isInstalling = (name: string) => state.isBusy(`install:${name}`)

function stateOf(entry: MarketEntry): { key: string; tone: Tone } | null {
  const candidate = stagedCandidate(entry.name)
  if (!entry.installed && !candidate && !(entry.name in props.snapshot.available)) {
    return entry.compatible ? null : { key: 'incompatible', tone: 'error' }
  }
  if (candidate) return { key: 'candidate', tone: 'info' }
  if (disabledIn(props.snapshot, entry.name)) return { key: 'disabled', tone: 'neutral' }
  const running = runningOf(props.snapshot, entry.name)
  if (running?.status === 'failed') return { key: 'failed', tone: 'error' }
  if (running?.status === 'running') return { key: 'running', tone: 'success' }
  return { key: entry.name in props.snapshot.saved.plugins ? 'configured' : 'installed', tone: 'info' }
}
// Only Git installs can update in place; a ZIP install takes its next ZIP through import.
const updatable = (name: string) => manifestOf(props.snapshot, name)?.source?.installed?.kind === 'git'

const selectedEntry = ref<MarketEntry | null>(null)
const selected = computed<MarketEntry | null>(() => {
  if (!selectedEntry.value) return null
  return entries.value.find((item) => item.name === selectedEntry.value!.name) ?? selectedEntry.value
})
const selectedInstalling = computed(() => Boolean(selected.value && isInstalling(selected.value.name)))
const detailOpen = computed({
  get: () => selectedEntry.value !== null,
  set: (value: boolean) => {
    if (!value && !selectedInstalling.value) selectedEntry.value = null
  },
})

async function install(entry: MarketEntry) {
  const result = await state.run(`install:${entry.name}`, () => pluginsApi.installEntry(entry.name), {
    failure: t('plugins.install.failed'),
  })
  if (!result) return
  toast.success(
    result.operation?.needs_config ? t('plugins.install.readyConfigure') : t('plugins.install.ready'),
  )
}
function configure(entry: MarketEntry) {
  selectedEntry.value = null
  emit('open', entry.name, { q: search.value.trim(), cat: chosenCategory.value })
}
function update(entry: MarketEntry) {
  selectedEntry.value = null
  emit('install', { kind: 'update', name: entry.name, ref: entry.ref })
}

const platformLabel = (platform: string) =>
  te(`plugins.chatPlatforms.${platform}`) ? t(`plugins.chatPlatforms.${platform}`) : platform
const permissionLabel = (name: string) =>
  te(`plugins.permissions.names.${name}`) ? t(`plugins.permissions.names.${name}`) : name

// The server normalizes ">=0.2,<1" to "<1,>=0.2"; lower bounds read first.
const hostRange = (value: string) =>
  value
    .split(',')
    .sort((a, b) => Number(b.startsWith('>')) - Number(a.startsWith('>')))
    .join(', ')

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
// A source left without a custom URL disappears from the filter; fall back to every source.
watch(sources, (value) => {
  if (source.value !== ALL && !value.some((item) => item.kind === source.value)) source.value = ALL
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <div class="w-full sm:w-72">
        <Input
          v-model="search"
          type="search"
          size="sm"
          :icon="Search"
          :placeholder="t('plugins.discover.search')"
          :aria-label="t('plugins.discover.search')"
          clearable
        />
      </div>
      <div class="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto">
        <div class="min-w-0 sm:w-36"><Select v-model="source" :options="sourceOptions" size="sm" /></div>
        <div class="min-w-0 sm:w-40"><Select v-model="category" :options="categories" size="sm" /></div>
      </div>
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
          {{ t('plugins.discover.custom') }}
        </Button>
      </div>
    </div>
    <p v-if="loadedText" class="text-xs text-muted tabular">{{ loadedText }}</p>

    <ErrorNote
      v-if="readError"
      :title="t('plugins.discover.readFailed')"
      :error="readError"
      :retry="() => refresh.mutate()"
    />
    <ErrorNote
      v-for="item in failedSources"
      :key="item.kind"
      :title="t('plugins.discover.sourceReadFailed', { name: t(`plugins.discover.sources.${item.kind}`) })"
      :error="item.error"
      :retry="() => refresh.mutate()"
    />
    <Skeleton v-if="market.isPending.value || (refresh.isPending.value && !entries.length)" :lines="6" />
    <EmptyState v-else-if="!entries.length" :icon="Search" :title="t('common.noResults')" compact />
    <div v-else class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-4">
      <article
        v-for="entry in entries"
        :key="entry.name"
        class="relative flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 shadow-card transition-[border-color,box-shadow] duration-150 hover:border-line-strong hover:shadow-hover"
        :class="!entry.compatible && !installedOrStaged(entry) && 'opacity-75'"
      >
        <div class="flex items-start gap-3">
          <Avatar :name="entry.name" shape="square" :size="40" />
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-2">
              <h3 class="min-w-0 truncate text-base font-semibold">
                <button
                  type="button"
                  class="block max-w-full cursor-pointer truncate text-left text-ink after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:focus-ring"
                  @click="selectedEntry = entry"
                >
                  {{ entry.title }}
                </button>
              </h3>
              <Badge :tone="sourceTone[entry.source]">
                {{ t(`plugins.discover.sources.${entry.source}`) }}
              </Badge>
            </div>
            <p class="mt-0.5 flex items-center gap-1.5 truncate text-xs text-subtle tabular">
              <span class="truncate font-mono">{{ entry.name }}</span>
              <span aria-hidden="true">·</span>
              <span class="shrink-0">v{{ entry.version }}</span>
              <template v-if="entry.authors.length">
                <span aria-hidden="true">·</span>
                <span class="truncate">{{ entry.authors.join(t('personas.separator')) }}</span>
              </template>
            </p>
          </div>
          <Badge v-if="stateOf(entry)" :tone="stateOf(entry)!.tone" dot>
            {{ t(`plugins.discover.state.${stateOf(entry)!.key}`) }}
          </Badge>
        </div>
        <p class="line-clamp-3 text-sm text-muted">{{ entry.description }}</p>
        <p
          v-if="entry.update_available && !stagedCandidate(entry.name)"
          class="self-start rounded-sm bg-warning-bg px-2 py-0.5 text-xs text-warning tabular"
        >
          {{ t('plugins.discover.updatable', { now: entry.installed_version ?? '?', next: entry.version }) }}
        </p>
        <p
          v-else-if="!entry.compatible && !installedOrStaged(entry)"
          class="self-start rounded-sm bg-error-bg px-2 py-0.5 text-xs text-error"
        >
          {{ entry.incompatible_reason }}
        </p>
        <div
          v-if="entry.category || entry.chat_platforms?.length || entry.capabilities.length"
          class="flex flex-wrap gap-1.5"
        >
          <Badge v-if="entry.category" tone="brand">{{ entry.category }}</Badge>
          <Badge v-for="platform in entry.chat_platforms ?? []" :key="`p:${platform}`" tone="brand">
            {{ platformLabel(platform) }}
          </Badge>
          <Badge v-for="item in entry.capabilities.slice(0, 3)" :key="item">{{ item }}</Badge>
          <Badge v-if="entry.capabilities.length > 3" class="tabular">
            +{{ entry.capabilities.length - 3 }}
          </Badge>
        </div>
        <div
          class="relative z-10 mt-auto flex items-center justify-between gap-2 border-t border-line pt-3"
          @click.stop
        >
          <div class="-ml-2 flex flex-wrap items-center gap-1">
            <Button size="sm" variant="ghost" @click.stop="selectedEntry = entry">
              {{ t('plugins.discover.details') }}
            </Button>
            <Button
              v-if="entry.update_available && updatable(entry.name) && !stagedCandidate(entry.name)"
              size="sm"
              variant="ghost"
              :disabled="state.pluginBusy(entry.name)"
              @click.stop="update(entry)"
            >
              {{ t('plugins.discover.updateTo', { version: entry.version }) }}
            </Button>
          </div>
          <Button
            v-if="installedOrStaged(entry)"
            size="sm"
            :variant="needsEnable(entry) ? 'primary' : 'secondary'"
            @click.stop="configure(entry)"
          >
            {{ needsEnable(entry) ? t('plugins.discover.configureEnable') : t('plugins.discover.configure') }}
          </Button>
          <Button
            v-else
            size="sm"
            variant="primary"
            :disabled="!entry.compatible || (state.pluginBusy(entry.name) && !isInstalling(entry.name))"
            :loading="isInstalling(entry.name)"
            @click.stop="install(entry)"
          >
            {{ t('plugins.discover.install') }}
          </Button>
        </div>
      </article>
    </div>

    <Dialog v-model:open="detailOpen" :title="selected?.title ?? ''" size="md" :busy="selectedInstalling">
      <div v-if="selected" class="flex flex-col gap-4">
        <p class="text-sm text-ink-2">{{ selected.description }}</p>
        <section v-if="selected.usage.length" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-ink">{{ t('plugins.discover.usage') }}</h3>
          <ol class="flex list-decimal flex-col gap-1 pl-5 text-sm text-ink-2">
            <li v-for="item in selected.usage" :key="item">{{ item }}</li>
          </ol>
        </section>
        <section v-if="selected.capabilities.length" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-ink">{{ t('plugins.discover.capabilities') }}</h3>
          <div class="flex flex-wrap gap-1.5">
            <Badge v-for="item in selected.capabilities" :key="item">{{ item }}</Badge>
          </div>
        </section>
        <section v-if="selected.permissions !== undefined" class="flex flex-col gap-1.5">
          <h3 class="text-sm font-semibold text-ink">{{ t('plugins.permissions.title') }}</h3>
          <p v-if="selected.permissions === null" class="text-sm text-warning">
            {{ t('plugins.permissions.undeclared') }}
          </p>
          <p v-else-if="!selected.permissions.length" class="text-sm text-muted">
            {{ t('plugins.permissions.none') }}
          </p>
          <ul v-else class="flex list-disc flex-col gap-1 pl-5 text-sm text-ink-2">
            <li v-for="perm in selected.permissions" :key="perm">{{ permissionLabel(perm) }}</li>
          </ul>
        </section>
        <dl
          class="grid gap-x-6 gap-y-2 border-y border-line py-3 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]"
        >
          <dt class="text-muted">{{ t('plugins.discover.name') }}</dt>
          <dd class="font-mono break-all text-ink">{{ selected.name }}</dd>
          <template v-if="selected.category">
            <dt class="text-muted">{{ t('plugins.discover.category') }}</dt>
            <dd class="text-ink">{{ selected.category }}</dd>
          </template>
          <dt class="text-muted">{{ t('plugins.discover.source') }}</dt>
          <dd class="text-ink">{{ t(`plugins.discover.sources.${selected.source}`) }}</dd>
          <template v-if="selected.authors.length">
            <dt class="text-muted">{{ t('plugins.discover.authors') }}</dt>
            <dd class="text-ink">{{ selected.authors.join(t('personas.separator')) }}</dd>
          </template>
          <dt class="text-muted">{{ t('plugins.discover.version') }}</dt>
          <dd class="text-ink tabular">
            v{{ selected.version }}
            <template v-if="selected.ref">
              ·
              <span class="font-mono" :title="selected.ref">{{ selected.ref.slice(0, 7) }}</span>
            </template>
          </dd>
          <dt class="text-muted">{{ t('plugins.discover.license') }}</dt>
          <dd class="text-ink">{{ selected.license }}</dd>
          <template v-if="selected.requires_lenbot">
            <dt class="text-muted">{{ t('plugins.discover.host') }}</dt>
            <dd class="font-mono text-ink tabular">{{ hostRange(selected.requires_lenbot) }}</dd>
          </template>
          <template v-if="selected.chat_platforms?.length">
            <dt class="text-muted">{{ t('plugins.version.chatPlatforms') }}</dt>
            <dd class="text-ink">
              {{ selected.chat_platforms.map(platformLabel).join(t('personas.separator')) }}
            </dd>
          </template>
          <template v-if="selected.installed || stagedCandidate(selected.name)">
            <dt class="text-muted">{{ t('plugins.discover.here') }}</dt>
            <dd class="text-ink tabular">
              <template v-if="selected.installed">v{{ selected.installed_version ?? '?' }}</template>
              <template v-if="stagedCandidate(selected.name)">
                {{ selected.installed ? ' · ' : ''
                }}{{ t('plugins.card.candidate', { version: stagedCandidate(selected.name)!.version }) }}
              </template>
            </dd>
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
        <Button variant="ghost" :disabled="selectedInstalling" @click="selectedEntry = null">
          {{ t('common.close') }}
        </Button>
        <Button
          v-if="selected.update_available && updatable(selected.name) && !stagedCandidate(selected.name)"
          variant="secondary"
          :disabled="state.pluginBusy(selected.name)"
          @click="update(selected)"
        >
          {{ t('plugins.discover.updateTo', { version: selected.version }) }}
        </Button>
        <Button v-if="installedOrStaged(selected)" variant="primary" @click="configure(selected)">
          {{
            needsEnable(selected) ? t('plugins.discover.configureEnable') : t('plugins.discover.configure')
          }}
        </Button>
        <Button
          v-else
          variant="primary"
          :disabled="!selected.compatible || (state.pluginBusy(selected.name) && !selectedInstalling)"
          :loading="selectedInstalling"
          @click="install(selected)"
        >
          {{ t('plugins.discover.install') }}
        </Button>
      </template>
    </Dialog>

    <Dialog
      v-model:open="sourceOpen"
      :title="t('plugins.discover.custom')"
      size="sm"
      :busy="setSource.isPending.value"
    >
      <form
        id="catalog-source"
        class="flex flex-col gap-4"
        @submit.prevent="sourceDirty && setSource.mutate()"
      >
        <Field :label="t('plugins.discover.sourceUrl')">
          <Input v-model="sourceUrl" type="url" mono placeholder="https://example.com/catalog.json" />
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
