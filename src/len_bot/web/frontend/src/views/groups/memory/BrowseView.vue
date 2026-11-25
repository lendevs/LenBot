<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, ChevronRight, FileText, Folder, FolderOpen, Lock, Plus, Search } from '@lucide/vue'
import { memoryApi, type MemoryNode, type MemoryScope, type MemoryState } from '../../../api/memory'
import { keys } from '../../../api/query'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import DirectorySummary from './DirectorySummary.vue'
import FileView from './FileView.vue'

const props = defineProps<{
  scene: string
  scope: MemoryScope
  state: MemoryState
  timeZone: string
  /** A file to open, such as one picked from search results. */
  opening: { scope: MemoryScope; path: string } | null
}>()
const emit = defineEmits<{ dirty: [value: boolean]; opened: [] }>()

const { t } = useI18n()
const wide = useMediaQuery('(min-width: 1024px)')
const scope = computed(() => props.scope)
const directory = ref('')
const filter = ref('')
const file = ref<string | null>(null)
const creating = ref(false)
const fileDirty = ref(false)
watch(fileDirty, (value) => emit('dirty', value), { immediate: true })

const can = (action: string) => props.state.actions.includes(action)
const writable = computed(() => can('write') && (scope.value === 'scene' || props.state.public_writable))

const listing = useInfiniteQuery({
  queryKey: computed(() => keys.memory.browse(props.scene, scope.value, directory.value)),
  queryFn: ({ pageParam, signal }) =>
    memoryApi.browse(props.scene, scope.value, directory.value, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page, pages) =>
    page.has_more ? pages.reduce((sum, item) => sum + item.nodes.length, 0) : undefined,
  enabled: computed(() => can('browse')),
})
const nodes = computed(() => listing.data.value?.pages.flatMap((page) => page.nodes) ?? [])
const showFilter = computed(() => nodes.value.length >= 8 || filter.value !== '')
const filteredNodes = computed(() => {
  const keyword = filter.value.trim().toLowerCase()
  if (!keyword) return nodes.value
  return nodes.value.filter(
    (node) => node.name.toLowerCase().includes(keyword) || node.path.toLowerCase().includes(keyword),
  )
})
const isReadOnly = (node: MemoryNode) =>
  Boolean(node.access && /^(r|ro|read|read[-_]?only)$/i.test(node.access))

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
  filter.value = ''
  reset()
}
async function openFile(path: string) {
  if (path === file.value || !(await leave())) return
  fileDirty.value = false
  file.value = path
  creating.value = false
}
watch(scope, () => {
  directory.value = ''
  filter.value = ''
  reset()
})
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
    if (!value) return
    if (!(await leave())) {
      emit('opened')
      return
    }
    directory.value = value.path.split('/').slice(0, -1).join('/')
    filter.value = ''
    reset()
    file.value = value.path
    emit('opened')
  },
  { immediate: true },
)
const detail = computed(() => Boolean(file.value || creating.value))
const split = computed(() => wide.value && nodes.value.length > 0)
</script>

<template>
  <div class="grid min-w-0 items-start gap-6" :class="split && 'grid-cols-[272px_minmax(0,1fr)]'">
    <section
      v-if="split || !detail"
      class="flex min-w-0 flex-col gap-3"
      :class="split && 'border-r border-line pr-5'"
      :aria-label="t('groups.memory.views.browse')"
    >
      <div v-if="crumbs.length > 1 || (writable && nodes.length)" class="flex flex-wrap items-center gap-2">
        <nav
          v-if="crumbs.length > 1"
          class="flex min-w-0 flex-wrap items-center gap-0.5 text-sm"
          :aria-label="t('groups.memory.path')"
        >
          <template v-for="(crumb, index) in crumbs" :key="crumb.path">
            <ChevronRight v-if="index > 0" :size="13" class="shrink-0 text-subtle" aria-hidden="true" />
            <button
              type="button"
              class="max-w-44 cursor-pointer truncate rounded-sm px-1 py-0.5 transition-colors hover:bg-hover focus-visible:focus-ring"
              :class="index === crumbs.length - 1 ? 'font-medium text-ink' : 'text-muted hover:text-ink'"
              @click="openDirectory(crumb.path)"
            >
              {{ crumb.name }}
            </button>
          </template>
        </nav>
        <Button
          v-if="writable && nodes.length"
          size="sm"
          variant="ghost"
          :icon="Plus"
          class="ml-auto"
          @click="create"
        >
          {{ t('groups.memory.create') }}
        </Button>
      </div>
      <Input
        v-if="showFilter"
        v-model="filter"
        size="sm"
        :icon="Search"
        :placeholder="t('groups.memory.filterPlaceholder')"
        :aria-label="t('groups.memory.filterPlaceholder')"
        clearable
      />
      <p v-if="!can('browse')" class="text-sm text-muted">{{ t('groups.memory.noBrowse') }}</p>
      <Skeleton v-else-if="listing.isPending.value" :lines="5" />
      <ErrorNote
        v-else-if="listing.isError.value"
        :title="t('groups.memory.readFailed')"
        :error="listing.error.value"
        :retry="listing.refetch"
      />
      <EmptyState
        v-else-if="!nodes.length && !detail"
        :icon="FolderOpen"
        :title="directory ? t('groups.memory.emptyDirectory') : t('groups.memory.empty')"
      >
        <Button v-if="writable" variant="primary" :icon="Plus" @click="create">
          {{ t('groups.memory.create') }}
        </Button>
      </EmptyState>
      <p v-else-if="nodes.length && !filteredNodes.length" class="px-2 py-2 text-xs text-muted">
        {{ t('common.noResults') }}
      </p>
      <ul v-else-if="filteredNodes.length" class="-mx-1 flex list-none flex-col gap-0.5 px-1">
        <li v-for="node in filteredNodes" :key="node.path">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors duration-150 focus-visible:focus-ring"
            :class="node.path === file ? 'bg-selected font-semibold text-ink' : 'text-ink hover:bg-hover'"
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
            <span
              v-if="isReadOnly(node)"
              class="inline-flex shrink-0 text-subtle"
              :title="t('groups.memory.readOnly')"
            >
              <Lock :size="13" aria-hidden="true" />
              <span class="sr-only">{{ t('groups.memory.readOnly') }}</span>
            </span>
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

    <section v-if="detail || split" class="flex min-w-0 flex-col gap-3">
      <Button
        v-if="!split && detail"
        size="sm"
        variant="ghost"
        :icon="ArrowLeft"
        class="self-start"
        @click="close"
      >
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
      <DirectorySummary
        v-else-if="nodes.length"
        :key="`${scope}:${directory}`"
        :scene="scene"
        :scope="scope"
        :path="directory"
        :time-zone="timeZone"
      />
    </section>
  </div>
</template>
