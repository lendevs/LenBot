<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Eye, LogOut, X } from '@lucide/vue'
import { hostApi, type IntentCondition, type SceneFocus } from '../../../api/host'
import { keys } from '../../../api/query'
import { formatDateTime } from '../../../i18n/format'
import IconButton from '../../../ui/IconButton.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string; timeZone?: string }>()
const { t } = useI18n()
const client = useQueryClient()
const key = computed(() => keys.host.focus(props.scene))

// Intents change inside turns and expire on their own; a short poll keeps the bar current.
const focus = useQuery({
  queryKey: key,
  queryFn: ({ signal }) => hostApi.focus(props.scene, signal),
  refetchInterval: 10_000,
})
const intents = computed(() => focus.data.value?.intents ?? [])
const wrapUp = computed(() => focus.data.value?.wrap_up ?? null)

const drop = useMutation({
  mutationFn: (id: string) => hostApi.dropIntent(props.scene, id),
  onSuccess: (result: SceneFocus) => client.setQueryData(key.value, result),
  onError: (error) =>
    toast.error(t('groups.live.focus.dropFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})

const account = (uid: string) => uid.split(':').slice(1).join(':')
function condition(item: IntentCondition) {
  if (item.type === 'person')
    return t('groups.live.focus.when.person', { who: item.people.map(account).join('、') })
  if (item.type === 'thread') return t('groups.live.focus.when.thread', { id: item.message_id })
  if (item.type === 'open_question')
    return item.keywords?.length
      ? t('groups.live.focus.when.openKeywords', { id: item.message_id, words: item.keywords.join('、') })
      : t('groups.live.focus.when.thread', { id: item.message_id })
  if (item.type === 'topic') return t('groups.live.focus.when.topic', { words: item.keywords.join('、') })
  return t('groups.live.focus.when.at', { n: item.minutes })
}
const conditions = (when: IntentCondition[], match: 'any' | 'all') =>
  when.map(condition).join(t(`groups.live.focus.join.${match}`))
const time = (at: number) => formatDateTime(at, { timeZone: props.timeZone })
</script>

<template>
  <ul
    v-if="intents.length || wrapUp"
    class="flex min-w-0 flex-col divide-y divide-line rounded-lg border border-line bg-surface"
    :aria-label="t('groups.live.focus.label')"
  >
    <li v-for="intent in intents" :key="intent.id" class="flex min-w-0 items-start gap-3 px-3 py-2">
      <Eye :size="16" class="mt-0.5 shrink-0 text-primary" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium text-ink">{{ intent.reason }}</p>
        <p class="text-xs text-muted">
          {{ conditions(intent.when, intent.match) }} ·
          {{ t('groups.live.focus.until', { time: time(intent.until) }) }}
        </p>
      </div>
      <IconButton
        :icon="X"
        size="sm"
        :label="t('groups.live.focus.drop', { reason: intent.reason })"
        :loading="drop.isPending.value && drop.variables.value === intent.id"
        @click="drop.mutate(intent.id)"
      />
    </li>
    <li v-if="wrapUp" class="flex min-w-0 items-center gap-3 px-3 py-2">
      <LogOut :size="16" class="shrink-0 text-muted" aria-hidden="true" />
      <p class="min-w-0 flex-1 truncate text-sm text-ink-2">
        {{
          wrapUp.state === 'closed'
            ? t('groups.live.focus.closed')
            : wrapUp.people.length
              ? t('groups.live.focus.openPeople', { who: wrapUp.people.map(account).join('、') })
              : t('groups.live.focus.open')
        }}
        · {{ t('groups.live.focus.until', { time: time(wrapUp.until) }) }}
      </p>
    </li>
  </ul>
</template>
