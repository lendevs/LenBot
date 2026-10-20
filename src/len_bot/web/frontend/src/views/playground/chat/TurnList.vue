<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ChevronDown } from '@lucide/vue'
import { keys } from '../../../api/query'
import { failedTurn } from '../../../api/timeline'
import { chatApi, type ChatSource, type ChatTurn } from '../../../api/trials'
import { formatDateTime } from '../../../i18n/format'
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
    class="flex max-h-[min(78vh,820px)] min-w-0 flex-col gap-2 overflow-y-auto rounded-xl border border-line bg-surface p-3 scrollbar-thin"
  >
    <h3 class="px-1 text-sm font-semibold text-ink">{{ t('playground.turns') }}</h3>
    <p v-if="!turns.length" class="px-1 text-sm text-muted">{{ t('playground.noTurns') }}</p>
    <ul v-else class="flex list-none flex-col gap-1.5">
      <li
        v-for="turn in turns"
        :key="turn.id"
        :data-turn="turn.id"
        class="overflow-hidden rounded-lg border border-line"
      >
        <button
          type="button"
          class="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm hover:bg-hover focus-visible:focus-ring"
          :aria-expanded="open === turn.id"
          @click="open = open === turn.id ? null : turn.id"
        >
          <Badge :tone="tone(turn)" dot>{{ labels.status(turn.status) }}</Badge>
          <time class="min-w-0 flex-1 truncate text-xs text-muted tabular">
            {{ formatDateTime(turn.started, { withSeconds: true, timeZone }) }}
          </time>
          <ChevronDown
            :size="15"
            class="shrink-0 text-subtle transition-transform"
            :class="open === turn.id && 'rotate-180'"
            aria-hidden="true"
          />
        </button>
        <div v-if="open === turn.id" class="border-t border-line px-3 py-3">
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
