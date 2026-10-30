<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, FolderOpen, Plus, X } from '@lucide/vue'
import { keys } from '../../../api/query'
import {
  storageApi,
  type CleanupOperation,
  type EnvironmentFilter,
  type ResourceEntry,
  type ResourceInput,
  type StorageFilter,
  type StorageRow,
} from '../../../api/resources'
import { tasksApi, type Task } from '../../../api/tasks'
import { formatBytes, formatDateTime } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import CleanupDialog from './CleanupDialog.vue'
import FileBrowser from './FileBrowser.vue'
import NewTaskDialog from './NewTaskDialog.vue'
import TaskSpace from './TaskSpace.vue'
import { statusTone } from './labels'

const props = defineProps<{ scene: string; timeZone: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const wide = useMediaQuery('(min-width: 1280px)')

const service = useQuery({ queryKey: keys.tasks.state(), queryFn: ({ signal }) => tasksApi.state(signal) })
const accepting = computed(() => {
  const value = service.data.value
  return Boolean(
    value?.configured && value.accepting && value.scenes.find((item) => item.scene === props.scene)?.enabled,
  )
})
const pool = useQuery({ queryKey: keys.tasks.pool(), queryFn: ({ signal }) => storageApi.pool(signal) })

const status = ref<StorageFilter>('all')
const environment = ref<EnvironmentFilter>('all')
const since = ref('')
const until = ref('')
const measure = ref(false)
const statuses = computed(() =>
  (['all', 'active', 'done', 'failed', 'cancelled'] as const).map((value) => ({
    value,
    label: t(`groups.tasks.filters.${value}`),
  })),
)
const environments = computed(() =>
  (['all', 'retained', 'discarded'] as const).map((value) => ({
    value,
    label: t(`groups.tasks.space.environments.${value}`),
  })),
)
/** Start of a picked day in the browser's zone; `until` includes its whole day. */
const day = (value: string, next = false) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const date = new Date(`${value}T00:00:00`)
  if (next) date.setDate(date.getDate() + 1)
  return date.getTime() / 1000
}
const query = computed(() => ({
  status: status.value,
  environment: environment.value,
  since: day(since.value),
  before: day(until.value, true),
  measure: measure.value,
}))
const rangeError = computed(() =>
  query.value.since !== null && query.value.before !== null && query.value.since >= query.value.before
    ? t('groups.tasks.space.rangeInvalid')
    : null,
)
const list = useInfiniteQuery({
  queryKey: computed(() => keys.tasks.usage(props.scene, query.value)),
  queryFn: ({ pageParam, signal }) => storageApi.list(props.scene, query.value, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page) => page.next_offset ?? undefined,
  enabled: computed(() => !rangeError.value),
})
const rows = computed(() => list.data.value?.pages.flatMap((page) => page.items) ?? [])
function remeasure() {
  if (measure.value) void list.refetch()
  else measure.value = true
}
function usage(item: StorageRow): string | null {
  if (!item.roots) return null
  return item.roots
    .map(
      (root) =>
        `${t(`groups.tasks.space.roots.${root.kind}`)} ${root.usage ? formatBytes(root.usage.allocated_bytes) : '—'}`,
    )
    .join(' · ')
}

const checked = ref<number[]>([])
watch([() => props.scene, status, environment, since, until], () => (checked.value = []))
const cleanable = computed(() => rows.value.filter((item) => item.cleanable).map((item) => item.id))
const allChecked = computed(() =>
  cleanable.value.length && cleanable.value.every((id) => checked.value.includes(id))
    ? true
    : checked.value.length
      ? 'indeterminate'
      : false,
)
function checkAll(on: boolean) {
  checked.value = on ? [...cleanable.value] : []
}
function check(id: number, on: boolean) {
  checked.value = on ? [...checked.value, id] : checked.value.filter((item) => item !== id)
}
const cleaning = ref<CleanupOperation | null>(null)
function cleaned() {
  checked.value = []
  void client.invalidateQueries({ queryKey: keys.tasks.all() })
}

