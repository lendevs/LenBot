<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useInfiniteQuery, useQuery } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, Plus, TriangleAlert } from '@lucide/vue'
import { keys } from '../../../api/query'
import { tasksApi, type Task, type TaskFilter } from '../../../api/tasks'
import { formatDateTime } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { groupsTarget } from '../route'
import NewTaskDialog from './NewTaskDialog.vue'
import TaskDetail from './TaskDetail.vue'
import { statusTone } from './labels'

const props = defineProps<{ scene: string; timeZone: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const wide = useMediaQuery('(min-width: 1280px)')

const service = useQuery({ queryKey: keys.tasks.state(), queryFn: ({ signal }) => tasksApi.state(signal) })
const sceneTasks = computed(
  () => service.data.value?.scenes.find((item) => item.scene === props.scene) ?? null,
)
const accepting = computed(() =>
  Boolean(service.data.value?.configured && service.data.value.accepting && sceneTasks.value?.enabled),
)

const filter = ref<TaskFilter>('active')
const filters = computed(() =>
  (['active', 'all', 'done', 'failed', 'cancelled'] as const).map((value) => ({
    value,
    label: t(`groups.tasks.filters.${value}`),
  })),
)
const list = useInfiniteQuery({
  queryKey: computed(() => keys.tasks.list(props.scene, filter.value)),
  queryFn: ({ pageParam, signal }) => tasksApi.list(props.scene, filter.value, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page) => page.next_offset ?? undefined,
})
const rows = computed(() => list.data.value?.pages.flatMap((page) => page.items) ?? [])

const selected = computed(() => {
  const value = route.query.id
  return typeof value === 'string' && /^[1-9][0-9]*$/.test(value) ? Number(value) : null
})
const detailDirty = ref(false)
const creating = ref(false)
const newDirty = ref(false)
watch(
  () => detailDirty.value || newDirty.value,
  (value) => emit('dirty', value),
  { immediate: true },
)

async function open(id: number | null) {
  if (id === selected.value) return
  if (
    detailDirty.value &&
    !(await confirm({ title: t('groups.tasks.unsavedTitle'), confirmLabel: t('common.discard') }))
  )
    return
  detailDirty.value = false
  const { id: _, ...rest } = route.query
  void router.replace({ query: id === null ? rest : { ...rest, id: String(id) } })
}
function created(task: Task) {
  creating.value = false
  newDirty.value = false
  void list.refetch()
  void open(task.id)
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <Skeleton v-if="service.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="service.isError.value"
      :title="t('groups.tasks.readFailed')"
      :error="service.error.value"
      :retry="service.refetch"
    />
    <template v-else-if="service.data.value">
      <div
        v-if="!service.data.value.configured"
        class="flex flex-wrap items-center gap-3 rounded-lg border border-line px-4 py-3 text-sm text-muted"
      >
        <span class="min-w-0 flex-1">{{ t('groups.tasks.notConfigured') }}</span>
        <Button size="sm" :to="{ name: 'host-capabilities', query: { tab: 'tasks' } }">
          {{ t('groups.tasks.toCapabilities') }}
        </Button>
      </div>
      <div
        v-else-if="sceneTasks && !sceneTasks.enabled"
        class="flex flex-wrap items-center gap-3 rounded-lg bg-warning-bg px-4 py-3 text-sm text-warning"
      >
        <TriangleAlert :size="16" aria-hidden="true" />
        <span class="min-w-0 flex-1">{{ t('groups.tasks.sceneOff') }}</span>
        <Button size="sm" :to="groupsTarget(scene, 'settings')">{{ t('groups.tasks.toSettings') }}</Button>
      </div>
      <ErrorNote
        v-if="service.data.value.error"
        :title="t('groups.tasks.serviceError')"
        :error="service.data.value.error"
      />
    </template>

    <div class="grid min-w-0 items-start gap-5" :class="wide && 'grid-cols-[320px_minmax(0,1fr)]'">
      <section
        v-if="wide || selected === null"
        class="flex min-w-0 flex-col gap-3"
        :aria-label="t('groups.tasks.views.tasks')"
      >
        <div class="flex items-center gap-2">
          <div class="w-32"><Select v-model="filter" :options="filters" size="sm" /></div>
          <Button
            v-if="accepting"
            size="sm"
            variant="ghost"
            :icon="Plus"
            class="ml-auto"
            @click="creating = true"
          >
            {{ t('groups.tasks.create') }}
          </Button>
        </div>
        <Skeleton v-if="list.isPending.value" :lines="5" />
        <ErrorNote
          v-else-if="list.isError.value"
          :title="t('groups.tasks.readFailed')"
          :error="list.error.value"
          :retry="list.refetch"
        />
        <EmptyState v-else-if="!rows.length" :title="t('groups.tasks.empty')" compact />
        <ul v-else class="flex list-none flex-col gap-0.5">
          <li v-for="item in rows" :key="item.id">
            <button
              type="button"
              class="flex w-full cursor-pointer flex-col gap-1 rounded-md px-3 py-2 text-left hover:bg-hover focus-visible:focus-ring"
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
      </section>

      <section v-if="wide || selected !== null" class="flex min-w-0 flex-col gap-3">
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
        <TaskDetail
          v-if="selected !== null && service.data.value"
          :id="selected"
          :key="selected"
          :scene="scene"
          :time-zone="timeZone"
          :service="service.data.value"
          :scene-enabled="Boolean(sceneTasks?.enabled)"
          @dirty="(value: boolean) => (detailDirty = value)"
        />
        <EmptyState v-else-if="selected === null" :title="t('groups.tasks.pick')" compact />
      </section>
    </div>

    <NewTaskDialog
      v-if="creating"
      :scene="scene"
      @dirty="(value: boolean) => (newDirty = value)"
      @created="created"
      @close="creating = false"
    />
  </div>
</template>
