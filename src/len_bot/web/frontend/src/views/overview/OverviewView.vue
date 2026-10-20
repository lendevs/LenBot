<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Overview } from '../../api/overview'
import { developerDetails } from '../../composables/useDeveloperMode.js'
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
const { items } = useAttention()
// The shell reads today's overview and keeps it fresh from events; this page only shows it.
const day = computed(() => host.overview as Overview | null)
const sum = (values: Record<string, number | undefined>) =>
  Object.values(values).reduce<number>((total, value) => total + (value ?? 0), 0)

const stats = computed(() => {
  const value = day.value
  if (!value) return null
  return [
    { key: 'received', value: value.messages.received ?? 0, trend: value.hourly.received, tone: 'brand' as const },
    {
      key: 'spoke',
      value: (value.messages.sent ?? 0) + (value.messages.simulated ?? 0),
      trend: value.hourly.spoke,
      tone: 'success' as const,
    },
    { key: 'turns', value: sum(value.turns), trend: value.hourly.turns, tone: 'info' as const },
    { key: 'tokens', value: value.tokens.input + value.tokens.output, trend: value.hourly.tokens, tone: 'warning' as const },
    { key: 'schedules', value: value.pending_schedules, trend: undefined, tone: 'neutral' as const },
  ]
})
const tokenNote = computed(() => {
  const value = day.value
  if (!value) return ''
  return value.unknown_token_calls
    ? t('overview.stats.unknownTokens', { n: formatNumber(value.unknown_token_calls) })
    : t('overview.stats.tokenSplit', { input: formatNumber(value.tokens.input), output: formatNumber(value.tokens.output) })
})
const effects = computed(() =>
  Object.entries(day.value?.reply_effects ?? {})
    .filter(([, n]) => n)
    .map(([key, n]) => t('overview.stats.effect', { name: t(`overview.stats.effects.${key}`), n })),
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-6">
    <Skeleton v-if="!host.state && !host.stateError" :lines="4" />
    <ErrorNote v-else-if="!host.state" :title="t('overview.stateFailed')" :error="host.stateError" :retry="readHostState" />
    <template v-else>
      <StatusCard />

      <ErrorNote v-if="host.overviewError" :title="t('overview.readFailed')" :error="host.overviewError" :retry="readOverview" />
      <section class="flex flex-col gap-2">
        <div class="grid grid-cols-2 gap-x-6 gap-y-5 rounded-xl border border-line bg-surface p-5 sm:grid-cols-3 lg:grid-cols-5">
          <template v-if="stats">
            <StatTile
              v-for="item in stats"
              :key="item.key"
              :label="t(`overview.stats.${item.key}`)"
              :value="item.value"
              :trend="item.trend"
              :tone="item.tone"
              :format-options="item.key === 'tokens' ? { notation: 'compact', maximumFractionDigits: 1 } : undefined"
            />
          </template>
          <template v-else>
            <StatTile v-for="n in 5" :key="n" label="" :value="null" loading />
          </template>
        </div>
        <p v-if="stats" class="flex flex-wrap gap-x-4 gap-y-1 px-1 text-xs text-muted">
          <span>{{ t('overview.stats.hours') }}</span>
          <span>{{ tokenNote }}</span>
          <span v-if="effects.length">{{ t('overview.stats.effectsLabel') }}{{ effects.join(' · ') }}</span>
        </p>
      </section>

      <div class="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(20rem,2fr)]">
        <div class="flex min-w-0 flex-col gap-6">
          <AttentionList :items="items" :loading="!day && !host.overviewError" />
          <LiveFeed :overview="day" />
        </div>
        <div class="flex min-w-0 flex-col gap-6">
          <GroupsPanel />
          <HealthPanel />
        </div>
      </div>

      <div v-if="developerDetails" class="flex flex-col gap-2">
        <RawRecord :label="t('overview.raw.connection')" :code="host.state.connection" />
        <RawRecord v-if="day" :label="t('overview.raw.overview')" :code="day" />
        <RawRecord v-if="Object.keys(host.titleErrors).length" :label="t('overview.raw.titles')" :code="host.titleErrors" />
      </div>
    </template>
  </div>
</template>
