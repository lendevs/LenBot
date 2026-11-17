<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useIntervalFn } from '@vueuse/core'
import { Activity as ActivityIcon } from '@lucide/vue'
import type { Overview } from '../../api/overview'
import { formatRelative } from '../../i18n/format'
import { groupLabel, groupSecondaryId } from '../../layouts/shell/scenes'
import { useHostEvent, type HostEvent } from '../../realtime/stream'
import Avatar from '../../ui/Avatar.vue'
import Badge, { type Tone } from '../../ui/Badge.vue'
import EmptyState from '../../ui/EmptyState.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { useLiveLabels } from '../groups/live/labels'
import { groupsTarget } from '../groups/route'

interface Entry {
  key: string
  kind: 'turn' | 'send' | 'task'
  scene: string
  at: number
  status: string
  /** What was said, for sends; the task goal, for tasks. */
  text?: string
  channel?: string
  task?: number
  /** Whether an ended turn sent anything; unknown while it runs. */
  spoke?: boolean
}

const props = defineProps<{ overview: Overview | null }>()

const { t } = useI18n()
const labels = useLiveLabels()
const LIMIT = 30

// Relative times move on without new events, and never read as later than now.
const now = ref(Date.now() / 1000)
useIntervalFn(() => (now.value = Date.now() / 1000), 30_000)

/** Turns and sends seen on the event stream since the page opened; newest first. */
const live = ref<Entry[]>([])
function put(entry: Entry) {
  now.value = Math.max(Date.now() / 1000, entry.at)
  const index = live.value.findIndex((item) => item.key === entry.key)
  if (index === -1) live.value = [entry, ...live.value].slice(0, LIMIT)
  else live.value[index] = { ...live.value[index]!, ...entry, at: live.value[index]!.at }
}
const sceneOf = (event: HostEvent) => event.scene ?? ''
useHostEvent('turn.started', (event) =>
  put({
    key: `turn:${String(event.turn_id)}`,
    kind: 'turn',
    scene: sceneOf(event),
    at: event.at,
    status: 'running',
    channel: typeof event.channel === 'string' ? event.channel : undefined,
  }),
)
useHostEvent('turn.ended', (event) =>
  put({
    key: `turn:${String(event.turn_id)}`,
    kind: 'turn',
    scene: sceneOf(event),
    at: event.at,
    status: String(event.status),
    spoke: typeof event.expressions === 'number' ? event.expressions > 0 : undefined,
  }),
)
useHostEvent('message.sent', (event) =>
  put({
    key: `send:${sceneOf(event)}:${String(event.message_seq)}`,
    kind: 'send',
    scene: sceneOf(event),
    at: event.at,
    status: String(event.status),
    text: typeof event.summary === 'string' ? event.summary : undefined,
  }),
)

// Before the page opened: the overview lists recent turns, ended tasks and sends that failed.
const entries = computed(() => {
  const seen = new Set(live.value.map((item) => item.key))
  const earlier: Entry[] = (props.overview?.activity ?? []).map((item) => ({
    key: item.kind === 'send' ? `send:${item.scene}:${item.id}` : `${item.kind}:${item.id}`,
    kind: item.kind,
    scene: item.scene,
    at: item.at,
    status: item.status,
    text: item.goal,
    task: item.kind === 'task' ? Number(item.id) : undefined,
    spoke: item.spoke,
  }))
  return [...live.value, ...earlier.filter((item) => !seen.has(item.key))]
    .sort((a, b) => b.at - a.at)
    .slice(0, LIMIT)
})

const turnTones: Record<string, Tone> = {
  running: 'info',
  settled: 'success',
  error: 'error',
  timeout: 'error',
  interrupted: 'warning',
  step_limit: 'warning',
  send_failed: 'error',
  cancelled: 'neutral',
}
const sendTones: Record<string, Tone> = { sent: 'success', simulated: 'neutral', failed: 'error' }
function describe(entry: Entry) {
  if (entry.kind === 'turn') {
    const listened = entry.status !== 'running' && entry.spoke === false
    const channel = entry.channel && labels.channel(entry.channel)
    return {
      text: listened
        ? channel
          ? t('overview.feed.listenedFrom', { channel })
          : t('overview.feed.listened')
        : channel
          ? t('overview.feed.turnFrom', { channel })
          : t('overview.feed.turn'),
      status: labels.status(entry.status),
      tone: turnTones[entry.status] ?? 'neutral',
      to: groupsTarget(entry.scene, 'live'),
    }
  }
  if (entry.kind === 'send') {
    return {
      text: entry.text ? t('overview.feed.said', { text: entry.text }) : t('overview.feed.send'),
      status: t(`overview.feed.sendStatus.${sendTones[entry.status] ? entry.status : 'unconfirmed'}`),
      tone: sendTones[entry.status] ?? 'warning',
      to: groupsTarget(entry.scene, 'live'),
    }
  }
  return {
    text: t('overview.feed.task', { goal: entry.text ?? '' }),
    status: t(
      `overview.feed.taskStatus.${entry.status === 'failed' ? 'failed' : entry.status === 'cancelled' ? 'cancelled' : 'done'}`,
    ),
    tone: (entry.status === 'failed' ? 'error' : 'neutral') as Tone,
    to: groupsTarget(entry.scene, 'tasks', entry.task === undefined ? {} : { id: String(entry.task) }),
  }
}
const rows = computed(() => entries.value.map((entry) => ({ entry, info: describe(entry) })))
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <h2 class="text-base font-semibold text-ink">{{ t('overview.feed.title') }}</h2>
    <div
      v-if="!overview && !live.length"
      class="flex flex-col divide-y divide-line border-y border-line"
      aria-hidden="true"
    >
      <div v-for="n in 3" :key="n" class="flex items-center gap-3 py-3">
        <Skeleton width="30px" height="30px" rounded="rounded-md" />
        <div class="flex min-w-0 flex-1 flex-col gap-1.5">
          <Skeleton width="62%" height="14px" />
          <Skeleton width="28%" height="12px" />
        </div>
        <Skeleton width="52px" height="20px" rounded="rounded-full" />
      </div>
    </div>
    <div v-else-if="!rows.length" class="border-y border-line">
      <EmptyState :icon="ActivityIcon" :title="t('overview.feed.empty')" compact />
    </div>
    <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
      <li v-for="{ entry, info } in rows" :key="entry.key">
        <RouterLink
          :to="info.to"
          class="link-plain -mx-2 flex min-w-0 items-center gap-3 rounded-md px-2 py-2.5 transition-colors hover:bg-hover focus-visible:focus-ring"
        >
          <Avatar :name="groupLabel(entry.scene)" shape="square" :size="30" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm text-ink">
              <span class="font-medium">{{ groupLabel(entry.scene) }}</span>
              <span class="mx-1.5 text-subtle" aria-hidden="true">·</span>
              <span class="text-ink-2">{{ info.text }}</span>
            </span>
            <span class="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-muted tabular">
              <span v-if="groupSecondaryId(entry.scene)" class="truncate font-mono text-subtle">
                {{ groupSecondaryId(entry.scene) }}
              </span>
              <span v-if="groupSecondaryId(entry.scene)" aria-hidden="true">·</span>
              <span class="shrink-0">{{ formatRelative(entry.at, now) }}</span>
            </span>
          </span>
          <Badge :tone="info.tone" :dot="entry.status === 'running'" :pulse="entry.status === 'running'">
            {{ info.status }}
          </Badge>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
