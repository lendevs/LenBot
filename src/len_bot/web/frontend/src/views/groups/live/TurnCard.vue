<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { useNow } from '@vueuse/core'
import { ChevronDown, CircleAlert, Download, ScrollText, Sparkles } from '@lucide/vue'
import { keys } from '../../../api/query'
import { failedTurn, timelineApi, type TimelineTurn } from '../../../api/timeline'
import { currentLocale } from '../../../i18n'
import { formatCompact, formatDateTime, formatDuration } from '../../../i18n/format'
import { useHostEvent } from '../../../realtime/stream'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Spinner from '../../../ui/Spinner.vue'
import TurnSteps from './TurnSteps.vue'
import { useLiveLabels } from './labels'

const props = defineProps<{ turn: TimelineTurn; scene: string; timeZone: string }>()
const expanded = defineModel<boolean>('expanded', { default: false })

const { t } = useI18n()
const labels = useLiveLabels()
const client = useQueryClient()
const running = computed(() => props.turn.ended === null)
const failed = computed(() => failedTurn(props.turn.status))
// The clock only ticks for a running turn's elapsed time.
const { now, pause, resume } = useNow({ interval: 1000, controls: true })
watch(running, (value) => (value ? resume() : pause()), { immediate: true })
const list = computed(() => new Intl.ListFormat(currentLocale.value, { type: 'unit', style: 'short' }))

const channelLabel = computed(() => labels.channel(props.turn.channel))
const metrics = computed(() => {
  const turn = props.turn
  const ended = turn.ended ?? now.value.getTime() / 1000
  return [
    t('groups.live.turn.steps', { n: turn.steps }),
    turn.ended !== null && turn.expressions === 0
      ? t('groups.live.turn.listened')
      : t('groups.live.turn.expressions', { n: turn.expressions }),
    ...(turn.first_expression_wait === null
      ? []
      : [
          t('groups.live.turn.firstWait', {
            time: formatDuration(Math.max(0, turn.first_expression_wait) * 1000),
          }),
        ]),
    t('groups.live.turn.duration', { time: formatDuration(Math.max(0, ended - turn.started) * 1000) }),
    t('groups.live.turn.tokens', {
      input: formatCompact(turn.tokens.input),
      output: formatCompact(turn.tokens.output),
    }),
  ]
})
const tools = computed(() => props.turn.tools.filter((name) => name !== 'say').map(labels.tool))

const queryKey = computed(() => keys.scene.turn(props.scene, props.turn.turn_id))
const detail = useQuery({
  queryKey,
  queryFn: ({ signal }) => timelineApi.turn(props.scene, props.turn.turn_id, signal),
  enabled: expanded,
  staleTime: () => (running.value ? 0 : 30_000),
})
// While the turn runs, each step reads the detail again, at most every 600 ms.
let timer: ReturnType<typeof setTimeout> | undefined
useHostEvent('*', (event) => {
  if (!expanded.value || event.scene !== props.scene || event.turn_id !== props.turn.turn_id) return
  if (!/^turn\.(step|ended)$/.test(event.type) && event.type !== 'message.sent') return
  if (timer) return
  timer = setTimeout(() => {
    timer = undefined
    void client.invalidateQueries({ queryKey: queryKey.value })
  }, 600)
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div
    class="my-2 rounded-lg border transition-colors"
    :class="
      failed
        ? 'border-error/40 bg-surface'
        : running
          ? 'border-info/40 bg-surface'
          : expanded
            ? 'border-line-strong bg-surface shadow-card'
            : 'border-line bg-surface'
    "
  >
    <button
      type="button"
      class="flex w-full cursor-pointer items-start gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-hover focus-visible:focus-ring sm:items-center"
      :class="expanded ? 'rounded-t-lg' : 'rounded-lg'"
      :aria-expanded="expanded"
      :aria-label="expanded ? t('groups.live.turn.collapse') : t('groups.live.turn.expand')"
      @click="expanded = !expanded"
    >
      <span
        class="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-sm sm:mt-0"
        :class="failed ? 'bg-error-bg text-error' : running ? 'bg-info-bg text-info' : 'bg-fill text-ink-2'"
      >
        <Spinner v-if="running" :size="13" />
        <CircleAlert v-else-if="failed" :size="14" aria-hidden="true" />
        <Sparkles v-else :size="14" aria-hidden="true" />
      </span>
      <span class="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-0.5 leading-5">
        <strong class="font-medium text-ink">{{ channelLabel }}</strong>
        <Badge v-if="running || failed" :tone="failed ? 'error' : 'info'" :dot="running" :pulse="running">
          {{ labels.status(turn.status) }}
        </Badge>
        <span
          v-for="metric in metrics"
          :key="metric"
          class="inline-flex items-center gap-1.5 text-xs whitespace-nowrap text-ink-2 tabular"
        >
          <span class="text-subtle" aria-hidden="true">·</span>
          <span>{{ metric }}</span>
        </span>
        <span v-if="tools.length" class="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted">
          <span class="shrink-0 text-subtle" aria-hidden="true">·</span>
          <span class="truncate">{{ list.format(tools) }}</span>
        </span>
      </span>
      <span class="mt-0.5 flex shrink-0 items-center gap-1.5 sm:mt-0">
        <time class="text-xs text-subtle tabular">
          {{ formatDateTime(turn.started, { timeZone }) }}
        </time>
        <ChevronDown
          :size="16"
          class="text-muted transition-transform duration-200 ease-out"
          :class="expanded && 'rotate-180'"
          aria-hidden="true"
        />
      </span>
    </button>
    <div v-if="expanded" class="animate-fade border-t border-line px-3.5 py-3">
      <Skeleton v-if="detail.isPending.value" :lines="3" />
      <ErrorNote
        v-else-if="detail.isError.value"
        :title="t('groups.live.turn.readFailed')"
        :error="detail.error.value"
        :retry="detail.refetch"
      />
      <TurnSteps v-else-if="detail.data.value" :detail="detail.data.value" />
      <div v-if="!running" class="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-2.5">
        <Button
          size="sm"
          variant="ghost"
          :icon="ScrollText"
          :to="{ name: 'host-logs', query: { scene, turn: turn.turn_id } }"
        >
          {{ t('groups.live.turn.logs') }}
        </Button>
        <Button size="sm" variant="ghost" :icon="Download" :href="timelineApi.exportUrl(scene, turn.turn_id)">
          {{ t('groups.live.turn.export') }}
        </Button>
      </div>
    </div>
  </div>
</template>
