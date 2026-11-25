<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { BarChart3, ChevronRight } from '@lucide/vue'
import { modelsApi, type UsageTotals } from '../../api/models'
import { keys } from '../../api/query'
import type { SettingsSnapshot } from '../../api/settings'
import { developerDetails } from '../../composables/useDeveloperMode'
import { formatNumber } from '../../i18n/format'
import { groupLabel, sceneSecondaryId } from '../../layouts/shell/scenes'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import StatTile from '../../ui/StatTile.vue'
import RawRecord from '../groups/tasks/RawRecord.vue'
import { useLiveLabels } from '../groups/live/labels'
import LimitsSection from './LimitsSection.vue'

defineProps<{ snapshot: SettingsSnapshot }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const labels = useLiveLabels()
const period = ref<'day' | 'month'>('day')
const periods = computed(() => [
  { value: 'day' as const, label: t('models.usage.day') },
  { value: 'month' as const, label: t('models.usage.month') },
])
const usage = useQuery({
  queryKey: computed(() => keys.host.usage(period.value)),
  queryFn: ({ signal }) => modelsApi.usage(period.value, signal),
  placeholderData: keepPreviousData,
})
const data = computed(() => usage.data.value)
const switching = computed(() => usage.isPlaceholderData.value)

type TileKey = 'total' | 'input' | 'cached' | 'output' | 'calls'
const dailySeries = computed(() => {
  if (period.value !== 'month' || data.value?.period !== 'month') return null
  const rows = data.value.days
  if (!rows.length) return null
  const byDay = new Map<string, Record<TileKey, number>>()
  for (const row of rows) {
    const entry = byDay.get(row.day) ?? { total: 0, input: 0, cached: 0, output: 0, calls: 0 }
    entry.total += row.input + row.output
    entry.input += row.input
    entry.cached += row.cached
    entry.output += row.output
    entry.calls += row.calls
    byDay.set(row.day, entry)
  }
  const days = [...byDay.keys()].sort()
  return {
    labels: days,
    total: days.map((day) => byDay.get(day)!.total),
    input: days.map((day) => byDay.get(day)!.input),
    cached: days.map((day) => byDay.get(day)!.cached),
    output: days.map((day) => byDay.get(day)!.output),
    calls: days.map((day) => byDay.get(day)!.calls),
  }
})
const tiles = computed<{ key: TileKey; value: number | null; trend?: number[] }[]>(() => {
  const value = data.value
  const series = dailySeries.value
  return [
    { key: 'total', value: value ? value.input + value.output : null, trend: series?.total },
    { key: 'input', value: value?.input ?? null, trend: series?.input },
    { key: 'cached', value: value?.cached ?? null, trend: series?.cached },
    { key: 'output', value: value?.output ?? null, trend: series?.output },
    { key: 'calls', value: value?.calls ?? null, trend: series?.calls },
  ]
})

const modelKey = (row: { provider: string; model: string }) => `${row.provider}\0${row.model}`
const modelSummaryRows = computed(() => data.value?.models ?? [])
const totalModelTokens = computed(() =>
  modelSummaryRows.value.reduce((sum, row) => sum + row.input + row.output, 0),
)
const modelShare = (row: { input: number; output: number }) => {
  const total = totalModelTokens.value
  if (total <= 0) return 0
  return Math.min(100, Math.round(((row.input + row.output) / total) * 1000) / 10)
}
const modelDays = computed(() => {
  const map = new Map<string, (UsageTotals & { day: string })[]>()
  for (const row of data.value?.days ?? []) {
    const key = modelKey(row)
    const list = map.get(key) ?? []
    list.push(row)
    map.set(key, list)
  }
  for (const list of map.values()) list.sort((a, b) => b.day.localeCompare(a.day))
  return map
})
const expandedModels = ref<Set<string>>(new Set())
watch(period, () => {
  expandedModels.value = new Set()
})
const canExpandModel = (row: { provider: string; model: string }) =>
  period.value === 'month' &&
  data.value?.period === 'month' &&
  (modelDays.value.get(modelKey(row))?.length ?? 0) > 0
const isModelExpanded = (row: { provider: string; model: string }) =>
  canExpandModel(row) && expandedModels.value.has(modelKey(row))
