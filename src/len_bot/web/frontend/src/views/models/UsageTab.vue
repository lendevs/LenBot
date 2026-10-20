<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { BarChart3 } from '@lucide/vue'
import { modelsApi } from '../../api/models'
import { keys } from '../../api/query'
import type { SettingsSnapshot } from '../../api/settings'
import { developerDetails } from '../../composables/useDeveloperMode.js'
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

const wakeScene = ref('all')
const wakeScenes = computed(() => [
  { value: 'all', label: t('models.usage.allGroups') },
  ...[...new Set((data.value?.wakes ?? []).map((row) => row.scene))].map((scene) => ({ value: scene, label: groupLabel(scene) })),
])
const wakes = computed(() => (data.value?.wakes ?? []).filter((row) => wakeScene.value === 'all' || row.scene === wakeScene.value))
const count = (value: number) => formatNumber(value)
const percent = (value: number) => formatNumber(value, { style: 'percent', maximumFractionDigits: 1 })
</script>

<template>
  <div class="flex min-w-0 flex-col gap-8">
    <section class="flex min-w-0 flex-col gap-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-base font-semibold">{{ t('models.usage.title') }}</h2>
        <SegmentedControl v-model="period" :options="periods" size="sm" :label="t('models.usage.title')" />
      </div>
      <ErrorNote v-if="usage.isError.value" :title="t('models.usage.readFailed')" :error="usage.error.value" :retry="usage.refetch" />
      <template v-else>
        <div class="grid grid-cols-2 gap-x-6 gap-y-5 rounded-xl border border-line bg-surface p-5 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile
            v-for="item in tiles"
            :key="item.key"
            :label="t(`models.usage.tiles.${item.key}`)"
            :value="item.value"
            :loading="usage.isPending.value"
            :format-options="item.key === 'calls' ? undefined : { notation: 'compact', maximumFractionDigits: 1 }"
          />
        </div>
        <p v-if="data?.unknown_calls" class="text-xs text-muted">
          {{ t('models.usage.unknown', { n: count(data.unknown_calls) }, data.unknown_calls) }}
        </p>
      </template>
    </section>

    <section v-if="!usage.isError.value" class="flex min-w-0 flex-col gap-3">
      <h2 class="text-base font-semibold">{{ t('models.usage.byGroup') }}</h2>
      <Skeleton v-if="usage.isPending.value" :lines="3" />
      <EmptyState v-else-if="!data?.groups.length" :icon="BarChart3" :title="t('models.usage.noCalls')" compact />
      <div v-else class="overflow-x-auto rounded-xl border border-line bg-surface px-4 scrollbar-thin">
        <table class="w-full min-w-[560px] text-sm">
          <thead>
            <tr class="text-left text-xs text-muted">
              <th scope="col" class="py-2 pr-3 font-medium">{{ t('models.usage.group') }}</th>
              <th scope="col" class="py-2 pr-3 font-medium">{{ t('models.usage.role') }}</th>
              <th scope="col" class="py-2 pr-3 text-right font-medium">{{ t('models.usage.calls') }}</th>
              <th scope="col" class="py-2 pr-3 text-right font-medium">{{ t('models.usage.input') }}</th>
              <th scope="col" class="py-2 text-right font-medium">{{ t('models.usage.output') }}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line border-t border-line">
            <tr v-for="row in data.groups" :key="`${row.scene}/${row.role}`">
              <th scope="row" class="max-w-48 truncate py-2 pr-3 text-left font-normal text-ink">{{ groupLabel(row.scene) }}</th>
              <td class="py-2 pr-3 text-ink-2">{{ labels.role(row.role) }}</td>
              <td class="py-2 pr-3 text-right text-ink-2 tabular">
                {{ count(row.calls) }}
                <span v-if="row.unknown_calls" class="text-xs text-muted">{{ t('models.usage.unreported', { n: row.unknown_calls }) }}</span>
              </td>
              <td class="py-2 pr-3 text-right text-ink-2 tabular">{{ count(row.input) }}</td>
              <td class="py-2 text-right text-ink-2 tabular">{{ count(row.output) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="!usage.isError.value" class="flex min-w-0 flex-col gap-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-base font-semibold">{{ t('models.usage.wakes') }}</h2>
        <div class="w-48"><Select v-model="wakeScene" :options="wakeScenes" size="sm" /></div>
      </div>
      <Skeleton v-if="usage.isPending.value" :lines="3" />
      <EmptyState v-else-if="!wakes.length" :icon="BarChart3" :title="t('models.usage.noWakes')" compact />
      <div v-else class="overflow-x-auto rounded-xl border border-line bg-surface px-4 scrollbar-thin">
        <table class="w-full min-w-[720px] text-sm">
          <thead>
            <tr class="text-left text-xs text-muted">
              <th scope="col" class="py-2 pr-3 font-medium">{{ t('models.usage.group') }}</th>
              <th scope="col" class="py-2 pr-3 font-medium">{{ t('models.usage.date') }}</th>
              <th scope="col" class="py-2 pr-3 font-medium">{{ t('models.usage.channel') }}</th>
              <th scope="col" class="py-2 pr-3 text-right font-medium">{{ t('models.usage.woken') }}</th>
              <th scope="col" class="py-2 pr-3 text-right font-medium">{{ t('models.usage.spoken') }}</th>
              <th scope="col" class="py-2 pr-3 text-right font-medium">{{ t('models.usage.rate') }}</th>
              <th scope="col" class="py-2 pr-3 text-right font-medium">{{ t('models.usage.input') }}</th>
              <th scope="col" class="py-2 text-right font-medium">{{ t('models.usage.cached') }}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line border-t border-line">
            <tr v-for="row in wakes" :key="`${row.scene}/${row.day}/${row.channel}`">
              <th scope="row" class="max-w-48 truncate py-2 pr-3 text-left font-normal text-ink">{{ groupLabel(row.scene) }}</th>
              <td class="py-2 pr-3 text-ink-2 tabular">{{ row.day }}</td>
              <td class="py-2 pr-3 text-ink-2">{{ labels.channel(row.channel) }}</td>
              <td class="py-2 pr-3 text-right text-ink-2 tabular">{{ count(row.wakes) }}</td>
              <td class="py-2 pr-3 text-right text-ink-2 tabular">{{ count(row.spoken) }}</td>
              <td class="py-2 pr-3 text-right text-ink-2 tabular">{{ percent(row.speech_rate) }}</td>
              <td class="py-2 pr-3 text-right text-ink-2 tabular">{{ count(row.input) }}</td>
              <td class="py-2 text-right text-ink-2 tabular">{{ count(row.cached) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <RawRecord v-if="developerDetails && data" :label="t('models.usage.raw')" :code="JSON.stringify(data, null, 2)" />

    <LimitsSection :snapshot="snapshot" @dirty="(value) => emit('dirty', value)" />
  </div>
</template>
