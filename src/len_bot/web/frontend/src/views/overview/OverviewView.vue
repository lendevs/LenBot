<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Overview } from '../../api/overview'
import { developerDetails } from '../../composables/useDeveloperMode'
import { host, readHostState, readOverview } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import ErrorNote from '../../ui/ErrorNote.vue'
import Skeleton from '../../ui/Skeleton.vue'
import StatTile from '../../ui/StatTile.vue'
import RawRecord from '../groups/tasks/RawRecord.vue'
import AttentionList from './AttentionList.vue'
import GroupsPanel from './GroupsPanel.vue'
import HealthPanel from './HealthPanel.vue'
import LiveFeed from './LiveFeed.vue'
import StatusCard from './StatusCard.vue'
import { useAttention } from './attention'

const { t } = useI18n()
const { items, dismiss } = useAttention()
// The shell reads today's overview and keeps it fresh from events; this page only shows it.
const day = computed(() => host.overview as Overview | null)
const sum = (values: Record<string, number | undefined>) =>
  Object.values(values).reduce<number>((total, value) => total + (value ?? 0), 0)

const statKeys = ['received', 'spoke', 'turns', 'tokens', 'schedules'] as const

const stats = computed(() => {
  const value = day.value
  if (!value) return null
  return [
    {
      key: 'received',
      value: value.messages.received ?? 0,
      trend: value.hourly.received,
      tone: 'brand' as const,
    },
    {
      key: 'spoke',
      value: (value.messages.sent ?? 0) + (value.messages.simulated ?? 0),
      trend: value.hourly.spoke,
      tone: 'success' as const,
    },
    { key: 'turns', value: sum(value.turns), trend: value.hourly.turns, tone: 'info' as const },
    {
      key: 'tokens',
      value: value.tokens.input + value.tokens.output,
      trend: value.hourly.tokens,
      tone: 'warning' as const,
    },
    { key: 'schedules', value: value.pending_schedules, trend: undefined, tone: 'neutral' as const },
  ]
})
const tokenNote = computed(() => {
  const value = day.value
  if (!value) return ''
  return t('overview.stats.tokenSplit', {
    input: formatNumber(value.tokens.input),
    output: formatNumber(value.tokens.output),
  })
})
const activeTasksNote = computed(() => {
  const n = day.value?.active_tasks ?? 0
  return n > 0 ? t('overview.stats.tasks', { n: formatNumber(n) }) : undefined
})
const effects = computed(() =>
  Object.entries(day.value?.reply_effects ?? {})
    .filter(([, n]) => n)
    .map(([key, n]) =>
      t('overview.stats.effect', { name: t(`overview.stats.effects.${key}`), n: formatNumber(n) }),
    ),
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-6">
    <div v-if="!host.state && !host.stateError" class="flex flex-col gap-6" aria-hidden="true">
      <div class="flex items-center gap-4 border-b border-line pb-6">
        <Skeleton width="48px" height="48px" rounded="rounded-xl" />
        <div class="flex min-w-0 flex-1 flex-col gap-2">
          <Skeleton width="140px" height="22px" />
          <Skeleton width="180px" height="14px" />
        </div>
        <Skeleton width="96px" height="32px" rounded="rounded-md" />
      </div>
      <div
        class="grid grid-cols-2 gap-x-5 gap-y-6 border-b border-line pb-6 sm:grid-cols-3 lg:grid-cols-5 lg:gap-x-0 lg:divide-x lg:divide-line"
      >
        <div v-for="key in statKeys" :key="key" class="min-w-0 lg:px-5 lg:first:pl-0 lg:last:pr-0">
          <StatTile :label="t(`overview.stats.${key}`)" :value="null" loading />
        </div>
      </div>
      <div class="grid min-w-0 gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(21rem,2.2fr)]">
        <Skeleton :lines="4" />
        <Skeleton :lines="4" />
      </div>
    </div>
    <ErrorNote
      v-else-if="!host.state"
      :title="t('overview.stateFailed')"
      :error="host.stateError"
      :retry="readHostState"
    />
    <template v-else>
      <StatusCard />

      <ErrorNote
        v-if="host.overviewError"
        :title="t('overview.readFailed')"
        :error="host.overviewError"
        :retry="readOverview"
      />
      <section class="flex flex-col gap-3 border-b border-line pb-6">
        <div
          class="grid grid-cols-2 gap-x-5 gap-y-6 sm:grid-cols-3 lg:grid-cols-5 lg:gap-x-0 lg:divide-x lg:divide-line"
        >
          <template v-if="stats">
            <div v-for="item in stats" :key="item.key" class="min-w-0 lg:px-5 lg:first:pl-0 lg:last:pr-0">
              <StatTile
                :label="t(`overview.stats.${item.key}`)"
                :value="item.value"
                :trend="item.trend"
                :tone="item.tone"
                :caption="
                  item.key === 'tokens' ? tokenNote : item.key === 'schedules' ? activeTasksNote : undefined
                "
                :format-options="
                  item.key === 'tokens' ? { notation: 'compact', maximumFractionDigits: 1 } : undefined
                "
              />
            </div>
          </template>
          <template v-else>
            <div v-for="key in statKeys" :key="key" class="min-w-0 lg:px-5 lg:first:pl-0 lg:last:pr-0">
              <StatTile :label="t(`overview.stats.${key}`)" :value="null" loading />
            </div>
          </template>
        </div>
        <p v-if="stats && effects.length" class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted tabular">
          <span>{{ t('overview.stats.effectsLabel') }}{{ effects.join(' · ') }}</span>
        </p>
      </section>

      <div class="grid min-w-0 items-start gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(21rem,2.2fr)]">
        <div class="flex min-w-0 flex-col gap-8">
          <AttentionList :items="items" :loading="!day && !host.overviewError" @dismiss="dismiss" />
          <LiveFeed :overview="day" />
        </div>
        <div class="flex min-w-0 flex-col gap-8">
          <GroupsPanel />
          <HealthPanel />
        </div>
      </div>

      <div v-if="developerDetails" class="flex flex-col gap-2 border-t border-line pt-4">
        <RawRecord :label="t('overview.raw.connection')" :code="host.state.connection" />
        <RawRecord v-if="day" :label="t('overview.raw.overview')" :code="day" />
        <RawRecord
          v-if="Object.keys(host.titleErrors).length"
          :label="t('overview.raw.titles')"
          :code="host.titleErrors"
        />
      </div>
    </template>
  </div>
</template>
