<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { useDocumentVisibility, watchDebounced } from '@vueuse/core'
import { ArrowUpRight, Download, FileText, RefreshCw, ScrollText, Search, X } from '@lucide/vue'
import { logsApi, type LogFilter, type LogRecord } from '../../../api/logs'
import { keys } from '../../../api/query'
import { timelineApi } from '../../../api/timeline'
import { host } from '../../../api/hostStore'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import VirtualList from '../../../ui/VirtualList.vue'
import TurnSteps from '../../groups/live/TurnSteps.vue'
import { groupsTarget } from '../../groups/route'
import LogRow from './LogRow.vue'
import { useLogLabels } from './labels'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const labels = useLogLabels()
const text = (key: string) => (typeof route.query[key] === 'string' ? (route.query[key] as string) : '')
function setQuery(change: LocationQueryRaw) {
  const next: LocationQueryRaw = { ...route.query, ...change }
  for (const [key, value] of Object.entries(next)) if (value === '' || value === null) delete next[key]
  void router.replace({ query: next })
}

const ALL = 'all'
const level = computed({
  get: () => (['WARNING', 'ERROR'].includes(text('level')) ? text('level') : ALL),
  set: (value: string) => setQuery({ level: value === ALL ? undefined : value }),
})
const levels = computed(() => [
  { value: ALL, label: t('logs.levels.all') },
  { value: 'WARNING', label: t('logs.levels.warning') },
  { value: 'ERROR', label: t('logs.levels.error') },
])
const scenes = computed<string[]>(() => (host.state?.scenes ?? []).map((item: { scene: string }) => item.scene))
const scene = computed({
  get: () => text('scene') || ALL,
  set: (value: string) => setQuery({ scene: value === ALL ? undefined : value }),
})
const sceneOptions = computed(() => [
  { value: ALL, label: t('logs.allGroups') },
  ...[...new Set([...scenes.value, ...(text('scene') ? [text('scene')] : [])])].map((value) => ({ value, label: groupLabel(value) })),
])
/** Logger names seen so far, so the source filter offers what the log actually contains. */
const seenSources = ref(new Set<string>())
const source = computed({
  get: () => text('source') || ALL,
  set: (value: string) => setQuery({ source: value === ALL ? undefined : value }),
})
const sourceOptions = computed(() => [
  { value: ALL, label: t('logs.allSources') },
  ...[...new Set([...seenSources.value, ...(text('source') ? [text('source')] : [])])].sort().map((value) => ({ value, label: value })),
])
// Typed filters reach the address after a pause, so each keystroke does not read the log files again.
const plugin = ref(text('plugin'))
const task = ref(text('task'))
const search = ref(text('q'))
watchDebounced([plugin, task, search], ([p, k, q]) => setQuery({ plugin: p.trim(), task: k.trim(), q: q.trim() }), { debounce: 400 })
watch(
  () => [text('plugin'), text('task'), text('q')],
  ([p, k, q]) => {
    if (p !== plugin.value.trim()) plugin.value = p!
    if (k !== task.value.trim()) task.value = k!
    if (q !== search.value.trim()) search.value = q!
  },
)
const turn = computed(() => text('turn'))
const kind = computed(() => text('event'))

const LIMITS = [300, 1000, 2000]
const limit = ref(LIMITS[0]!)
const filter = computed<LogFilter>(() => ({
  limit: limit.value,
  ...(level.value !== ALL ? { level: level.value as LogFilter['level'] } : {}),
  ...(scene.value !== ALL ? { scene: scene.value } : {}),
  ...(source.value !== ALL ? { source: source.value } : {}),
  ...(text('plugin') ? { plugin: text('plugin') } : {}),
  ...(text('task') ? { task_id: text('task') } : {}),
  ...(turn.value ? { turn_id: turn.value } : {}),
}))
watch(
  () => JSON.stringify({ ...filter.value, limit: 0 }),
  () => (limit.value = LIMITS[0]!),
)
const follow = ref(false)
const visible = useDocumentVisibility()
const logs = useQuery({
  queryKey: computed(() => keys.system.logs(filter.value)),
  queryFn: ({ signal }) => logsApi.read(filter.value, signal),
  placeholderData: (previous) => previous,
  refetchInterval: computed(() => (follow.value && visible.value === 'visible' ? 4000 : false)),
})
const items = computed(() => logs.data.value?.items ?? [])
watch(items, (list) => {
  const next = new Set(seenSources.value)
  for (const item of list) next.add(item.source)
  if (next.size !== seenSources.value.size) seenSources.value = next
})