const selected = computed(() => {
  const value = route.query.id
  return typeof value === 'string' && /^[1-9][0-9]*$/.test(value) ? Number(value) : null
})
const selectedRow = computed(() => rows.value.find((item) => item.id === selected.value))
/** Narrow screens show the list until something is opened; `id=shared` opens the shared materials. */
const opened = computed(() => selected.value !== null || route.query.id === 'shared')
function open(id: number | 'shared' | null) {
  const { id: _, ...rest } = route.query
  void router.replace({ query: id === null ? rest : { ...rest, id: String(id) } })
}

const picks = ref<ResourceInput[]>([])
const same = (a: ResourceInput['reference'], b: ResourceInput['reference']) =>
  a.scope === b.scope &&
  a.task_id === b.task_id &&
  a.path === b.path &&
  (a.file_id ?? null) === (b.file_id ?? null)
function pick(entry: ResourceEntry) {
  if (!picks.value.some((item) => same(item.reference, entry.reference)))
    picks.value.push({ reference: { ...entry.reference }, name: entry.name })
}
const creating = ref(false)
const newDirty = ref(false)
watch(
  () => picks.value.length > 0 || newDirty.value,
  (value) => emit('dirty', value),
  { immediate: true },
)
async function clearPicks() {
  if (await confirm({ title: t('groups.tasks.space.clearPicks'), confirmLabel: t('common.discard') }))
    picks.value = []
}
function created(task: Task) {
  creating.value = false
  newDirty.value = false
  void client.invalidateQueries({ queryKey: keys.tasks.all() })
  void toTask(task.id, true)
}
/** The tasks view; the tab switch skips the workbench's own unsaved check, so picks are confirmed here. */
async function toTask(id: number, done = false) {
  if (
    !done &&
    picks.value.length &&
    !(await confirm({ title: t('groups.tasks.space.clearPicks'), confirmLabel: t('common.discard') }))
  )
    return
  picks.value = []
  emit('dirty', false)
  void router.replace({ query: { id: String(id) } })
}
</script>

