<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { CircleAlert, FolderOpen, TriangleAlert } from '@lucide/vue'
import { keys } from '../../../api/query'
import { tasksApi, type TaskAction, type TaskService } from '../../../api/tasks'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatCompact, formatDateTime, formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import MarkdownText from '../../../ui/MarkdownText.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import FileBrowser from './FileBrowser.vue'
import LivePreview from './LivePreview.vue'
import RawRecord from './RawRecord.vue'
import TaskBrowser from './TaskBrowser.vue'
import TaskEvents from './TaskEvents.vue'
import TaskExtra from './TaskExtra.vue'
import TaskFiles from './TaskFiles.vue'
import TaskQuestion from './TaskQuestion.vue'
import TaskSpace from './TaskSpace.vue'
import { finished, statusTone } from './labels'

const props = defineProps<{
  id: number
  scene: string
  timeZone: string
  service: TaskService
  sceneEnabled: boolean
}>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
/** The first page carries the task; later pages only add events. */
const detail = useInfiniteQuery({
  queryKey: computed(() => keys.tasks.detail(props.scene, props.id)),
  queryFn: ({ pageParam, signal }) => tasksApi.detail(props.scene, props.id, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page) => (page.events.length === 100 ? page.next_after : undefined),
})
const first = computed(() => detail.data.value?.pages[0])
const task = computed(() => first.value?.task)
const events = computed(() => detail.data.value?.pages.flatMap((page) => page.events) ?? [])
const at = (seconds: number) => formatDateTime(seconds, { timeZone: props.timeZone })

const running = computed(() => task.value?.status === 'running' || task.value?.status === 'waiting_input')
const canAppend = computed(() => props.service.accepting && running.value)
const canContinue = computed(
  () =>
    props.service.accepting &&
    props.sceneEnabled &&
    finished(task.value?.status) &&
    !task.value?.workspace_discard_requested,
)
const canCancel = computed(
  () =>
    props.service.configured &&
    (running.value || task.value?.status === 'queued') &&
    (props.service.accepting || task.value?.status === 'queued'),
)
const canAnswer = computed(
  () => props.service.accepting && task.value?.status === 'waiting_input' && Boolean(task.value.question),
)

const append = ref('')
const followUp = ref('')
const answerDirty = ref(false)
watch(
  () => Boolean(append.value.trim() || followUp.value.trim() || answerDirty.value),
  (value) => emit('dirty', value),
  { immediate: true },
)

