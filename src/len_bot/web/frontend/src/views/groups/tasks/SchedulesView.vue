<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Bell, Plus, TriangleAlert } from '@lucide/vue'
import { keys } from '../../../api/query'
import { personasApi } from '../../../api/personas'
import { schedulesApi, type Schedule, type ScheduleFilter } from '../../../api/schedules'
import { developerDetails } from '../../../composables/useDeveloperMode.js'
import { host } from '../../../api/hostStore'
import { formatDateTime } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { groupsTarget } from '../route'
import RawRecord from './RawRecord.vue'
import ScheduleDialog from './ScheduleDialog.vue'

const props = defineProps<{ scene: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const service = useQuery({ queryKey: keys.tasks.scheduleState(), queryFn: ({ signal }) => schedulesApi.state(signal) })
const settings = computed(() => service.data.value?.scenes.find((item) => item.scene === props.scene) ?? null)
// Tools are allowed per role, on the role's detail page.
const roles = useQuery({ queryKey: keys.personas.all(), queryFn: ({ signal }) => personasApi.library(signal) })
const roleKey = computed(() => {
  const path = (host.state?.scenes ?? []).find((item: { scene: string }) => item.scene === props.scene)?.persona_path
  return roles.data.value?.roles.find((role) => role.path === path)?.key ?? null
})

const filter = ref<ScheduleFilter>('active')
const filters = computed(() =>
  (['active', 'all', 'delivered', 'cancelled'] as const).map((value) => ({
    value,
    label: t(`groups.tasks.schedules.filters.${value}`),
  })),
)
const list = useInfiniteQuery({
  queryKey: computed(() => keys.tasks.schedules(props.scene, filter.value)),
  queryFn: ({ pageParam, signal }) => schedulesApi.list(props.scene, filter.value, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page) => page.next_offset ?? undefined,
})
const rows = computed(() => list.data.value?.pages.flatMap((page) => page.items) ?? [])

const tones: Record<Schedule['status'], Tone> = {
  pending: 'info',
  blocked: 'warning',
  delivered: 'success',
  cancelled: 'neutral',
}
const repeats = (item: Schedule) => item.interval_seconds !== null || item.cron !== null
function cadence(item: Schedule): string {
  const prefix = 'groups.tasks.schedules.cadence'
  if (item.cron !== null) {
    const [minute, hour, , , week] = item.cron.replace(/^cron:/, '').split(' ')
    if (!/^\d+$/.test(hour ?? '') || !/^\d+$/.test(minute ?? '')) return item.cron
    const clock = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`
    if (week === '*') return t(`${prefix}.daily`, { clock })
    if (!/^[0-6](,[0-6])*$/.test(week ?? '')) return item.cron
    const days = week.split(',').map((day) => t(`groups.tasks.schedules.weekdays.${day}`))
    return t(`${prefix}.weekly`, { days: days.join(t(`${prefix}.separator`)), clock })
  }
  const value = item.interval_seconds
  if (value === null) return t(`${prefix}.once`)
  if (value % 86400 === 0) return t(`${prefix}.days`, { n: value / 86400 })
  if (value % 3600 === 0) return t(`${prefix}.hours`, { n: value / 3600 })
  return t(`${prefix}.minutes`, { n: Math.round(value / 60) })
}
function details(item: Schedule): string {
  const time = formatDateTime(item.due_at, { timeZone: item.timezone })
  return [
    cadence(item),
    item.status === 'pending' ? t('groups.tasks.schedules.next', { time }) : time,
    item.requester === null ? t('groups.tasks.schedules.byBot') : t('groups.tasks.schedules.by', { who: item.requester }),
    ...(item.target !== 'self' ? [t('groups.tasks.schedules.remind', { who: item.target })] : []),
  ].join(' · ')
}

const cancel = useMutation({
  mutationFn: (item: Schedule) => schedulesApi.cancel(props.scene, item.id),
  onSuccess: () => toast.success(t('groups.tasks.schedules.cancelled')),
  onError: (error) =>
    toast.error(t('groups.tasks.schedules.cancelFailed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => client.invalidateQueries({ queryKey: ['host', 'schedules'] }),
})
async function ask(item: Schedule) {
  const repeat = repeats(item)
  const sure = await confirm({
    title: t(repeat ? 'groups.tasks.schedules.stopTitle' : 'groups.tasks.schedules.cancelTitle'),
    message: item.note,
    confirmLabel: t(repeat ? 'groups.tasks.schedules.stopConfirm' : 'groups.tasks.schedules.cancelConfirm'),
    tone: 'danger',
  })
  if (sure) cancel.mutate(item)
}

const adding = ref(false)
function added() {
  adding.value = false
  void client.invalidateQueries({ queryKey: ['host', 'schedules'] })
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <ErrorNote
      v-if="service.isError.value"
      :title="t('groups.tasks.schedules.readFailed')"
      :error="service.error.value"
      :retry="service.refetch"
    />
    <div
      v-if="settings && (!settings.enabled || !settings.tool_allowed)"
      class="flex flex-wrap items-center gap-3 rounded-lg bg-warning-bg px-4 py-3 text-sm text-warning"
    >
      <TriangleAlert :size="16" aria-hidden="true" />
      <span class="min-w-0 flex-1">
        {{ t(!settings.enabled ? 'groups.tasks.schedules.off' : 'groups.tasks.schedules.noTool') }}
      </span>
      <Button v-if="!settings.enabled" size="sm" :to="groupsTarget(scene, 'settings')">
        {{ t('groups.tasks.toSettings') }}
      </Button>
      <Button
        v-else-if="roleKey"
        size="sm"
        :to="{ name: 'host-persona', query: { persona: roleKey, tab: 'abilities' } }"
      >
        {{ t('groups.tasks.schedules.toRole') }}
      </Button>
    </div>

    <div class="flex items-center gap-2">
      <div class="w-32"><Select v-model="filter" :options="filters" size="sm" /></div>
      <Button
        size="sm"
        variant="ghost"
        :icon="Plus"
        class="ml-auto"
        :disabled="!settings?.enabled || !settings.tool_allowed"
        @click="adding = true"
      >
        {{ t('groups.tasks.schedules.add') }}
      </Button>
    </div>
    <Skeleton v-if="list.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="list.isError.value"
      :title="t('groups.tasks.schedules.readFailed')"
      :error="list.error.value"
      :retry="list.refetch"
    />
    <EmptyState v-else-if="!rows.length" :icon="Bell" :title="t('groups.tasks.schedules.empty')" compact />
    <ul v-else class="flex list-none flex-col divide-y divide-line rounded-lg border border-line">
      <li v-for="item in rows" :key="item.id" class="flex flex-col gap-1.5 px-4 py-3">
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <p class="text-sm break-words whitespace-pre-wrap text-ink">{{ item.note }}</p>
            <p class="mt-0.5 text-xs text-muted">{{ details(item) }}</p>
          </div>
          <Badge :tone="tones[item.status]" dot size="sm">{{ t(`groups.tasks.schedules.status.${item.status}`) }}</Badge>
          <Button
            v-if="item.status === 'pending' || item.status === 'blocked'"
            size="sm"
            variant="danger-ghost"
            :loading="cancel.isPending.value && cancel.variables.value?.id === item.id"
            @click="ask(item)"
          >
            {{ t('groups.tasks.schedules.cancel') }}
          </Button>
        </div>
        <p v-if="item.reason" class="text-xs text-warning">{{ item.reason }}</p>
        <RawRecord v-if="developerDetails" :label="t('groups.tasks.schedules.raw')" :code="item" />
      </li>
    </ul>
    <Button
      v-if="list.hasNextPage.value"
      size="sm"
      variant="ghost"
      class="self-start"
      :loading="list.isFetchingNextPage.value"
      @click="list.fetchNextPage()"
    >
      {{ t('groups.tasks.more') }}
    </Button>

    <ScheduleDialog
      v-if="adding && settings"
      :scene="scene"
      :timezone="settings.timezone"
      @dirty="(value: boolean) => emit('dirty', value)"
      @added="added"
      @close="adding = false"
    />
  </div>
</template>