const eventKey = (item: LogRecord) => item.event ?? '_other'
const kinds = computed(() => {
  const counts = new Map<string, number>()
  for (const item of items.value) counts.set(eventKey(item), (counts.get(eventKey(item)) ?? 0) + 1)
  return [...counts].sort((a, b) => b[1] - a[1])
})
const haystack = (item: LogRecord) =>
  [item.event, item.event && labels.event(item.event), item.message, item.source, item.scene, item.plugin, item.tool, item.task_id, item.turn_id, item.error?.type, item.error?.message]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
const shown = computed(() => {
  const words = text('q').toLowerCase().split(/\s+/).filter(Boolean)
  return items.value.filter(
    (item) => (!kind.value || eventKey(item) === kind.value) && (!words.length || words.every((word) => haystack(item).includes(word))),
  )
})
const keyed = computed(() => shown.value.map((item, index) => ({ item, key: `${item.ts}#${index}` })))
const more = computed(() => items.value.length >= limit.value && limit.value < LIMITS[LIMITS.length - 1]!)
const timeZone = computed(() => host.state?.timezone as string | undefined)

function onFilter(key: 'turn' | 'plugin' | 'task' | 'scene', value: string) {
  if (key === 'plugin') plugin.value = value
  if (key === 'task') task.value = String(value)
  setQuery({ [key]: value })
}

const detail = useQuery({
  queryKey: computed(() => keys.scene.turn(scene.value, turn.value)),
  queryFn: ({ signal }) => timelineApi.turn(scene.value, turn.value, signal),
  enabled: computed(() => Boolean(turn.value) && scene.value !== ALL),
})

const files = useQuery({ queryKey: keys.system.logFiles(), queryFn: ({ signal }) => logsApi.files(signal) })
const size = (bytes: number) => `${Math.max(1, Math.ceil(bytes / 1024))} KB`