const act = useMutation({
  mutationFn: (body: TaskAction) => tasksApi.action(props.scene, props.id, body),
  onSuccess: (_, body) => {
    if (body.action === 'append') append.value = ''
    if (body.action === 'continue') followUp.value = ''
    if (body.action === 'answer') answerDirty.value = false
    toast.success(
      t(body.action === 'answer' ? 'groups.tasks.question.done' : `groups.tasks.${body.action}.done`),
    )
  },
  onError: (error) =>
    toast.error(t('groups.tasks.actionFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => client.invalidateQueries({ queryKey: keys.tasks.all() }),
})
async function cancel() {
  const confirmed = await confirm({
    title: t('groups.tasks.cancel.title'),
    message: task.value?.goal,
    confirmLabel: t('groups.tasks.cancel.confirm'),
    tone: 'danger',
  })
  if (confirmed) act.mutate({ action: 'cancel' })
}
const changed = () => void client.invalidateQueries({ queryKey: keys.tasks.all() })
/** The file browser opens on demand; the browser section opens it at the browser's output. */
const filesAt = ref<string | null>(null)
function showFiles(path: string) {
  filesAt.value = filesAt.value === path ? null : path
}

const facts = computed(() => {
  const value = task.value
  if (!value) return []
  return (
    [
      ['deliverable', value.deliverable],
      ['context', value.context],
      ['materials', value.materials.join(t('groups.tasks.schedules.cadence.separator'))],
      ['summary', value.summary],
    ] as const
  ).filter(([, text]) => text)
})
const budget = computed(() => {
  const value = first.value?.budget
  const status = task.value?.status
  if (!value) return null
  if (value.calls <= 0 && status !== 'running' && status !== 'waiting_input') return null
  const totalTokens = value.tokens.input + value.tokens.output
  const cachedTokens = value.tokens.cached ?? 0
  const callsRatio =
    value.max_calls && value.max_calls > 0
      ? Math.min(100, Math.round((value.calls / value.max_calls) * 100))
      : null
  const tokensRatio =
    value.max_tokens && value.max_tokens > 0
      ? Math.min(100, Math.round((totalTokens / value.max_tokens) * 100))
      : null
  return {
    callsText:
      value.max_calls !== null
        ? t('groups.tasks.budget.calls', {
            used: formatNumber(value.calls),
            limit: formatNumber(value.max_calls),
          })
        : t('groups.tasks.budget.callsNoLimit', { used: formatNumber(value.calls) }),
    tokensText:
      value.max_tokens !== null
        ? t('groups.tasks.budget.tokens', {
            used: formatCompact(totalTokens),
            limit: formatCompact(value.max_tokens),
          })
        : t('groups.tasks.budget.tokensNoLimit', { used: formatCompact(totalTokens) }),
    cachedText:
      cachedTokens > 0 ? t('groups.tasks.budget.cached', { cached: formatCompact(cachedTokens) }) : null,
    callsRatio,
    tokensRatio,
  }
})
const watchdogEvents = computed(() => first.value?.watchdog ?? [])
</script>

<template>
  <Skeleton v-if="detail.isPending.value" :lines="8" />
  <ErrorNote
    v-else-if="detail.isError.value"
    :title="t('groups.tasks.readFailed')"
    :error="detail.error.value"
    :retry="detail.refetch"
  />
  <article v-else-if="task && first" class="flex min-w-0 flex-col gap-5">
    <header class="flex flex-col gap-3">
      <div class="flex items-start gap-3">
        <h2
          class="min-w-0 flex-1 text-lg leading-snug font-semibold break-words whitespace-pre-wrap text-ink"
        >
          {{ task.goal }}
        </h2>
        <Badge :tone="statusTone[task.status]" dot :pulse="task.status === 'running'" class="mt-0.5">
          {{ t(`groups.tasks.status.${task.status}`) }}
        </Badge>
      </div>
      <p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
        <span class="tabular">#{{ task.id }}</span>
        <span class="tabular">
          {{ t('groups.tasks.meta', { who: task.requester, time: at(task.created) })
          }}{{ task.ended ? ` · ${t('groups.tasks.ended', { time: at(task.ended) })}` : '' }}
        </span>
        <Button
          v-if="canCancel"
          size="sm"
          variant="danger-ghost"
          class="ml-auto"
          :loading="act.isPending.value && act.variables.value?.action === 'cancel'"
          @click="cancel"
        >
          {{ t('groups.tasks.cancel.action') }}
        </Button>
      </p>
      <div
        v-if="budget"
        class="flex flex-col gap-2 rounded-lg border border-line bg-fill px-3.5 py-2.5 text-xs"
      >
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-muted">
          <span class="font-medium text-ink-2">{{ t('groups.tasks.budget.title') }}</span>
          <span class="tabular text-ink">{{ budget.callsText }}</span>
          <span class="tabular text-ink">{{ budget.tokensText }}</span>
          <span v-if="budget.cachedText" class="tabular text-muted">{{ budget.cachedText }}</span>
        </div>
        <div
          v-if="budget.callsRatio !== null || budget.tokensRatio !== null"
          class="grid gap-2 sm:grid-cols-2"
        >
          <div v-if="budget.callsRatio !== null" class="h-1.5 overflow-hidden rounded-full bg-line">
            <div
              class="h-full rounded-full transition-all duration-300"
              :class="
                budget.callsRatio >= 90 ? 'bg-error' : budget.callsRatio >= 75 ? 'bg-warning' : 'bg-info'
              "
              :style="{ width: `${budget.callsRatio}%` }"
            />
          </div>
          <div v-if="budget.tokensRatio !== null" class="h-1.5 overflow-hidden rounded-full bg-line">
            <div
              class="h-full rounded-full transition-all duration-300"
              :class="
                budget.tokensRatio >= 90 ? 'bg-error' : budget.tokensRatio >= 75 ? 'bg-warning' : 'bg-info'
              "
              :style="{ width: `${budget.tokensRatio}%` }"
            />
          </div>
        </div>
      </div>
      <ul v-if="watchdogEvents.length" class="flex list-none flex-col gap-2">
        <li
          v-for="entry in watchdogEvents"
          :key="entry.id"
          class="flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5 text-sm"
          :class="
            entry.action === 'stop'
              ? 'border-error-line bg-error-bg text-error'
              : 'border-line bg-warning-bg text-warning'
          "
        >
          <CircleAlert v-if="entry.action === 'stop'" :size="16" class="mt-0.5 shrink-0" aria-hidden="true" />
          <TriangleAlert v-else :size="16" class="mt-0.5 shrink-0" aria-hidden="true" />
          <div class="flex min-w-0 flex-1 flex-col gap-0.5">
            <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span class="font-medium">
                {{
                  t(
                    entry.action === 'stop'
                      ? 'groups.tasks.watchdog.stopped'
                      : 'groups.tasks.watchdog.steered',
                  )
                }}
              </span>
              <span class="text-xs text-muted tabular">
                {{ formatDateTime(entry.created, { timeZone, withSeconds: true }) }}
              </span>
            </div>
            <p v-if="entry.detail" class="text-xs break-words whitespace-pre-wrap text-ink-2">
              {{ entry.detail }}
            </p>
          </div>
        </li>
      </ul>
      <dl
        v-if="facts.length"
        class="grid items-baseline gap-x-6 gap-y-2 border-t border-line pt-3 text-sm sm:grid-cols-[auto_minmax(0,1fr)]"
      >
        <template v-for="[key, text] in facts" :key="key">
          <dt class="text-muted">{{ t(`groups.tasks.facts.${key}`) }}</dt>
          <dd v-if="key === 'summary'" class="min-w-0 text-ink"><MarkdownText :text="text ?? ''" /></dd>
          <dd v-else class="min-w-0 break-words whitespace-pre-wrap text-ink">{{ text }}</dd>
        </template>
      </dl>
      <ErrorNote v-if="task.error" :title="t('groups.tasks.failed')" :error="task.error" />
      <RawRecord
        v-if="developerDetails"
        :label="t('groups.tasks.raw')"
        :code="{ ...task, network: first.network, budget: first.budget, watchdog: first.watchdog }"
      />
    </header>

    <LivePreview v-if="running && service.configured" :id="id" :scene="scene" />

    <TaskQuestion
      v-if="task.question"
      :question="task.question"
      :can-answer="canAnswer"
      :busy="act.isPending.value"
      @answer="(body) => act.mutate({ action: 'answer', ...body })"
      @dirty="(value: boolean) => (answerDirty = value)"
    />

    <section v-if="canAppend || canContinue" class="flex flex-col gap-2 border-t border-line pt-5">
      <template v-if="canAppend">
        <label class="text-sm font-medium text-ink" :for="`append-${id}`">
          {{ t('groups.tasks.append.label') }}
        </label>
        <Textarea :id="`append-${id}`" v-model="append" :rows="2" :max-rows="8" />
        <Button
          size="sm"
          class="self-start"
          :disabled="!append.trim()"
          :loading="act.isPending.value && act.variables.value?.action === 'append'"
          @click="act.mutate({ action: 'append', text: append.trim() })"
        >
          {{ t('groups.tasks.append.action') }}
        </Button>
      </template>
      <template v-else>
        <label class="text-sm font-medium text-ink" :for="`continue-${id}`">
          {{ t('groups.tasks.continue.label') }}
        </label>
        <Textarea
          :id="`continue-${id}`"
          v-model="followUp"
          :rows="2"
          :max-rows="8"
          :placeholder="t('groups.tasks.continue.placeholder')"
        />
        <Button
          size="sm"
          class="self-start"
          :disabled="!followUp.trim()"
          :loading="act.isPending.value && act.variables.value?.action === 'continue'"
          @click="act.mutate({ action: 'continue', text: followUp.trim() })"
        >
          {{ t('groups.tasks.continue.action') }}
        </Button>
      </template>
    </section>

    <TaskFiles
      v-if="first.files.length"
      :scene="scene"
      :task-id="id"
      :files="first.files"
      :can-keep="service.configured"
    />
    <TaskBrowser
      :task="task"
      :browser="first.browser"
      :configured="service.configured"
      @files="showFiles('out/browser')"
    />
    <template v-if="service.configured">
      <div class="border-t border-line pt-5">
        <TaskSpace :scene="scene" :task-id="id" :time-zone="timeZone" @changed="changed" />
      </div>
      <section class="flex flex-col gap-2 border-t border-line pt-5">
        <h3 class="flex items-center gap-2 text-sm font-medium text-ink">
          <FolderOpen :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          {{ t('groups.tasks.space.files') }}
          <Button size="sm" variant="ghost" class="ml-auto" @click="filesAt = filesAt === null ? '' : null">
            {{ t(filesAt === null ? 'common.expand' : 'common.collapse') }}
          </Button>
        </h3>
        <FileBrowser
          v-if="filesAt !== null"
          :key="filesAt"
          :scene="scene"
          :task-id="id"
          :time-zone="timeZone"
          :initial-path="filesAt"
          @changed="changed"
        />
      </section>
    </template>
    <TaskEvents
      :scene="scene"
      :task-id="id"
      :events="events"
      :time-zone="timeZone"
      :has-more="detail.hasNextPage.value"
      :loading-more="detail.isFetchingNextPage.value"
      @more="detail.fetchNextPage()"
    />
    <TaskExtra :scene="scene" :task="task" :configured="service.configured" />
  </article>
</template>
