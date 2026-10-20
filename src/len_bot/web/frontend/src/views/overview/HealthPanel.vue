<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { overviewApi } from '../../api/overview'
import { keys } from '../../api/query'
import { formatNumber, formatRelative } from '../../i18n/format'
import Badge, { type Tone } from '../../ui/Badge.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Skeleton from '../../ui/Skeleton.vue'

const { t } = useI18n()
// Stalls are not events; the probe's counters are read every ten seconds while the page is visible.
const loop = useQuery({
  queryKey: keys.host.eventLoop(),
  queryFn: ({ signal }) => overviewApi.eventLoop(signal),
  refetchInterval: 10_000,
})
const latest = computed(() => loop.data.value?.recent[0] ?? null)
const verdict = computed<{ text: string; tone: Tone }>(() => {
  const value = loop.data.value
  if (!value) return { text: t('common.loading'), tone: 'neutral' }
  if (!value.running) return { text: t('overview.health.idle'), tone: 'neutral' }
  if (latest.value && Date.now() / 1000 - latest.value.at < 600) return { text: t('overview.health.stalled'), tone: 'warning' }
  return { text: t('overview.health.smooth'), tone: 'success' }
})
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <h2 class="text-base font-semibold">{{ t('overview.health.title') }}</h2>
    <Skeleton v-if="loop.isPending.value" :lines="2" />
    <ErrorNote v-else-if="loop.isError.value" :title="t('overview.health.readFailed')" :error="loop.error.value" :retry="loop.refetch" />
    <div v-else-if="loop.data.value" class="flex flex-col gap-2 rounded-lg border border-line bg-surface px-4 py-3">
      <div class="flex items-center gap-2">
        <span class="text-sm font-medium text-ink">{{ t('overview.health.loop') }}</span>
        <Badge :tone="verdict.tone" dot>{{ verdict.text }}</Badge>
      </div>
      <p class="text-xs text-muted tabular">
        {{
          [
            t('overview.health.stalls', { n: formatNumber(loop.data.value.stalls) }, loop.data.value.stalls),
            loop.data.value.pauses ? t('overview.health.pauses', { n: formatNumber(loop.data.value.pauses) }, loop.data.value.pauses) : '',
            t('overview.health.longest', { n: formatNumber(loop.data.value.max_lag_ms) }),
          ]
            .filter(Boolean)
            .join(' · ')
        }}
      </p>
      <details v-if="latest">
        <summary class="cursor-pointer text-xs text-muted hover:text-ink">
          {{
            t('overview.health.latest', {
              task: latest.task ?? t('common.unknown'),
              n: formatNumber(latest.lag_ms),
              ago: formatRelative(latest.at),
            })
          }}
        </summary>
        <CodeBlock :code="latest.stack ?? t('overview.health.noStack')" :max-lines="12" class="mt-1.5" />
      </details>
    </div>
  </section>
</template>