<template>
  <div
    v-if="service.data.value && !service.data.value.configured"
    class="flex flex-wrap items-center gap-3 rounded-lg border border-line px-4 py-3 text-sm text-muted"
  >
    <span class="min-w-0 flex-1">{{ t('groups.tasks.notConfigured') }}</span>
    <Button size="sm" :to="{ name: 'host-capabilities', query: { tab: 'tasks' } }">
      {{ t('groups.tasks.toCapabilities') }}
    </Button>
  </div>
  <div v-else class="flex flex-col gap-4">
    <ErrorNote
      v-if="pool.isError.value"
      :title="t('groups.tasks.space.poolFailed')"
      :error="pool.error.value"
    />
    <div
      v-else-if="pool.data.value?.usage"
      class="flex flex-col gap-1.5 rounded-lg border border-line px-4 py-3"
    >
      <div class="flex flex-wrap items-baseline gap-x-3 text-sm">
        <span class="font-medium text-ink">{{ t('groups.tasks.space.pool') }}</span>
        <span class="tabular text-ink-2">
          {{
            t('groups.tasks.space.poolUsed', {
              used: formatBytes(pool.data.value.usage.used_bytes),
              limit: formatBytes(pool.data.value.usage.limit_bytes),
              available: formatBytes(pool.data.value.usage.available_bytes),
            })
          }}
        </span>
      </div>
      <div class="h-1.5 overflow-hidden rounded-full bg-code" role="presentation">
        <div
          class="h-full rounded-full bg-primary"
          :style="{
            width: `${Math.min(100, (100 * pool.data.value.usage.used_bytes) / Math.max(1, pool.data.value.usage.limit_bytes))}%`,
          }"
        />
      </div>
    </div>
    <div
      v-else-if="pool.data.value?.disk"
      class="flex flex-wrap items-baseline gap-x-3 rounded-lg border border-line px-4 py-3 text-sm"
    >
      <span class="font-medium text-ink">{{ t('groups.tasks.space.disk') }}</span>
      <span class="tabular text-ink-2">
        {{ t('groups.tasks.space.diskFree', { free: formatBytes(pool.data.value.disk.free_bytes) }) }}
      </span>
      <span v-if="pool.data.value.disk.free_bytes < pool.data.value.disk.stop_bytes" class="text-error">
        {{ t('groups.tasks.space.diskStopped') }}
      </span>
      <span
        v-else-if="pool.data.value.disk.free_bytes < pool.data.value.disk.reserve_bytes"
        class="text-warning"
      >
        {{ t('groups.tasks.space.diskPaused') }}
      </span>
    </div>

    <div class="grid min-w-0 items-start gap-5" :class="wide && 'grid-cols-[340px_minmax(0,1fr)]'">
      <section
        v-if="wide || !opened"
        class="flex min-w-0 flex-col gap-3"
        :aria-label="t('groups.tasks.views.resources')"
      >
        <button
          type="button"
          class="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm hover:bg-hover focus-visible:focus-ring"
          :class="
            route.query.id === 'shared' || (wide && selected === null)
              ? 'bg-brand-soft text-primary'
              : 'text-ink'
          "
          @click="open('shared')"
        >
          <FolderOpen :size="16" aria-hidden="true" />
          {{ t('groups.tasks.space.shared') }}
        </button>
        <div class="grid grid-cols-2 gap-2">
          <Select v-model="status" :options="statuses" size="sm" />
          <Select v-model="environment" :options="environments" size="sm" />
        </div>
        <details class="text-sm">
          <summary class="cursor-pointer text-xs font-medium text-muted hover:text-ink">
            {{ t('groups.tasks.space.range') }}
          </summary>
          <div class="mt-2 grid grid-cols-2 gap-2">
            <Field :label="t('groups.tasks.space.since')">
              <Input v-model="since" type="date" size="sm" />
            </Field>
            <Field :label="t('groups.tasks.space.until')" :error="rangeError">
              <Input v-model="until" type="date" size="sm" />
            </Field>
          </div>
        </details>
        <div class="flex min-h-8 items-center gap-2">
          <label
            v-if="cleanable.length"
            class="flex min-w-0 cursor-pointer items-center gap-2 pl-3 text-xs text-muted"
          >
            <Checkbox :model-value="allChecked" @update:model-value="(on) => checkAll(on === true)" />
            {{ t('groups.tasks.space.checkAll') }}
          </label>
          <Button
            size="sm"
            variant="ghost"
            class="ml-auto shrink-0"
            :loading="list.isFetching.value && measure"
            @click="remeasure"
          >
            {{ t(measure ? 'groups.tasks.space.remeasure' : 'groups.tasks.space.measure') }}
          </Button>
        </div>

        <Skeleton v-if="list.isPending.value && !rangeError" :lines="5" />
        <ErrorNote
          v-else-if="list.isError.value"
          :title="t('groups.tasks.readFailed')"
          :error="list.error.value"
          :retry="list.refetch"
        />
        <EmptyState v-else-if="!rows.length && !rangeError" :title="t('groups.tasks.empty')" compact />
        <ul v-else class="flex list-none flex-col gap-0.5">
          <li v-for="item in rows" :key="item.id" class="flex items-start gap-1">
            <span class="pt-2.5 pl-3">
              <Checkbox
                :model-value="checked.includes(item.id)"
                :disabled="!item.cleanable"
                :aria-label="t('groups.tasks.space.check', { id: item.id })"
                @update:model-value="(on) => check(item.id, on === true)"
              />
            </span>
            <button
              type="button"
              class="flex min-w-0 flex-1 cursor-pointer flex-col gap-1 rounded-md px-2 py-2 text-left hover:bg-hover focus-visible:focus-ring"
              :class="item.id === selected && 'bg-brand-soft'"
              :aria-current="item.id === selected ? 'true' : undefined"
              @click="open(item.id)"
            >
              <span class="line-clamp-2 text-sm" :class="item.id === selected ? 'text-primary' : 'text-ink'">
                {{ item.goal }}
              </span>
              <span class="flex items-center gap-2 text-xs text-muted">
                <span class="tabular">#{{ item.id }}</span>
                <span class="tabular">{{ formatDateTime(item.created, { timeZone }) }}</span>
                <Badge :tone="statusTone[item.status]" dot size="sm" class="ml-auto">
                  {{ t(`groups.tasks.status.${item.status}`) }}
                </Badge>
              </span>
              <span class="text-xs text-muted">
                {{ t(`groups.tasks.space.continuation.${item.continuation}`) }}
              </span>
              <span v-if="usage(item)" class="tabular text-xs text-muted">{{ usage(item) }}</span>
              <span v-if="item.usage_error" class="text-xs break-all text-error">{{ item.usage_error }}</span>
            </button>
          </li>
        </ul>
        <Button
          v-if="list.hasNextPage.value"
          size="sm"
          variant="ghost"
          :loading="list.isFetchingNextPage.value"
          @click="list.fetchNextPage()"
        >
          {{ t('groups.tasks.more') }}
        </Button>
        <div
          v-if="checked.length"
          class="sticky bottom-3 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface-raised px-3 py-2 shadow-float"
        >
          <span class="text-sm text-ink">
            {{ t('groups.tasks.space.checked', { n: checked.length }) }}
            <span v-if="checked.length > 100" class="text-warning">
              · {{ t('groups.tasks.space.tooManyChecked') }}
            </span>
          </span>
          <div class="ml-auto flex gap-1">
            <Button size="sm" :disabled="checked.length > 100" @click="cleaning = 'temporary'">
              {{ t('groups.tasks.space.cleanup.temporary') }}
            </Button>
            <Button
              size="sm"
              variant="danger-ghost"
              :disabled="checked.length > 100"
              @click="cleaning = 'environment'"
            >
              {{ t('groups.tasks.space.cleanup.environment') }}
            </Button>
          </div>
        </div>
      </section>

      <section v-if="wide || opened" class="flex min-w-0 flex-col gap-5">
        <Button
          v-if="!wide"
          size="sm"
          variant="ghost"
          :icon="ArrowLeft"
          class="self-start"
          @click="open(null)"
        >
          {{ t('common.back') }}
        </Button>
        <div
          v-if="picks.length"
          class="flex flex-col gap-2 rounded-lg border border-line bg-brand-soft px-4 py-3"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-medium text-ink">
              {{ t('groups.tasks.space.picks', { n: picks.length }) }}
            </span>
            <div class="ml-auto flex gap-1">
              <Button size="sm" variant="ghost" @click="clearPicks">
                {{ t('groups.tasks.space.clear') }}
              </Button>
              <Button
                size="sm"
                variant="primary"
                :icon="Plus"
                :disabled="!accepting"
                @click="creating = true"
              >
                {{ t('groups.tasks.space.createWith') }}
              </Button>
            </div>
          </div>
          <ul class="flex list-none flex-wrap gap-1.5">
            <li
              v-for="(item, index) in picks"
              :key="index"
              class="flex max-w-full items-center gap-1 rounded-md bg-surface px-2 py-1 text-xs text-ink-2"
            >
              <span class="truncate">{{ item.name }}</span>
              <button
                type="button"
                class="shrink-0 cursor-pointer rounded text-subtle hover:text-ink"
                :aria-label="t('ui.combobox.remove', { name: item.name })"
                @click="picks.splice(index, 1)"
              >
                <X :size="12" aria-hidden="true" />
              </button>
            </li>
          </ul>
        </div>

        <template v-if="selected !== null">
          <div class="flex items-start gap-3">
            <h2 class="min-w-0 flex-1 text-lg font-semibold break-words text-ink">
              {{ selectedRow?.goal ?? `#${selected}` }}
            </h2>
            <Button size="sm" variant="ghost" @click="toTask(selected)">
              {{ t('groups.tasks.space.toTask') }}
            </Button>
          </div>
          <TaskSpace :key="`space-${selected}`" :scene="scene" :task-id="selected" :time-zone="timeZone" />
          <FileBrowser
            :key="`files-${selected}`"
            :scene="scene"
            :task-id="selected"
            :time-zone="timeZone"
            pickable
            @pick="pick"
          />
        </template>
        <template v-else-if="wide || route.query.id === 'shared'">
          <h2 class="text-lg font-semibold text-ink">{{ t('groups.tasks.space.shared') }}</h2>
          <FileBrowser :scene="scene" :task-id="null" :time-zone="timeZone" pickable @pick="pick" />
        </template>
      </section>
    </div>

    <CleanupDialog
      v-if="cleaning"
      :scene="scene"
      :ids="checked"
      :operation="cleaning"
      :time-zone="timeZone"
      @done="cleaned"
      @close="cleaning = null"
    />
    <NewTaskDialog
      v-if="creating"
      :scene="scene"
      :resources="picks"
      @dirty="(value: boolean) => (newDirty = value)"
      @created="created"
      @close="creating = false"
    />
  </div>
</template>
