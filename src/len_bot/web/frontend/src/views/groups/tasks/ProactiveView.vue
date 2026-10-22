<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { MessageCirclePlus, PauseCircle } from '@lucide/vue'
import { keys } from '../../../api/query'
import { schedulesApi, type ProactiveWake } from '../../../api/schedules'
import { formatDateTime } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { groupsTarget } from '../route'

const props = defineProps<{ scene: string }>()

const { t, te } = useI18n()
const page = useInfiniteQuery({
  queryKey: computed(() => keys.tasks.proactive(props.scene)),
  queryFn: ({ pageParam, signal }) => schedulesApi.proactive(props.scene, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (value) => value.next_offset ?? undefined,
})
const first = computed(() => page.data.value?.pages[0])
const rows = computed(() => page.data.value?.pages.flatMap((value) => value.items) ?? [])
const at = (seconds: number) => formatDateTime(seconds, { timeZone: first.value?.timezone })

function idle(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  return minutes % 60
    ? t('groups.tasks.proactive.hoursMinutes', { h: Math.floor(minutes / 60), m: minutes % 60 })
    : t('groups.tasks.proactive.hours', { n: minutes / 60 })
}
function outcome(item: ProactiveWake): string {
  const prefix = 'groups.tasks.proactive.outcomes'
  // Counted by arrivals, the outcome is already a sentence from the backend.
  if (item.assessment === 'arrival_count') return item.outcome || t(`${prefix}.running`)
  if (item.outcome) return te(`${prefix}.${item.outcome}`) ? t(`${prefix}.${item.outcome}`) : item.outcome
  return t(item.turn_ended === null ? `${prefix}.running` : `${prefix}.waiting`)
}
</script>

<template>
  <div class="flex max-w-3xl flex-col gap-4">
    <Skeleton v-if="page.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="page.isError.value"
      :title="t('groups.tasks.proactive.readFailed')"
      :error="page.error.value"
      :retry="page.refetch"
    />
    <template v-else-if="first">
      <div
        v-if="!first.settings"
        class="flex flex-wrap items-center gap-3 rounded-lg border border-line px-4 py-3 text-sm text-muted"
      >
        <span class="min-w-0 flex-1">{{ t('groups.tasks.proactive.off') }}</span>
        <Button size="sm" :to="groupsTarget(scene, 'settings')">{{ t('groups.tasks.toSettings') }}</Button>
      </div>
      <div v-else class="flex flex-col gap-1">
        <p class="text-sm text-ink">
          {{
            t('groups.tasks.proactive.rule', {
              idle: idle(first.settings.idle_seconds),
              start: first.settings.start.slice(0, 5),
              end: first.settings.end.slice(0, 5),
            })
          }}
        </p>
        <p class="text-xs text-muted">
          {{
            first.next_at === null
              ? t('groups.tasks.proactive.nextUnknown')
              : t('groups.tasks.proactive.next', { time: at(first.next_at) })
          }}
          <template v-if="first.next_reason">（{{ first.next_reason }}）</template>
        </p>
      </div>
      <div
        v-if="first.pause"
        class="flex items-center gap-2 rounded-lg bg-info-bg px-4 py-3 text-sm text-info"
      >
        <PauseCircle :size="16" aria-hidden="true" />
        {{ t('groups.tasks.proactive.paused', { time: at(first.pause.until) }) }}
      </div>

      <EmptyState
        v-if="!rows.length"
        :icon="MessageCirclePlus"
        :title="t('groups.tasks.proactive.empty')"
        compact
      />
      <ul v-else class="flex list-none flex-col divide-y divide-line rounded-lg border border-line">
        <li v-for="item in rows" :key="item.id" class="flex items-center gap-3 px-4 py-2.5">
          <div class="min-w-0 flex-1">
            <p class="text-sm text-ink">{{ outcome(item) }}</p>
            <p class="text-xs text-muted tabular">{{ at(item.woke_at) }}</p>
          </div>
          <Button size="sm" variant="ghost" :to="{ name: 'host-logs', query: { scene, turn: item.turn_id } }">
            {{ t('groups.tasks.proactive.turn') }}
          </Button>
        </li>
      </ul>
      <Button
        v-if="page.hasNextPage.value"
        size="sm"
        variant="ghost"
        class="self-start"
        :loading="page.isFetchingNextPage.value"
        @click="page.fetchNextPage()"
      >
        {{ t('groups.tasks.more') }}
      </Button>
    </template>
  </div>
</template>