function toggleModel(row: { provider: string; model: string }) {
  if (!canExpandModel(row)) return
  const key = modelKey(row)
  const next = new Set(expandedModels.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedModels.value = next
}

const groupScene = ref('all')
const groupScenes = computed(() => [
  { value: 'all', label: t('models.usage.allGroups') },
  ...[...new Set((data.value?.groups ?? []).map((row) => row.scene))].map((scene) => ({
    value: scene,
    label: groupLabel(scene),
  })),
])
watch(groupScenes, (options) => {
  if (groupScene.value !== 'all' && !options.some((item) => item.value === groupScene.value)) {
    groupScene.value = 'all'
  }
})
const groupRows = computed(() =>
  (data.value?.groups ?? []).filter((row) => groupScene.value === 'all' || row.scene === groupScene.value),
)

const wakeScene = ref('all')
const wakeScenes = computed(() => [
  { value: 'all', label: t('models.usage.allGroups') },
  ...[...new Set((data.value?.wakes ?? []).map((row) => row.scene))].map((scene) => ({
    value: scene,
    label: groupLabel(scene),
  })),
])
watch(wakeScenes, (options) => {
  if (wakeScene.value !== 'all' && !options.some((item) => item.value === wakeScene.value)) {
    wakeScene.value = 'all'
  }
})
const wakes = computed(() =>
  (data.value?.wakes ?? []).filter((row) => wakeScene.value === 'all' || row.scene === wakeScene.value),
)
const count = (value: number) => formatNumber(value)
const percent = (value: number) => formatNumber(value, { style: 'percent', maximumFractionDigits: 1 })
</script>

<template>
  <div class="flex min-w-0 flex-col gap-8">
    <section class="flex min-w-0 flex-col gap-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-base font-semibold text-ink">{{ t('models.usage.title') }}</h2>
        <SegmentedControl v-model="period" :options="periods" size="sm" :label="t('models.usage.title')" />
      </div>
      <ErrorNote
        v-if="usage.isError.value"
        :title="t('models.usage.readFailed')"
        :error="usage.error.value"
        :retry="usage.refetch"
      />
      <template v-else>
        <div
          class="grid grid-cols-2 gap-x-6 gap-y-5 border-y border-line py-5 transition-opacity duration-(--dur-2) sm:grid-cols-3 lg:grid-cols-5 lg:gap-x-0 lg:divide-x lg:divide-line"
          :class="switching && 'opacity-60'"
        >
          <div v-for="item in tiles" :key="item.key" class="min-w-0 lg:px-5 lg:first:pl-0 lg:last:pr-0">
            <StatTile
              :label="t(`models.usage.tiles.${item.key}`)"
              :value="item.value"
              :trend="item.trend"
              :trend-labels="dailySeries?.labels"
              tone="brand"
              :loading="usage.isPending.value"
              :format-options="
                item.key === 'calls' ? undefined : { notation: 'compact', maximumFractionDigits: 1 }
              "
            />
          </div>
        </div>
      </template>
    </section>

    <section
      v-if="!usage.isError.value"
      class="flex min-w-0 flex-col gap-3 transition-opacity duration-(--dur-2)"
      :class="switching && 'opacity-60'"
    >
      <h2 class="text-base font-semibold text-ink">{{ t('models.usage.byModel') }}</h2>
      <Skeleton v-if="usage.isPending.value" :lines="3" />
      <EmptyState
        v-else-if="!modelSummaryRows.length"
        :icon="BarChart3"
        :title="t('models.usage.noCalls')"
        compact
      />
      <template v-else>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line sm:hidden">
          <li v-for="row in modelSummaryRows" :key="modelKey(row)" class="flex flex-col gap-2 py-3">
            <button
              v-if="canExpandModel(row)"
              type="button"
              class="flex w-full min-w-0 cursor-pointer flex-col gap-1.5 rounded-sm text-left outline-none focus-visible:focus-ring"
              :aria-expanded="isModelExpanded(row)"
              :aria-label="
                t(isModelExpanded(row) ? 'models.usage.collapseDaily' : 'models.usage.expandDaily', {
                  model: row.model,
                })
              "
              @click="toggleModel(row)"
            >
              <span class="flex w-full min-w-0 items-center justify-between gap-2">
                <span class="flex min-w-0 flex-1 items-center gap-1.5">
                  <ChevronRight
                    :size="14"
                    class="shrink-0 text-subtle transition-transform duration-(--dur-1)"
                    :class="isModelExpanded(row) && 'rotate-90'"
                    aria-hidden="true"
                  />
                  <span class="min-w-0 truncate font-mono text-sm font-medium text-ink">
                    {{ row.model }}
                  </span>
                </span>
                <span class="max-w-28 shrink-0 truncate text-xs text-muted">{{ row.provider }}</span>
              </span>
              <span class="block h-1 w-full overflow-hidden rounded-full bg-track" aria-hidden="true">
                <span
                  class="block h-full rounded-full bg-brand transition-[width] duration-(--dur-2) ease-out"
                  :style="{ width: `${modelShare(row)}%` }"
                />
              </span>
            </button>
            <div v-else class="flex flex-col gap-1.5">
              <div class="flex min-w-0 items-baseline justify-between gap-2">
                <span class="min-w-0 flex-1 truncate font-mono text-sm font-medium text-ink">
                  {{ row.model }}
                </span>
                <span class="max-w-28 shrink-0 truncate text-xs text-muted">{{ row.provider }}</span>
              </div>
              <div class="h-1 w-full overflow-hidden rounded-full bg-track" aria-hidden="true">
                <div
                  class="h-full rounded-full bg-brand transition-[width] duration-(--dur-2) ease-out"
                  :style="{ width: `${modelShare(row)}%` }"
                />
              </div>
            </div>
            <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted tabular">
              <span>
                {{ t('models.usage.calls') }}
                <strong class="font-medium text-ink-2">{{ count(row.calls) }}</strong>
              </span>
              <span>
                {{ t('models.usage.input') }}
                <strong class="font-medium text-ink-2">{{ count(row.input) }}</strong>
              </span>
              <span>
                {{ t('models.usage.cached') }}
                <strong class="font-medium text-ink-2">{{ count(row.cached) }}</strong>
              </span>
              <span>
                {{ t('models.usage.output') }}
                <strong class="font-medium text-ink-2">{{ count(row.output) }}</strong>
              </span>
            </div>
            <ul
              v-if="isModelExpanded(row)"
              class="mt-1 flex list-none flex-col divide-y divide-line rounded-md bg-fill/50 px-2.5"
            >
              <li
                v-for="dayRow in modelDays.get(modelKey(row))"
                :key="dayRow.day"
                class="flex flex-col gap-1 py-2 text-xs tabular"
              >
                <span class="font-medium text-ink-2">{{ dayRow.day }}</span>
                <div class="flex flex-wrap gap-x-3.5 gap-y-0.5 text-muted">
                  <span>
                    {{ t('models.usage.calls') }}
                    <strong class="font-medium text-ink-2">{{ count(dayRow.calls) }}</strong>
                  </span>
                  <span>
                    {{ t('models.usage.input') }}
                    <strong class="font-medium text-ink-2">{{ count(dayRow.input) }}</strong>
                  </span>
                  <span>
                    {{ t('models.usage.cached') }}
                    <strong class="font-medium text-ink-2">{{ count(dayRow.cached) }}</strong>
                  </span>
                  <span>
                    {{ t('models.usage.output') }}
                    <strong class="font-medium text-ink-2">{{ count(dayRow.output) }}</strong>
                  </span>
                </div>
              </li>
            </ul>
          </li>
        </ul>
        <div class="w-full overflow-x-auto border-y border-line scrollbar-thin max-sm:hidden">
          <table class="w-full min-w-130 text-sm">
            <thead>
              <tr class="text-left text-xs text-muted">
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.model') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.calls') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.input') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.cached') }}</th>
                <th scope="col" class="py-2.5 text-right font-medium">{{ t('models.usage.output') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line border-t border-line">
              <template v-for="row in modelSummaryRows" :key="modelKey(row)">
                <tr
                  class="transition-colors hover:bg-hover/60"
                  :class="canExpandModel(row) && 'cursor-pointer'"
                  @click="canExpandModel(row) && toggleModel(row)"
                >
                  <th scope="row" class="max-w-72 py-2.5 pr-3 text-left font-normal text-ink">
                    <div class="flex min-w-0 items-center gap-1.5">
                      <button
                        v-if="canExpandModel(row)"
                        type="button"
                        class="-ml-1 inline-flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-sm text-subtle transition-colors hover:text-ink focus-visible:focus-ring"
                        :aria-expanded="isModelExpanded(row)"
                        :aria-label="
                          t(
                            isModelExpanded(row) ? 'models.usage.collapseDaily' : 'models.usage.expandDaily',
                            { model: row.model },
                          )
                        "
                        @click.stop="toggleModel(row)"
                      >
                        <ChevronRight
                          :size="14"
                          class="transition-transform duration-(--dur-1)"
                          :class="isModelExpanded(row) && 'rotate-90'"
                          aria-hidden="true"
                        />
                      </button>
                      <span class="min-w-0 truncate font-mono font-medium">{{ row.model }}</span>
                      <span class="shrink-0 text-xs text-muted">{{ row.provider }}</span>
                    </div>
                    <div class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-track" aria-hidden="true">
                      <div
                        class="h-full rounded-full bg-brand transition-[width] duration-(--dur-2) ease-out"
                        :style="{ width: `${modelShare(row)}%` }"
                      />
                    </div>
                  </th>
                  <td class="py-2.5 pr-3 text-right align-top text-ink-2 tabular">{{ count(row.calls) }}</td>
                  <td class="py-2.5 pr-3 text-right align-top text-ink-2 tabular">{{ count(row.input) }}</td>
                  <td class="py-2.5 pr-3 text-right align-top text-ink-2 tabular">{{ count(row.cached) }}</td>
                  <td class="py-2.5 text-right align-top text-ink-2 tabular">{{ count(row.output) }}</td>
                </tr>
                <template v-if="isModelExpanded(row)">
                  <tr
                    v-for="dayRow in modelDays.get(modelKey(row))"
                    :key="`${modelKey(row)}:${dayRow.day}`"
                    class="bg-fill/40 text-xs"
                  >
                    <th
                      scope="row"
                      class="py-2 pr-3 pl-6 text-left font-normal whitespace-nowrap text-muted tabular"
                    >
                      {{ dayRow.day }}
                    </th>
                    <td class="py-2 pr-3 text-right text-muted tabular">{{ count(dayRow.calls) }}</td>
                    <td class="py-2 pr-3 text-right text-muted tabular">{{ count(dayRow.input) }}</td>
                    <td class="py-2 pr-3 text-right text-muted tabular">{{ count(dayRow.cached) }}</td>
                    <td class="py-2 text-right text-muted tabular">{{ count(dayRow.output) }}</td>
                  </tr>
                </template>
              </template>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <section
      v-if="!usage.isError.value"
      class="flex min-w-0 flex-col gap-3 transition-opacity duration-(--dur-2)"
      :class="switching && 'opacity-60'"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-base font-semibold text-ink">{{ t('models.usage.byGroup') }}</h2>
        <div v-if="groupScenes.length > 1" class="w-full sm:w-52">
          <Select v-model="groupScene" :options="groupScenes" size="sm" />
        </div>
      </div>
      <Skeleton v-if="usage.isPending.value" :lines="3" />
      <EmptyState
        v-else-if="!groupRows.length"
        :icon="BarChart3"
        :title="t('models.usage.noCalls')"
        compact
      />
      <template v-else>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line sm:hidden">
          <li
            v-for="row in groupRows"
            :key="`${row.scene}/${row.purpose}`"
            class="flex flex-col gap-1.5 py-3"
          >
            <div class="flex min-w-0 items-baseline justify-between gap-2">
              <div class="flex min-w-0 flex-1 items-baseline gap-1.5">
                <span class="min-w-0 truncate text-sm font-medium text-ink">{{ groupLabel(row.scene) }}</span>
                <span
                  v-if="sceneSecondaryId(row.scene)"
                  class="max-w-24 shrink-0 truncate font-mono text-xs text-muted tabular"
                >
                  {{ sceneSecondaryId(row.scene) }}
                </span>
              </div>
              <span class="shrink-0 text-xs text-muted">{{ labels.role(row.purpose) }}</span>
            </div>
            <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted tabular">
              <span>
                {{ t('models.usage.calls') }}
                <strong class="font-medium text-ink-2">{{ count(row.calls) }}</strong>
              </span>
              <span>
                {{ t('models.usage.input') }}
                <strong class="font-medium text-ink-2">{{ count(row.input) }}</strong>
              </span>
              <span>
                {{ t('models.usage.cached') }}
                <strong class="font-medium text-ink-2">{{ count(row.cached) }}</strong>
              </span>
              <span>
                {{ t('models.usage.output') }}
                <strong class="font-medium text-ink-2">{{ count(row.output) }}</strong>
              </span>
            </div>
          </li>
        </ul>
        <div class="w-full overflow-x-auto border-y border-line scrollbar-thin max-sm:hidden">
          <table class="w-full min-w-130 text-sm">
            <thead>
              <tr class="text-left text-xs text-muted">
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.group') }}</th>
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.role') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.calls') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.input') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.cached') }}</th>
                <th scope="col" class="py-2.5 text-right font-medium">{{ t('models.usage.output') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line border-t border-line">
              <tr
                v-for="row in groupRows"
                :key="`${row.scene}/${row.purpose}`"
                class="transition-colors hover:bg-hover/60"
              >
                <th scope="row" class="max-w-56 py-2.5 pr-3 text-left font-normal text-ink">
                  <div class="flex min-w-0 items-baseline gap-1.5">
                    <span class="min-w-0 truncate font-medium">{{ groupLabel(row.scene) }}</span>
                    <span
                      v-if="sceneSecondaryId(row.scene)"
                      class="max-w-28 shrink-0 truncate font-mono text-xs text-muted tabular"
                    >
                      {{ sceneSecondaryId(row.scene) }}
                    </span>
                  </div>
                </th>
                <td class="py-2.5 pr-3 whitespace-nowrap text-ink-2">{{ labels.role(row.purpose) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.calls) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.input) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.cached) }}</td>
                <td class="py-2.5 text-right text-ink-2 tabular">{{ count(row.output) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <section
      v-if="!usage.isError.value"
      class="flex min-w-0 flex-col gap-3 transition-opacity duration-(--dur-2)"
      :class="switching && 'opacity-60'"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-base font-semibold text-ink">{{ t('models.usage.wakes') }}</h2>
        <div class="w-full sm:w-52"><Select v-model="wakeScene" :options="wakeScenes" size="sm" /></div>
      </div>
      <Skeleton v-if="usage.isPending.value" :lines="3" />
      <EmptyState v-else-if="!wakes.length" :icon="BarChart3" :title="t('models.usage.noWakes')" compact />
      <template v-else>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line sm:hidden">
          <li
            v-for="row in wakes"
            :key="`${row.scene}/${row.day}/${row.channel}`"
            class="flex flex-col gap-1.5 py-3"
          >
            <div class="flex min-w-0 items-baseline justify-between gap-2">
              <div class="flex min-w-0 flex-1 items-baseline gap-1.5">
                <span class="min-w-0 truncate text-sm font-medium text-ink">{{ groupLabel(row.scene) }}</span>
                <span
                  v-if="sceneSecondaryId(row.scene)"
                  class="max-w-24 shrink-0 truncate font-mono text-xs text-muted tabular"
                >
                  {{ sceneSecondaryId(row.scene) }}
                </span>
              </div>
              <span class="shrink-0 text-xs text-muted">
                <span class="tabular">{{ row.day }}</span>
                · {{ labels.channel(row.channel) }}
              </span>
            </div>
            <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted tabular">
              <span>
                {{ t('models.usage.woken') }}
                <strong class="font-medium text-ink-2">{{ count(row.wakes) }}</strong>
              </span>
              <span>
                {{ t('models.usage.spoken') }}
                <strong class="font-medium text-ink-2">{{ count(row.spoken) }}</strong>
              </span>
              <span>
                {{ t('models.usage.rate') }}
                <strong class="font-medium text-ink-2">{{ percent(row.speech_rate) }}</strong>
              </span>
              <span>
                {{ t('models.usage.input') }}
                <strong class="font-medium text-ink-2">{{ count(row.input) }}</strong>
              </span>
              <span>
                {{ t('models.usage.cached') }}
                <strong class="font-medium text-ink-2">{{ count(row.cached) }}</strong>
              </span>
            </div>
          </li>
        </ul>
        <div class="w-full overflow-x-auto border-y border-line scrollbar-thin max-sm:hidden">
          <table class="w-full min-w-160 text-sm">
            <thead>
              <tr class="text-left text-xs text-muted">
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.group') }}</th>
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.date') }}</th>
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.channel') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.woken') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.spoken') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.rate') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.input') }}</th>
                <th scope="col" class="py-2.5 text-right font-medium">{{ t('models.usage.cached') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line border-t border-line">
              <tr
                v-for="row in wakes"
                :key="`${row.scene}/${row.day}/${row.channel}`"
                class="transition-colors hover:bg-hover/60"
              >
                <th scope="row" class="max-w-56 py-2.5 pr-3 text-left font-normal text-ink">
                  <div class="flex min-w-0 items-baseline gap-1.5">
                    <span class="min-w-0 truncate font-medium">{{ groupLabel(row.scene) }}</span>
                    <span
                      v-if="sceneSecondaryId(row.scene)"
                      class="max-w-28 shrink-0 truncate font-mono text-xs text-muted tabular"
                    >
                      {{ sceneSecondaryId(row.scene) }}
                    </span>
                  </div>
                </th>
                <td class="py-2.5 pr-3 whitespace-nowrap text-ink-2 tabular">{{ row.day }}</td>
                <td class="py-2.5 pr-3 whitespace-nowrap text-ink-2">{{ labels.channel(row.channel) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.wakes) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.spoken) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ percent(row.speech_rate) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.input) }}</td>
                <td class="py-2.5 text-right text-ink-2 tabular">{{ count(row.cached) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <RawRecord
      v-if="developerDetails && data"
      :label="t('models.usage.raw')"
      :code="JSON.stringify(data, null, 2)"
    />

    <LimitsSection :snapshot="snapshot" @dirty="(value) => emit('dirty', value)" />
  </div>
</template>
