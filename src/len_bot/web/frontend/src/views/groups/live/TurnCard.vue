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

const summary = computed(() => {
  const turn = props.turn
  const ended = turn.ended ?? now.value.getTime() / 1000
  return [
    labels.channel(turn.channel),
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
    formatDuration(Math.max(0, ended - turn.started) * 1000),
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
    class="my-1.5 rounded-lg border bg-surface transition-colors"
    :class="failed ? 'border-error/40' : expanded ? 'border-line-strong' : 'border-line'"
  >
    <button
      type="button"
      class="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-hover focus-visible:focus-ring"
      :aria-expanded="expanded"
      :aria-label="expanded ? t('groups.live.turn.collapse') : t('groups.live.turn.expand')"
      @click="expanded = !expanded"
    >
      <Spinner v-if="running" :size="15" class="shrink-0 text-primary" />
      <CircleAlert v-else-if="failed" :size="15" class="shrink-0 text-error" aria-hidden="true" />
      <Sparkles v-else :size="15" class="shrink-0 text-primary" aria-hidden="true" />
      <span class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-0.5">
        <strong v-if="running || failed" class="font-medium" :class="failed ? 'text-error' : 'text-primary'">
          {{ labels.status(turn.status) }}
        </strong>
        <span class="min-w-0 truncate text-ink-2 tabular">{{ summary.join(' · ') }}</span>
        <span v-if="tools.length" class="min-w-0 truncate text-muted">{{ list.format(tools) }}</span>
      </span>
      <time class="shrink-0 text-xs text-subtle tabular">
        {{ formatDateTime(turn.started, { timeZone }) }}
      </time>
      <ChevronDown
        :size="16"
        class="shrink-0 text-muted transition-transform duration-200"
        :class="expanded && 'rotate-180'"
        aria-hidden="true"
      />
    </button>
    <div v-if="expanded" class="border-t border-line px-3 py-3">
      <Skeleton v-if="detail.isPending.value" :lines="3" />
      <ErrorNote
        v-else-if="detail.isError.value"
        :title="t('groups.live.turn.readFailed')"
        :error="detail.error.value"
        :retry="detail.refetch"
      />
      <TurnSteps v-else-if="detail.data.value" :detail="detail.data.value" />
      <div v-if="!running" class="mt-2 flex flex-wrap gap-1 border-t border-line pt-2">
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
