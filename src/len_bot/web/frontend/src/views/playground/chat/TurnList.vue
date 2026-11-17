<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
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

const props = defineProps<{ source: ChatSource; turns: ChatTurn[]; timeZone: string }>()
const open = defineModel<string | null>('open', { default: null })

const { t } = useI18n()
const labels = useLiveLabels()
const detail = useQuery({
  queryKey: computed(() => keys.chat.steps(props.source.id, open.value ?? '')),
  queryFn: ({ signal }) => chatApi.steps(props.source, open.value!, signal),
  enabled: computed(() => open.value !== null),
})
const tone = (turn: ChatTurn) =>
  turn.ended === null ? 'info' : failedTurn(turn.status) ? 'error' : 'neutral'
</script>

<template>
  <section
    class="flex max-h-[min(calc(100dvh-230px),780px)] min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-surface"
  >
    <header class="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
      <h3 class="text-sm font-semibold text-ink">{{ t('playground.turns') }}</h3>
      <Badge v-if="turns.length">
        <span class="tabular">{{ formatNumber(turns.length) }}</span>
      </Badge>
    </header>
    <p v-if="!turns.length" class="px-4 py-6 text-center text-sm text-muted">{{ t('playground.noTurns') }}</p>
    <ul
      v-else
      class="flex min-h-0 flex-1 list-none flex-col divide-y divide-line overflow-y-auto scrollbar-thin"
    >
      <li v-for="turn in turns" :key="turn.id" :data-turn="turn.id">
        <button
          type="button"
          class="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors hover:bg-hover focus-visible:focus-ring"
          :class="open === turn.id && 'bg-fill/60'"
          :aria-expanded="open === turn.id"
          @click="open = open === turn.id ? null : turn.id"
        >
          <Badge :tone="tone(turn)" dot :pulse="turn.ended === null">{{ labels.status(turn.status) }}</Badge>
          <time class="min-w-0 flex-1 truncate text-xs text-muted tabular">
            {{ formatDateTime(turn.started, { withSeconds: true, timeZone }) }}
          </time>
          <span v-if="turn.ended !== null" class="shrink-0 text-xs text-subtle tabular">
            {{ formatDuration(Math.max(0, turn.ended - turn.started) * 1000) }}
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
