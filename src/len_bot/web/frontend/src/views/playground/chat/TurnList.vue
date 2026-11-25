<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { usePreferredReducedMotion } from '@vueuse/core'
import { ChevronDown } from '@lucide/vue'
import { keys } from '../../../api/query'
import { failedTurn } from '../../../api/timeline'
import { chatApi, type ChatSource, type ChatTurn } from '../../../api/trials'
import { formatDateTime, formatDuration, formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import TurnSteps from '../../groups/live/TurnSteps.vue'
import { useLiveLabels } from '../../groups/live/labels'

const props = withDefaults(
  defineProps<{
    source: ChatSource
    turns: ChatTurn[]
    timeZone: string
    speechCounts?: Map<string, number>
    bare?: boolean
    embedded?: boolean
  }>(),
  { speechCounts: undefined, bare: false, embedded: false },
)
const open = defineModel<string | null>('open', { default: null })

const { t } = useI18n()
const labels = useLiveLabels()
const reducedMotion = usePreferredReducedMotion()
const root = ref<HTMLElement>()

const detail = useQuery({
  queryKey: computed(() => keys.chat.steps(props.source.id, open.value ?? '')),
  queryFn: ({ signal }) => chatApi.steps(props.source, open.value!, signal),
  enabled: computed(() => open.value !== null),
})
const tone = (turn: ChatTurn) =>
  turn.ended === null ? 'info' : failedTurn(turn.status) ? 'error' : 'neutral'

function channelOf(turn: ChatTurn): string | null {
  const channel = typeof turn.wake_channel === 'string' ? turn.wake_channel : null
  return channel && channel !== 'unknown' ? labels.channel(channel) : null
}

function speechOf(turn: ChatTurn): string | null {
  const count = props.speechCounts?.get(turn.id) ?? 0
  if (count > 0) return t('groups.live.turn.expressions', { n: count })
  if (turn.first_expression_at != null) return t('groups.live.turn.expressions', { n: 1 })
  if (turn.ended !== null) return t('groups.live.turn.listened')
  return null
}

async function focusTurn(turnId: string) {
  await nextTick()
  const target = root.value?.querySelector<HTMLElement>(`[data-turn="${CSS.escape(turnId)}"]`)
  if (!target) return
  target.scrollIntoView({
    behavior: reducedMotion.value === 'reduce' ? 'auto' : 'smooth',
    block: 'nearest',
  })
  if (reducedMotion.value !== 'reduce') {
    target.animate([{ backgroundColor: 'var(--selected)' }, { backgroundColor: 'transparent' }], {
      duration: 1200,
    })
  }
}

defineExpose({ focusTurn })
</script>

<template>
  <section
    ref="root"
    class="flex min-w-0 flex-col"
    :class="
      bare
        ? '-mx-5 -mt-4 -mb-5'
        : [
            'overflow-hidden rounded-xl border border-line bg-surface',
            embedded ? 'max-h-[min(calc(100dvh-280px),680px)]' : 'max-h-[min(calc(100dvh-230px),780px)]',
          ]
    "
  >
    <header v-if="!bare" class="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
      <h3 class="text-sm font-semibold text-ink">{{ t('playground.turns') }}</h3>
      <Badge v-if="turns.length">
        <span class="tabular">{{ formatNumber(turns.length) }}</span>
      </Badge>
    </header>
    <p v-if="!turns.length" class="px-4 py-6 text-center text-sm text-muted">{{ t('playground.noTurns') }}</p>
    <ul
      v-else
      class="flex min-h-0 flex-1 list-none flex-col divide-y divide-line"
      :class="!bare && 'overflow-y-auto scrollbar-thin'"
    >
      <li v-for="turn in turns" :key="turn.id" :data-turn="turn.id">
        <button
          type="button"
          class="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors hover:bg-hover focus-visible:focus-ring"
          :class="open === turn.id && 'bg-fill/60'"
          :aria-expanded="open === turn.id"
          @click="open = open === turn.id ? null : turn.id"
        >
          <span class="flex min-w-0 flex-1 flex-col gap-0.5">
            <span class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
              <Badge :tone="tone(turn)" dot :pulse="turn.ended === null">
                {{ labels.status(turn.status) }}
              </Badge>
              <span v-if="channelOf(turn)" class="truncate text-xs font-medium text-ink-2">
                {{ channelOf(turn) }}
              </span>
              <span v-if="speechOf(turn)" class="shrink-0 text-xs text-muted tabular">
                <span v-if="channelOf(turn)" class="mr-1 text-subtle" aria-hidden="true">·</span>
                {{ speechOf(turn) }}
              </span>
            </span>
            <span class="flex items-center gap-1.5 text-2xs text-subtle tabular">
              <time>{{ formatDateTime(turn.started, { withSeconds: true, timeZone }) }}</time>
              <template v-if="turn.ended !== null">
                <span aria-hidden="true">·</span>
                <span>{{ formatDuration(Math.max(0, turn.ended - turn.started) * 1000) }}</span>
              </template>
            </span>
          </span>
          <ChevronDown
            :size="15"
            class="shrink-0 text-subtle transition-transform duration-200"
            :class="open === turn.id && 'rotate-180'"
            aria-hidden="true"
          />
        </button>
        <div v-if="open === turn.id" class="animate-fade border-t border-line bg-sidebar/50 px-4 py-3">
          <Skeleton v-if="detail.isPending.value" :lines="3" />
          <ErrorNote
            v-else-if="detail.isError.value"
            :title="t('playground.turnFailed')"
            :error="detail.error.value"
            :retry="detail.refetch"
          />
          <TurnSteps v-else-if="detail.data.value" :detail="detail.data.value" />
        </div>
      </li>
    </ul>
  </section>
</template>
