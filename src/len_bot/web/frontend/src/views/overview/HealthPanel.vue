<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { useIntervalFn } from '@vueuse/core'
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
const now = ref(Date.now() / 1000)
useIntervalFn(() => (now.value = Date.now() / 1000), 30_000)
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
  if (latest.value && now.value - latest.value.at < 600)
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
    <h2 class="text-base font-semibold text-ink">{{ t('overview.health.title') }}</h2>
    <div v-if="loop.isPending.value" class="border-y border-line py-3" aria-hidden="true">
      <div class="flex items-center justify-between gap-2">
        <Skeleton width="96px" height="15px" />
        <Skeleton width="52px" height="20px" rounded="rounded-full" />
      </div>
      <div class="mt-2">
        <Skeleton width="150px" height="12px" />
      </div>
    </div>
    <ErrorNote
      v-else-if="loop.isError.value"
      :title="t('overview.health.readFailed')"
      :error="loop.error.value"
      :retry="loop.refetch"
    />
    <div
      v-else-if="loop.data.value || models.length"
      class="flex flex-col divide-y divide-line border-y border-line"
    >
      <div v-if="loop.data.value" class="flex flex-col gap-1.5 py-3">
        <div class="flex items-center justify-between gap-2">
          <span class="text-sm font-medium text-ink">{{ t('overview.health.loop') }}</span>
          <Badge :tone="verdict.tone" dot>{{ verdict.text }}</Badge>
        </div>
        <p class="text-xs text-muted tabular">
          {{
            [
              t(
                'overview.health.stalls',
                { n: formatNumber(loop.data.value.stalls) },
                loop.data.value.stalls,
              ),
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
          <summary
            class="cursor-pointer rounded-sm text-xs text-muted hover:text-ink focus-visible:focus-ring tabular"
          >
            {{
              t('overview.health.latest', {
                task: latest.task ?? t('common.unknown'),
                n: formatNumber(latest.lag_ms),
                ago: formatRelative(latest.at, now),
              })
            }}
          </summary>
          <div class="mt-1.5">
            <CodeBlock :code="latest.stack ?? t('overview.health.noStack')" :max-lines="12" />
          </div>
        </details>
      </div>
      <div v-if="models.length" class="flex flex-col gap-2.5 py-3">
        <span class="text-xs font-medium text-muted">{{ t('overview.health.models') }}</span>
        <ul class="flex list-none flex-col gap-2.5">
          <li v-for="item in models" :key="item.purpose" class="flex flex-col gap-1">
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-medium text-ink">{{ labels.role(item.purpose) }}</span>
              <Badge :tone="item.failing ? 'error' : 'success'" dot>
                {{ item.failing ? t('overview.health.failing') : t('overview.health.working') }}
              </Badge>
            </div>
            <p class="flex flex-wrap gap-x-3 text-xs text-muted tabular">
              <span v-if="item.success">
                {{ t('overview.health.lastSuccess', { ago: formatRelative(item.success.started, now) }) }}
              </span>
              <RouterLink
                v-if="item.failure"
                :to="{
                  name: 'host-logs',
                  query: {
                    level: 'ERROR',
                    scene: item.failure.scene,
                    call: item.failure.id,
                    turn: item.failure.turn_id ?? undefined,
                  },
                }"
                class="text-error hover:underline"
                :title="item.failure.error"
              >
                {{ t('overview.health.lastFailure', { ago: formatRelative(item.failure.started, now) }) }}
              </RouterLink>
            </p>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
