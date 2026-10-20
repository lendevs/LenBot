<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { ChevronRight, File, Folder, MoreHorizontal, RefreshCw, Upload } from '@lucide/vue'
import { keys } from '../../../api/query'
import { resourcesApi, type ResourceEntry, type ResourceRef, type ResourceScope } from '../../../api/resources'
import { formatBytes, formatDateTime } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import FileCopyDialog from './FileCopyDialog.vue'
import FilePreview from './FilePreview.vue'
import FileUploadDialog from './FileUploadDialog.vue'
import { uploadTone } from './labels'

/** Files of one task (`taskId`) or of the group's shared materials (`taskId` null). */
const props = withDefaults(
  defineProps<{
    scene: string
    taskId: number | null
    timeZone: string
    initialPath?: string
    /** Offers "use for a new task" on files. */
    pickable?: boolean
  }>(),
  { initialPath: '', pickable: false },
)
const emit = defineEmits<{ pick: [entry: ResourceEntry]; changed: [] }>()

const { t, te } = useI18n()
const client = useQueryClient()
const scope = ref<ResourceScope>(props.taskId === null ? 'shared' : 'workspace')
const path = ref(props.initialPath)
const scopes = computed(() =>
  (['workspace', 'inputs', 'deliveries', 'runtime'] as const).map((value) => ({
    value,
    label: t(`groups.tasks.space.scopes.${value}`),
  })),
)
watch(scope, () => (path.value = ''))
const location = computed<ResourceRef>(() => ({ scope: scope.value, task_id: props.taskId, path: path.value }))
const listing = useInfiniteQuery({
  queryKey: computed(() => keys.tasks.files(props.scene, location.value)),
  queryFn: ({ pageParam, signal }) => resourcesApi.list(props.scene, location.value, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page) => page.next_offset ?? undefined,
})
const first = computed(() => listing.data.value?.pages[0])
const rows = computed(() => listing.data.value?.pages.flatMap((page) => page.entries) ?? [])
const crumbs = computed(() => {
  const parts = path.value ? path.value.split('/') : []
  return parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join('/') }))
})

function refresh() {
  void client.invalidateQueries({ queryKey: keys.tasks.space() })
  emit('changed')
}

const at = (seconds: number) => formatDateTime(seconds, { timeZone: props.timeZone })
function where(reference: Partial<ResourceRef>): string {
  const scopeName = reference.scope ? t(`groups.tasks.space.scopes.${reference.scope}`) : ''
  const file = reference.scope === 'deliveries' ? `#${reference.file_id}` : (reference.path ?? '')
  return [reference.task_id ? `#${reference.task_id}` : '', scopeName, file].filter(Boolean).join(' · ')
}
function source(entry: ResourceEntry): string | null {
  const value = entry.source
  if (!value) return null
  if (entry.purpose === 'inputs') return value.reference ? where(value.reference) : (value.source_path ?? null)
  return where(value)
}
function details(entry: ResourceEntry): string {
  return [
    te(`groups.tasks.space.purposes.${entry.purpose}`) ? t(`groups.tasks.space.purposes.${entry.purpose}`) : entry.purpose,
    entry.size === null ? null : formatBytes(entry.size),
    at(entry.modified),
    entry.kind === 'symlink' ? t('groups.tasks.space.symlink') : null,
    !entry.exists && !entry.deletion ? t('groups.tasks.space.missing') : null,
  ]
    .filter(Boolean)
    .join(' · ')
}
const openable = (entry: ResourceEntry) =>
  entry.kind === 'directory' || (entry.kind === 'file' && entry.exists && entry.preview !== 'download')

const previewing = ref<ResourceEntry | null>(null)
function open(entry: ResourceEntry, asText = false) {
  if (entry.kind === 'directory') path.value = entry.reference.path
  else previewing.value = asText ? { ...entry, preview: 'text' } : entry
}
function download(entry: ResourceEntry) {
  const link = document.createElement('a')
  link.href = resourcesApi.downloadUrl(props.scene, entry.reference)
  link.download = entry.name
  document.body.appendChild(link)
  link.click()
  link.remove()
}

