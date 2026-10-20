<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ArrowUpRight, Moon } from '@lucide/vue'
import { logsApi } from '../../../api/logs'
import { overviewApi } from '../../../api/overview'
import { keys } from '../../../api/query'
import { host } from '../../../host/store.js'
import { formatDateTime, formatNumber, formatRelative } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import StatTile from '../../../ui/StatTile.vue'
import { seconds } from './labels'

const { t } = useI18n()
// Stalls are not events; the probe's counters are read every ten seconds while the page is visible.
const loop = useQuery({
  queryKey: keys.host.eventLoop(),
  queryFn: ({ signal }) => overviewApi.eventLoop(signal),
  refetchInterval: 10_000,
})
// Pauses are only counted in memory; the log keeps when each one happened, across restarts.
const pauses = useQuery({
  queryKey: keys.system.logs({ event: 'event_loop_paused', limit: 20 }),
  queryFn: ({ signal }) => logsApi.read({ event: 'event_loop_paused', limit: 20 }, signal),
})
const data = computed(() => loop.data.value)
const timeZone = computed(() => host.state?.timezone as string | undefined)
const verdict = computed<{ text: string; tone: Tone }>(() => {
  const value = data.value
  if (!value) return { text: t('common.loading'), tone: 'neutral' }
  if (!value.running) return { text: t('overview.health.idle'), tone: 'neutral' }
  const latest = value.recent[0]
  if (latest && Date.now() / 1000 - latest.at < 600) return { text: t('overview.health.stalled'), tone: 'warning' }
  return { text: t('overview.health.smooth'), tone: 'success' }
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <Skeleton v-if="loop.isPending.value" :lines="4" />
    <ErrorNote v-else-if="loop.isError.value" :title="t('overview.health.readFailed')" :error="loop.error.value" :retry="loop.refetch" />
    <template v-else-if="data">
      <section class="flex min-w-0 flex-col gap-4 rounded-xl border border-line bg-surface p-5">
        <header class="flex flex-wrap items-center gap-2">
          <h3 class="text-base font-semibold">{{ t('overview.health.loop') }}</h3>
          <Badge :tone="verdict.tone" dot>{{ verdict.text }}</Badge>
          <span v-if="data.started_at" class="text-xs text-muted">{{ t('logs.health.since', { time: formatDateTime(data.started_at, { timeZone }) }) }}</span>
        </header>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile :label="t('logs.health.stalls')" :value="data.stalls" />
          <StatTile :label="t('logs.health.longest')" :value="data.max_lag_ms" unit="ms" />
          <StatTile :label="t('logs.health.total')" :value="data.stalled_ms_total" unit="ms" />
          <StatTile :label="t('logs.health.pauses')" :value="data.pauses" />
        </div>
        <p class="text-xs text-muted tabular">
          {{ t('logs.health.probe', { interval: data.interval_ms, threshold: data.threshold_ms, n: formatNumber(data.probes) }) }}
        </p>
      </section>

      <section class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
        <header class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-base font-semibold">{{ t('logs.health.recent') }}</h3>
          <Button size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="{ query: { tab: 'system', event: 'event_loop_stall' } }">
            {{ t('logs.health.allStalls') }}
          </Button>
        </header>
        <p v-if="!data.recent.length" class="text-sm text-muted">{{ t('logs.health.noStalls') }}</p>
        <ul v-else class="flex list-none flex-col divide-y divide-line">
          <li v-for="stall in data.recent" :key="stall.at" class="flex flex-col gap-1.5 py-3">
            <details>
              <summary class="flex cursor-pointer flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
                <strong class="font-semibold text-warning tabular">{{ formatNumber(stall.lag_ms) }} ms</strong>
                <span class="font-mono text-ink-2">{{ stall.task ?? t('common.unknown') }}</span>
                <span class="text-xs text-muted">{{ formatDateTime(stall.at, { withSeconds: true, timeZone }) }} · {{ formatRelative(stall.at) }}</span>
              </summary>
              <CodeBlock :code="stall.stack ?? t('overview.health.noStack')" :max-lines="16" class="mt-2" />
            </details>
          </li>
        </ul>
      </section>
    </template>

    <section class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
      <h3 class="text-base font-semibold">{{ t('logs.health.pauseTitle') }}</h3>
      <Skeleton v-if="pauses.isPending.value" :lines="2" />
      <ErrorNote v-else-if="pauses.isError.value" :title="t('logs.readFailed')" :error="pauses.error.value" :retry="pauses.refetch" />
      <p v-else-if="!pauses.data.value?.items.length" class="text-sm text-muted">{{ t('logs.health.noPauses') }}</p>
      <ul v-else class="flex list-none flex-col divide-y divide-line">
        <li v-for="item in pauses.data.value.items" :key="item.ts" class="flex items-center gap-3 py-2 text-sm">
          <Moon :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
          <span class="text-ink-2 tabular">{{ formatDateTime(seconds(item), { withSeconds: true, timeZone }) }}</span>
          <span class="text-muted tabular">
            {{ t('logs.health.pausedFor', { n: formatNumber(Math.round(Number(item.lag_ms ?? 0) / 1000)) }) }}
          </span>
        </li>
      </ul>
    </section>
  </div>
</template>