function exportShown() {
  const blob = new Blob([shown.value.map((item) => JSON.stringify(item)).join('\n') + '\n'], { type: 'application/x-ndjson' })
  const link = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob),
    download: `lenbot-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.jsonl`,
  })
  link.click()
  setTimeout(() => URL.revokeObjectURL(link.href), 1000)
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <section class="flex min-w-0 flex-col gap-4 rounded-xl border border-line bg-surface p-4">
      <div class="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:items-end">
        <div class="col-span-2"><SegmentedControl v-model="level" :options="levels" :label="t('logs.level')" /></div>
        <Field :label="t('logs.group')" class="col-span-2 sm:w-48">
          <Select v-model="scene" :options="sceneOptions" />
        </Field>
        <Field :label="t('logs.source')" class="col-span-2 sm:w-64">
          <Select v-model="source" :options="sourceOptions" />
        </Field>
        <Field :label="t('logs.plugin')" class="sm:w-36">
          <Input v-model="plugin" mono clearable />
        </Field>
        <Field :label="t('logs.task')" class="sm:w-28">
          <Input v-model="task" mono clearable />
        </Field>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <Input v-model="search" :icon="Search" clearable :placeholder="t('logs.search')" class="min-w-0 flex-1 basis-60" :aria-label="t('logs.search')" />
        <Field :label="t('logs.follow')" inline>
          <Switch v-model="follow" />
        </Field>
        <Button size="sm" variant="ghost" :icon="RefreshCw" :loading="logs.isFetching.value && !follow" @click="logs.refetch()">{{ t('logs.refresh') }}</Button>
        <Button size="sm" variant="ghost" :icon="Download" :disabled="!shown.length" @click="exportShown">
          {{ t('logs.export', { n: shown.length }, shown.length) }}
        </Button>
      </div>
      <div v-if="turn" class="flex flex-wrap items-center gap-2">
        <Badge tone="brand">{{ t('logs.onlyTurn', { id: turn.slice(0, 8) }) }}</Badge>
        <Button size="sm" variant="ghost" :icon="X" @click="setQuery({ turn: undefined })">{{ t('logs.allTurns') }}</Button>
      </div>
      <div v-if="kinds.length > 1" class="flex flex-wrap gap-1.5" role="group" :aria-label="t('logs.kinds')">
        <button
          type="button"
          class="inline-flex h-7 cursor-pointer items-center gap-1 rounded-full border px-2.5 text-xs transition-colors focus-visible:focus-ring"
          :class="!kind ? 'border-primary bg-primary-bg text-primary' : 'border-line text-ink-2 hover:bg-hover'"
          :aria-pressed="!kind"
          @click="setQuery({ event: undefined })"
        >
          {{ t('logs.allKinds') }} <span class="tabular opacity-70">{{ items.length }}</span>
        </button>
        <button
          v-for="[key, count] in kinds"
          :key="key"
          type="button"
          class="inline-flex h-7 cursor-pointer items-center gap-1 rounded-full border px-2.5 text-xs transition-colors focus-visible:focus-ring"
          :class="kind === key ? 'border-primary bg-primary-bg text-primary' : 'border-line text-ink-2 hover:bg-hover'"
          :aria-pressed="kind === key"
          @click="setQuery({ event: kind === key ? undefined : key })"
        >
          {{ key === '_other' ? labels.event(undefined) : labels.event(key) }} <span class="tabular opacity-70">{{ count }}</span>
        </button>
      </div>
    </section>

    <section v-if="turn && scene !== ALL" class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-4">
      <header class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-base font-semibold">{{ t('logs.turnTitle') }}</h3>
        <Button size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="groupsTarget(scene, 'live')">{{ t('logs.openGroup') }}</Button>
      </header>
      <Skeleton v-if="detail.isPending.value" :lines="3" />
      <ErrorNote v-else-if="detail.isError.value" :title="t('logs.turnFailed')" :error="detail.error.value" :retry="detail.refetch" />
      <TurnSteps v-else-if="detail.data.value" :detail="detail.data.value" />
    </section>

    <Skeleton v-if="logs.isPending.value" :lines="8" />
    <ErrorNote v-else-if="logs.isError.value" :title="t('logs.readFailed')" :error="logs.error.value" :retry="logs.refetch" />
    <EmptyState v-else-if="!shown.length" :icon="ScrollText" :title="t('logs.empty')" compact />
    <div v-else class="flex min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <VirtualList :items="keyed" :get-key="(row) => row.key" :estimate-size="76" class="max-h-[min(70vh,720px)]">
        <template #default="{ item: row }">
          <LogRow :item="row.item" :time-zone="timeZone" :turn="turn" @filter="onFilter" />
        </template>
      </VirtualList>
      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2 text-xs text-muted">
        <span class="tabular">{{ t('logs.count', { shown: shown.length, read: items.length }) }}</span>
        <Button v-if="more" size="sm" variant="ghost" :loading="logs.isFetching.value" @click="limit = LIMITS[LIMITS.indexOf(limit) + 1]!">
          {{ t('logs.more', { n: LIMITS[LIMITS.indexOf(limit) + 1] }) }}
        </Button>
      </div>
    </div>

    <section v-if="files.data.value?.items.length" class="flex min-w-0 flex-col gap-2 rounded-xl border border-line bg-surface p-4">
      <h3 class="text-base font-semibold">{{ t('logs.files') }}</h3>
      <ul class="flex list-none flex-col divide-y divide-line">
        <li v-for="file in files.data.value.items" :key="file.name" class="flex items-center gap-3 py-2">
          <FileText :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate font-mono text-sm">{{ file.name }}</span>
          <span class="text-xs text-muted tabular">{{ size(file.bytes) }}</span>
          <a
            :href="logsApi.fileUrl(file.name)"
            class="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-semibold text-ink hover:bg-hover focus-visible:focus-ring"
          >
            <Download :size="15" aria-hidden="true" />{{ t('logs.download') }}
          </a>
        </li>
      </ul>
    </section>
  </div>
</template>
