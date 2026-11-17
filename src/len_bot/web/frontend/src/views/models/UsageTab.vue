<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { BarChart3 } from '@lucide/vue'
import { modelsApi } from '../../api/models'
import { keys } from '../../api/query'
import type { SettingsSnapshot } from '../../api/settings'
import { developerDetails } from '../../composables/useDeveloperMode'
import { formatNumber } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import StatTile from '../../ui/StatTile.vue'
import RawRecord from '../groups/tasks/RawRecord.vue'
import { useLiveLabels } from '../groups/live/labels'
import LimitsSection from './LimitsSection.vue'
import { sceneSecondaryId } from './form'

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
const tiles = computed(() => {
  const value = data.value
  return [
    { key: 'total', value: value ? value.input + value.output : null },
    { key: 'input', value: value?.input ?? null },
    { key: 'cached', value: value?.cached ?? null },
    { key: 'output', value: value?.output ?? null },
    { key: 'calls', value: value?.calls ?? null },
  ]
})

// A month lists each day's models; a day lists the models once.
const modelRows = computed(() =>
  period.value === 'month'
    ? (data.value?.days ?? [])
    : (data.value?.models ?? []).map((row) => ({ ...row, day: '' })),
)

const wakeScene = ref('all')
const wakeScenes = computed(() => [
  { value: 'all', label: t('models.usage.allGroups') },
  ...[...new Set((data.value?.wakes ?? []).map((row) => row.scene))].map((scene) => ({
    value: scene,
    label: groupLabel(scene),
  })),
])
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
          class="grid grid-cols-2 gap-x-6 gap-y-5 border-y border-line py-5 sm:grid-cols-3 lg:grid-cols-5 lg:gap-x-0 lg:divide-x lg:divide-line"
        >
          <div v-for="item in tiles" :key="item.key" class="min-w-0 lg:px-5 lg:first:pl-0 lg:last:pr-0">
            <StatTile
              :label="t(`models.usage.tiles.${item.key}`)"
              :value="item.value"
              :loading="usage.isPending.value"
              :format-options="
                item.key === 'calls' ? undefined : { notation: 'compact', maximumFractionDigits: 1 }
              "
            />
          </div>
        </div>
      </template>
    </section>

    <section v-if="!usage.isError.value" class="flex min-w-0 flex-col gap-3">
      <h2 class="text-base font-semibold text-ink">{{ t('models.usage.byModel') }}</h2>
      <Skeleton v-if="usage.isPending.value" :lines="3" />
      <EmptyState
        v-else-if="!data?.models.length"
        :icon="BarChart3"
        :title="t('models.usage.noCalls')"
        compact
      />
      <template v-else>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line sm:hidden">
          <li
            v-for="row in modelRows"
            :key="`${row.day}/${row.provider}/${row.model}`"
            class="flex flex-col gap-1.5 py-3"
          >
            <div class="flex min-w-0 items-baseline justify-between gap-2">
              <span class="min-w-0 truncate font-mono text-sm font-medium text-ink">{{ row.model }}</span>
              <span class="shrink-0 text-xs text-muted">
                <template v-if="period === 'month'">
                  <span class="tabular">{{ row.day }}</span>
                  ·
                </template>
                {{ row.provider }}
              </span>
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
                <th v-if="period === 'month'" scope="col" class="py-2.5 pr-3 font-medium">
                  {{ t('models.usage.date') }}
                </th>
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.model') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.calls') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.input') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.cached') }}</th>
                <th scope="col" class="py-2.5 text-right font-medium">{{ t('models.usage.output') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line border-t border-line">
              <tr
                v-for="row in modelRows"
                :key="`${row.day}/${row.provider}/${row.model}`"
                class="transition-colors hover:bg-hover/60"
              >
                <td v-if="period === 'month'" class="py-2.5 pr-3 whitespace-nowrap text-ink-2 tabular">
                  {{ row.day }}
                </td>
                <th scope="row" class="max-w-64 truncate py-2.5 pr-3 text-left font-normal text-ink">
                  <span class="font-mono font-medium">{{ row.model }}</span>
                  <span class="ml-1.5 text-xs text-muted">{{ row.provider }}</span>
                </th>
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

    <section v-if="!usage.isError.value" class="flex min-w-0 flex-col gap-3">
      <h2 class="text-base font-semibold text-ink">{{ t('models.usage.byGroup') }}</h2>
      <Skeleton v-if="usage.isPending.value" :lines="3" />
      <EmptyState
        v-else-if="!data?.groups.length"
        :icon="BarChart3"
        :title="t('models.usage.noCalls')"
        compact
      />
      <template v-else>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line sm:hidden">
          <li
            v-for="row in data.groups"
            :key="`${row.scene}/${row.purpose}`"
            class="flex flex-col gap-1.5 py-3"
          >
            <div class="flex min-w-0 items-baseline justify-between gap-2">
              <div class="flex min-w-0 items-baseline gap-1.5">
                <span class="truncate text-sm font-medium text-ink">{{ groupLabel(row.scene) }}</span>
                <span
                  v-if="sceneSecondaryId(row.scene)"
                  class="shrink-0 font-mono text-xs text-muted tabular"
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
                {{ t('models.usage.output') }}
                <strong class="font-medium text-ink-2">{{ count(row.output) }}</strong>
              </span>
            </div>
          </li>
        </ul>
        <div class="w-full overflow-x-auto border-y border-line scrollbar-thin max-sm:hidden">
          <table class="w-full min-w-120 text-sm">
            <thead>
              <tr class="text-left text-xs text-muted">
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.group') }}</th>
                <th scope="col" class="py-2.5 pr-3 font-medium">{{ t('models.usage.role') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.calls') }}</th>
                <th scope="col" class="py-2.5 pr-3 text-right font-medium">{{ t('models.usage.input') }}</th>
                <th scope="col" class="py-2.5 text-right font-medium">{{ t('models.usage.output') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line border-t border-line">
              <tr
                v-for="row in data.groups"
                :key="`${row.scene}/${row.purpose}`"
                class="transition-colors hover:bg-hover/60"
              >
                <th scope="row" class="max-w-56 py-2.5 pr-3 text-left font-normal text-ink">
                  <div class="flex min-w-0 items-baseline gap-1.5">
                    <span class="truncate font-medium">{{ groupLabel(row.scene) }}</span>
                    <span
                      v-if="sceneSecondaryId(row.scene)"
                      class="shrink-0 font-mono text-xs text-muted tabular"
                    >
                      {{ sceneSecondaryId(row.scene) }}
                    </span>
                  </div>
                </th>
                <td class="py-2.5 pr-3 whitespace-nowrap text-ink-2">{{ labels.role(row.purpose) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.calls) }}</td>
                <td class="py-2.5 pr-3 text-right text-ink-2 tabular">{{ count(row.input) }}</td>
                <td class="py-2.5 text-right text-ink-2 tabular">{{ count(row.output) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <section v-if="!usage.isError.value" class="flex min-w-0 flex-col gap-3">
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
              <div class="flex min-w-0 items-baseline gap-1.5">
                <span class="truncate text-sm font-medium text-ink">{{ groupLabel(row.scene) }}</span>
                <span
                  v-if="sceneSecondaryId(row.scene)"
                  class="shrink-0 font-mono text-xs text-muted tabular"
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
                    <span class="truncate font-medium">{{ groupLabel(row.scene) }}</span>
                    <span
                      v-if="sceneSecondaryId(row.scene)"
                      class="shrink-0 font-mono text-xs text-muted tabular"
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
