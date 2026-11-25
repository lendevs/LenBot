<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ArrowUpRight, ChevronDown, Moon } from '@lucide/vue'
import { logsApi } from '../../../api/logs'
import { overviewApi } from '../../../api/overview'
import { keys } from '../../../api/query'
import { host } from '../../../api/hostStore'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatDateTime, formatDuration, formatNumber, formatRelative } from '../../../i18n/format'
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
  if (latest && Date.now() / 1000 - latest.at < 600)
    return { text: t('overview.health.stalled'), tone: 'warning' }
  return { text: t('overview.health.smooth'), tone: 'success' }
})
</script>

<template>
  <div class="flex min-w-0 max-w-4xl flex-col divide-y divide-line">
    <div v-if="loop.isPending.value" class="py-4">
      <Skeleton :lines="4" />
    </div>
    <div v-else-if="loop.isError.value" class="py-4">
      <ErrorNote :title="t('overview.health.readFailed')" :error="loop.error.value" :retry="loop.refetch" />
    </div>
    <template v-else-if="data">
      <section class="flex min-w-0 flex-col gap-4 py-6 first:pt-1">
        <header class="flex flex-wrap items-center gap-2.5">
          <h3 class="text-base font-semibold text-ink">{{ t('overview.health.loop') }}</h3>
          <Badge :tone="verdict.tone" dot>{{ verdict.text }}</Badge>
          <span v-if="data.started_at" class="text-xs text-muted tabular">
            {{ t('logs.health.since', { time: formatDateTime(data.started_at, { timeZone }) }) }}
          </span>
        </header>
        <div
          class="grid grid-cols-2 gap-x-6 gap-y-5 border-y border-line py-5 sm:grid-cols-4 sm:gap-x-0 sm:divide-x sm:divide-line"
        >
          <div class="min-w-0 sm:pr-5">
            <StatTile :label="t('logs.health.stalls')" :value="data.stalls" />
          </div>
          <div class="min-w-0 sm:px-5">
            <StatTile :label="t('logs.health.longest')" :value="formatDuration(data.max_lag_ms)" />
          </div>
          <div class="min-w-0 sm:px-5">
            <StatTile :label="t('logs.health.total')" :value="formatDuration(data.stalled_ms_total)" />
          </div>
          <div class="min-w-0 sm:pl-5">
            <StatTile :label="t('logs.health.pauses')" :value="data.pauses" />
          </div>
        </div>
        <p v-if="developerDetails" class="text-xs text-muted tabular">
          {{
            t('logs.health.probe', {
              interval: formatNumber(data.interval_ms),
              threshold: formatNumber(data.threshold_ms),
              n: formatNumber(data.probes),
            })
          }}
        </p>
      </section>

      <section class="flex min-w-0 flex-col gap-3 py-6">
        <header class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-base font-semibold text-ink">{{ t('logs.health.recent') }}</h3>
          <Button
            size="sm"
            variant="ghost"
            :icon-right="ArrowUpRight"
            :to="{ query: { tab: 'system', event: 'event_loop_stall' } }"
          >
            {{ t('logs.health.allStalls') }}
          </Button>
        </header>
        <p v-if="!data.recent.length" class="text-sm text-muted">{{ t('logs.health.noStalls') }}</p>
        <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
          <li v-for="stall in data.recent" :key="stall.at" class="flex flex-col gap-1.5 py-3">
            <details class="group">
              <summary
                class="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 gap-y-0.5 rounded-sm text-sm select-none focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
              >
                <strong class="font-semibold text-warning tabular">
                  {{ formatDuration(stall.lag_ms) }}
                </strong>
                <span class="min-w-0 font-mono break-all text-ink-2">
                  {{ stall.task ?? t('common.unknown') }}
                </span>
                <span class="text-xs text-muted tabular">
                  {{ formatDateTime(stall.at, { withSeconds: true, timeZone }) }} ·
                  {{ formatRelative(stall.at) }}
                </span>
                <ChevronDown
                  :size="15"
                  class="ml-auto shrink-0 self-center text-subtle transition-transform group-open:rotate-180"
                  aria-hidden="true"
                />
              </summary>
              <div class="mt-2 min-w-0">
                <CodeBlock :code="stall.stack ?? t('overview.health.noStack')" :max-lines="16" />
              </div>
            </details>
          </li>
        </ul>
      </section>
    </template>

    <section class="flex min-w-0 flex-col gap-3 py-6 last:pb-0">
      <h3 class="text-base font-semibold text-ink">{{ t('logs.health.pauseTitle') }}</h3>
      <Skeleton v-if="pauses.isPending.value" :lines="2" />
      <ErrorNote
        v-else-if="pauses.isError.value"
        :title="t('logs.readFailed')"
        :error="pauses.error.value"
        :retry="pauses.refetch"
      />
      <p v-else-if="!pauses.data.value?.items.length" class="text-sm text-muted">
        {{ t('logs.health.noPauses') }}
      </p>
      <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li
          v-for="item in pauses.data.value.items"
          :key="item.ts"
          class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm"
        >
          <Moon :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
          <span class="text-ink-2 tabular">
            {{ formatDateTime(seconds(item), { withSeconds: true, timeZone }) }}
          </span>
          <span class="text-muted tabular">
            {{ t('logs.health.pausedDuration', { duration: formatDuration(Number(item.lag_ms ?? 0)) }) }}
          </span>
        </li>
      </ul>
    </section>
  </div>
</template>
