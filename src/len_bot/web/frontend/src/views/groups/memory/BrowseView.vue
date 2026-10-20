<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, ChevronRight, FileText, Folder, Plus } from '@lucide/vue'
import { memoryApi, type MemoryScope, type MemoryState } from '../../../api/memory'
import { keys } from '../../../api/query'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import DirectorySummary from './DirectorySummary.vue'
import FileView from './FileView.vue'

const props = defineProps<{
  scene: string
  state: MemoryState
  timeZone: string
  /** A file to open, such as one picked from search results. */
  opening: { scope: MemoryScope; path: string } | null
}>()
const emit = defineEmits<{ dirty: [value: boolean]; opened: [] }>()

const { t } = useI18n()
const wide = useMediaQuery('(min-width: 1280px)')
const scope = ref<MemoryScope>('scene')
const directory = ref('')
const file = ref<string | null>(null)
const creating = ref(false)
const fileDirty = ref(false)
watch(fileDirty, (value) => emit('dirty', value), { immediate: true })

const can = (action: string) => props.state.actions.includes(action)
const writable = computed(() => can('write') && (scope.value === 'scene' || props.state.public_writable))
const scopes = computed(() =>
  (['scene', 'public'] as const).map((value) => ({ value, label: t(`groups.memory.scopes.${value}`) })),
)

const listing = useInfiniteQuery({
  queryKey: computed(() => keys.memory.browse(props.scene, scope.value, directory.value)),
  queryFn: ({ pageParam, signal }) => memoryApi.browse(props.scene, scope.value, directory.value, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page, pages) => (page.has_more ? pages.reduce((sum, item) => sum + item.nodes.length, 0) : undefined),
  enabled: computed(() => can('browse')),
})
const nodes = computed(() => listing.data.value?.pages.flatMap((page) => page.nodes) ?? [])
const crumbs = computed(() => {
  const parts = directory.value ? directory.value.split('/') : []
  return [
    { name: t(`groups.memory.scopes.${scope.value}`), path: '' },
    ...parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join('/') })),
  ]
})

async function leave() {
  return !fileDirty.value || confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') })
}
function reset() {
  file.value = null
  creating.value = false
  fileDirty.value = false
}
async function openDirectory(path: string) {
  if (!(await leave())) return
  directory.value = path
  reset()
}
async function openFile(path: string) {
  if (path === file.value || !(await leave())) return
  fileDirty.value = false
  file.value = path
  creating.value = false
}
const scopeModel = computed({
  get: () => scope.value,
  set: (value: MemoryScope) => void changeScope(value),
})
async function changeScope(value: MemoryScope) {
  if (value === scope.value || !(await leave())) return
  scope.value = value
  directory.value = ''
  reset()
}
async function create() {
  if (!(await leave())) return
  file.value = null
  fileDirty.value = false
  creating.value = true
}
async function close() {
  if (await leave()) reset()
}
function changed(path: string | null) {
  creating.value = false
  fileDirty.value = false
  file.value = path
  void listing.refetch()
}
watch(
  () => props.opening,
  async (value) => {
    if (!value || !(await leave())) return
    scope.value = value.scope
    directory.value = value.path.split('/').slice(0, -1).join('/')
    reset()
    file.value = value.path
    emit('opened')
  },
  { immediate: true },
)
const detail = computed(() => Boolean(file.value || creating.value))
</script>

<template>
  <div class="grid min-w-0 items-start gap-5" :class="wide && 'grid-cols-[280px_minmax(0,1fr)]'">
    <section v-if="wide || !detail" class="flex min-w-0 flex-col gap-3" :aria-label="t('groups.memory.views.browse')">
      <div class="flex items-center gap-2">
        <SegmentedControl
          v-if="state.public_readable"
          v-model="scopeModel"
          :options="scopes"
          size="sm"
          :label="t('groups.memory.scope')"
        />
        <Button v-if="writable" size="sm" variant="ghost" :icon="Plus" class="ml-auto" @click="create">
          {{ t('groups.memory.create') }}
        </Button>
      </div>
      <nav class="flex flex-wrap items-center gap-0.5 text-sm" :aria-label="t('groups.memory.path')">
        <template v-for="(crumb, index) in crumbs" :key="crumb.path">
          <ChevronRight v-if="index > 0" :size="13" class="text-subtle" aria-hidden="true" />
          <button
            type="button"
            class="cursor-pointer rounded-sm px-1 py-0.5 hover:bg-hover focus-visible:focus-ring"
            :class="index === crumbs.length - 1 ? 'font-medium text-ink' : 'text-muted'"
            @click="openDirectory(crumb.path)"
          >
            {{ crumb.name }}
          </button>
        </template>
      </nav>
      <p v-if="!can('browse')" class="text-sm text-muted">{{ t('groups.memory.noBrowse') }}</p>
      <Skeleton v-else-if="listing.isPending.value" :lines="5" />
      <ErrorNote
        v-else-if="listing.isError.value"
        :title="t('groups.memory.readFailed')"
        :error="listing.error.value"
        :retry="listing.refetch"
      />
      <p v-else-if="!nodes.length" class="text-sm text-muted">{{ t('groups.memory.emptyDirectory') }}</p>
      <ul v-else class="flex list-none flex-col">
        <li v-for="node in nodes" :key="node.path">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm hover:bg-hover focus-visible:focus-ring"
            :class="node.path === file ? 'bg-brand-soft text-primary' : 'text-ink'"
            :aria-current="node.path === file ? 'true' : undefined"
            @click="node.is_dir ? openDirectory(node.path) : openFile(node.path)"
          >
            <component
              :is="node.is_dir ? Folder : FileText"
              :size="15"
              class="shrink-0"
              :class="node.path === file ? 'text-primary' : 'text-subtle'"
              aria-hidden="true"
            />
            <span class="min-w-0 flex-1 truncate">{{ node.name }}</span>
          </button>
        </li>
      </ul>
      <Button
        v-if="listing.hasNextPage.value"
        size="sm"
        variant="ghost"
        :loading="listing.isFetchingNextPage.value"
        @click="listing.fetchNextPage()"
      >
        {{ t('groups.memory.more') }}
      </Button>
    </section>

    <section v-if="wide || detail" class="flex min-w-0 flex-col gap-3">
      <Button v-if="!wide && detail" size="sm" variant="ghost" :icon="ArrowLeft" class="self-start" @click="close">
        {{ t('common.back') }}
      </Button>
      <FileView
        v-if="detail"
        :key="`${scope}:${file}:${creating}`"
        :scene="scene"
        :scope="scope"
        :path="file"
        :directory="directory"
        :state="state"
        :time-zone="timeZone"
        @dirty="(value: boolean) => (fileDirty = value)"
        @changed="changed"
        @close="close"
      />
      <DirectorySummary v-else :key="`${scope}:${directory}`" :scene="scene" :scope="scope" :path="directory" :time-zone="timeZone" />
    </section>
  </div>
</template>
