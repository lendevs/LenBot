<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { host } from '../../api/hostStore'
import { overviewApi, type Overview } from '../../api/overview'
import { keys } from '../../api/query'
import { formatNumber, formatRelative } from '../../i18n/format'
import Badge, { type Tone } from '../../ui/Badge.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { useLiveLabels } from '../groups/live/labels'

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
  if (latest.value && Date.now() / 1000 - latest.value.at < 600)
    return { text: t('overview.health.stalled'), tone: 'warning' }
  return { text: t('overview.health.smooth'), tone: 'success' }
})

const labels = useLiveLabels()
/** Each purpose with its latest calls; a failure after the latest success marks it as failing now. */
const models = computed(() =>
  ((host.overview as Overview | null)?.model_health ?? []).map((item) => ({
    ...item,
    failing: Boolean(item.failure && (!item.success || item.failure.id > item.success.id)),
  })),
)
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <h2 class="text-base font-semibold">{{ t('overview.health.title') }}</h2>
    <Skeleton v-if="loop.isPending.value" :lines="2" />
    <ErrorNote
      v-else-if="loop.isError.value"
      :title="t('overview.health.readFailed')"
      :error="loop.error.value"
      :retry="loop.refetch"
    />
    <div
      v-else-if="loop.data.value"
      class="flex flex-col gap-2 rounded-lg border border-line bg-surface px-4 py-3"
    >
      <div class="flex items-center gap-2">
        <span class="text-sm font-medium text-ink">{{ t('overview.health.loop') }}</span>
        <Badge :tone="verdict.tone" dot>{{ verdict.text }}</Badge>
      </div>
      <p class="text-xs text-muted tabular">
        {{
          [
            t('overview.health.stalls', { n: formatNumber(loop.data.value.stalls) }, loop.data.value.stalls),
            loop.data.value.pauses
              ? t(
                  'overview.health.pauses',
                  { n: formatNumber(loop.data.value.pauses) },
                  loop.data.value.pauses,
                )
              : '',
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
    <div v-if="models.length" class="flex flex-col gap-2 rounded-lg border border-line bg-surface px-4 py-3">
      <span class="text-sm font-medium text-ink">{{ t('overview.health.models') }}</span>
      <ul class="flex list-none flex-col gap-2">
        <li v-for="item in models" :key="item.purpose" class="flex flex-col gap-0.5">
          <div class="flex items-center gap-2">
            <span class="text-sm text-ink-2">{{ labels.role(item.purpose) }}</span>
            <Badge :tone="item.failing ? 'error' : 'success'" dot>
              {{ item.failing ? t('overview.health.failing') : t('overview.health.working') }}
            </Badge>
          </div>
          <p class="flex flex-wrap gap-x-3 text-xs text-muted tabular">
            <span v-if="item.success">
              {{ t('overview.health.lastSuccess', { ago: formatRelative(item.success.started) }) }}
            </span>
            <RouterLink
              v-if="item.failure"
              :to="{
                name: 'host-logs',
                query: {
                  scene: item.failure.scene,
                  call: item.failure.id,
                  turn: item.failure.turn_id ?? undefined,
                },
              }"
              class="text-error hover:underline"
              :title="item.failure.error"
            >
              {{ t('overview.health.lastFailure', { ago: formatRelative(item.failure.started) }) }}
            </RouterLink>
          </p>
        </li>
      </ul>
    </div>
  </section>
</template>