const copying = ref<{ entry: ResourceEntry; mode: 'register' | 'adopt' } | null>(null)
const uploading = ref(false)
const removal = useMutation({
  mutationFn: (entry: ResourceEntry) => resourcesApi.remove(props.scene, entry.reference),
  onSuccess: (value) => {
    toast.success(t('groups.tasks.space.removed', { name: value.name }))
    refresh()
  },
  onError: (error) =>
    toast.error(t('groups.tasks.space.removeFailed'), { detail: describeError(error, t('ui.error.network')).message }),
})
async function remove(entry: ResourceEntry) {
  const sure = await confirm({
    title: t('groups.tasks.space.removeTitle', { name: entry.name }),
    message: t(scope.value === 'deliveries' ? 'groups.tasks.space.removeDelivery' : 'groups.tasks.space.removeFile'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) removal.mutate(entry)
}
function actions(entry: ResourceEntry): MenuEntry[] {
  const items: MenuEntry[] = [{ label: t('groups.tasks.space.download'), select: () => download(entry) }]
  if (entry.preview === 'download') items.push({ label: t('groups.tasks.space.asText'), select: () => open(entry, true) })
  if (props.pickable && scope.value !== 'runtime')
    items.push({ label: t('groups.tasks.space.pick'), select: () => emit('pick', entry) })
  if (scope.value === 'workspace')
    items.push({ label: t('groups.tasks.space.register'), select: () => (copying.value = { entry, mode: 'register' }) })
  if (['workspace', 'inputs', 'deliveries'].includes(scope.value))
    items.push({ label: t('groups.tasks.space.adopt'), select: () => (copying.value = { entry, mode: 'adopt' }) })
  if (entry.deletable)
    items.push(
      { type: 'separator' },
      { label: t('common.delete'), danger: true, disabled: removal.isPending.value, select: () => void remove(entry) },
    )
  return items
}
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl
        v-if="taskId !== null"
        v-model="scope"
        :options="scopes"
        size="sm"
        :label="t('groups.tasks.space.scope')"
      />
      <div class="ml-auto flex items-center gap-1">
        <Button v-if="scope === 'shared'" size="sm" variant="ghost" :icon="Upload" @click="uploading = true">
          {{ t('groups.tasks.space.upload') }}
        </Button>
        <IconButton
          :icon="RefreshCw"
          :label="t('common.reload')"
          variant="ghost"
          size="sm"
          :loading="listing.isRefetching.value"
          @click="refresh"
        />
      </div>
    </div>
    <nav :aria-label="t('groups.tasks.space.path')" class="flex min-w-0 flex-wrap items-center gap-0.5 font-mono text-xs">
      <button type="button" class="rounded px-1 py-0.5 text-muted hover:bg-hover hover:text-ink" @click="path = ''">
        /
      </button>
      <template v-for="crumb in crumbs" :key="crumb.path">
        <ChevronRight :size="12" class="text-subtle" aria-hidden="true" />
        <button
          type="button"
          class="rounded px-1 py-0.5 break-all hover:bg-hover"
          :class="crumb.path === path ? 'text-ink' : 'text-muted hover:text-ink'"
          :aria-current="crumb.path === path ? 'location' : undefined"
          @click="path = crumb.path"
        >
          {{ crumb.name }}
        </button>
      </template>
    </nav>

    <Skeleton v-if="listing.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="listing.isError.value"
      :title="t('groups.tasks.space.readFailed')"
      :error="listing.error.value"
      :retry="listing.refetch"
    />
    <EmptyState
      v-else-if="!rows.length"
      :icon="Folder"
      :title="t(first?.exists === false ? 'groups.tasks.space.noDirectory' : 'groups.tasks.space.emptyDirectory')"
      compact
    />
    <ul v-else class="flex list-none flex-col divide-y divide-line rounded-lg border border-line">
      <li
        v-for="entry in rows"
        :key="entry.reference.file_id ?? entry.reference.path"
        class="flex items-start gap-2.5 px-3 py-2"
      >
        <component
          :is="entry.kind === 'directory' ? Folder : File"
          :size="16"
          class="mt-0.5 shrink-0 text-subtle"
          aria-hidden="true"
        />
        <div class="min-w-0 flex-1">
          <button
            v-if="openable(entry)"
            type="button"
            class="max-w-full cursor-pointer truncate text-left text-sm text-ink hover:text-primary hover:underline"
            @click="open(entry)"
          >
            {{ entry.name }}
          </button>
          <p v-else class="truncate text-sm text-ink-2">{{ entry.name }}</p>
          <p class="text-xs text-muted">{{ details(entry) }}</p>
          <p v-if="source(entry)" class="text-xs break-all text-muted">
            {{ t('groups.tasks.space.source', { where: source(entry) }) }}
          </p>
          <p v-if="entry.browser_source" class="text-xs break-all text-muted">
            {{ t(`groups.tasks.space.browserKinds.${entry.browser_source.kind}`) }}
            <template v-if="entry.browser_source.page_title"> · {{ entry.browser_source.page_title }}</template>
            <template v-if="entry.browser_source.page_url"> · {{ entry.browser_source.page_url }}</template>
          </p>
          <p v-if="entry.registrations.length" class="text-xs text-muted">
            {{ t('groups.tasks.space.registered', { ids: entry.registrations.map((id) => `#${id}`).join(' ') }) }}
          </p>
          <p v-if="entry.deletion" class="text-xs text-muted">
            {{ t('groups.tasks.space.deleted', { time: at(entry.deletion.created), who: entry.deletion.requester }) }}
          </p>
          <p v-if="entry.note" class="mt-0.5 text-sm break-words text-ink-2">{{ entry.note }}</p>
        </div>
        <Badge v-if="entry.upload" :tone="uploadTone[entry.upload.status] ?? 'neutral'" size="sm" class="mt-0.5">
          {{ t(`groups.tasks.files.upload.${entry.upload.status}`) }}
        </Badge>
        <DropdownMenu v-if="entry.kind === 'file' && entry.exists" :items="actions(entry)">
          <IconButton :icon="MoreHorizontal" :label="t('common.more')" variant="ghost" size="sm" :tooltip="false" />
        </DropdownMenu>
      </li>
    </ul>
    <Button
      v-if="listing.hasNextPage.value"
      size="sm"
      variant="ghost"
      class="self-start"
      :loading="listing.isFetchingNextPage.value"
      @click="listing.fetchNextPage()"
    >
      {{ t('groups.tasks.more') }}
    </Button>

    <FilePreview v-if="previewing" :scene="scene" :entry="previewing" @close="previewing = null" />
    <FileCopyDialog
      v-if="copying"
      :scene="scene"
      :entry="copying.entry"
      :mode="copying.mode"
      @done="refresh"
      @close="copying = null"
    />
    <FileUploadDialog v-if="uploading" :scene="scene" @done="refresh" @close="uploading = false" />
  </section>
</template>
