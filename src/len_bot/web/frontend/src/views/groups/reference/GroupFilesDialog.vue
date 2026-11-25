<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { ChevronRight, FileText, Folder, FolderOpen, Search } from '@lucide/vue'
import { keys } from '../../../api/query'
import { referenceApi, type GroupFile, type GroupFolder, type ReferenceListing } from '../../../api/reference'
import { formatBytes, formatDateTime, formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'

/** With `pick`, any file can be chosen and is emitted as `picked` instead of being added to the reference. */
const props = defineProps<{
  scene: string
  existing: string[]
  pick?: boolean
  formats?: string[]
  maxBytes?: number
}>()
const emit = defineEmits<{ imported: [listing: ReferenceListing]; picked: [file: GroupFile] }>()
const open = defineModel<boolean>('open', { default: false })

const { t } = useI18n()
const trail = ref<GroupFolder[]>([])
const filter = ref('')
const folder = computed(() => trail.value.at(-1)?.folder_id ?? null)
watch(open, (shown) => {
  if (shown) {
    trail.value = []
    filter.value = ''
  }
})
watch(folder, () => {
  filter.value = ''
})

const listing = useQuery({
  queryKey: computed(() => keys.reference.groupFiles(props.scene, folder.value)),
  queryFn: ({ signal }) => referenceApi.groupFiles(props.scene, folder.value, signal),
  enabled: open,
})
const empty = computed(() => !listing.data.value?.files.length && !listing.data.value?.folders.length)
const filteredFolders = computed(() => {
  const keyword = filter.value.trim().toLowerCase()
  const list = listing.data.value?.folders ?? []
  if (!keyword) return list
  return list.filter((item) => item.name.toLowerCase().includes(keyword))
})
const filteredFiles = computed(() => {
  const keyword = filter.value.trim().toLowerCase()
  const list = listing.data.value?.files ?? []
  if (!keyword) return list
  return list.filter(
    (file) =>
      file.name.toLowerCase().includes(keyword) || (file.uploader?.toLowerCase().includes(keyword) ?? false),
  )
})
const noFilteredMatch = computed(
  () => !empty.value && filteredFolders.value.length === 0 && filteredFiles.value.length === 0,
)

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot >= 0 ? filename.slice(dot).toLowerCase() : ''
}
function isTooLarge(file: GroupFile): boolean {
  if (props.pick || file.supported) return false
  return props.maxBytes !== undefined && file.size > props.maxBytes
}
function isUnsupportedFormat(file: GroupFile): boolean {
  if (props.pick || file.supported) return false
  if (props.formats?.length) return !props.formats.includes(extensionOf(file.name))
  return !isTooLarge(file)
}

const pending = ref<string | null>(null)
const importing = useMutation({
  mutationFn: (file: GroupFile) => {
    pending.value = file.file_id
    return referenceApi.importGroupFile(props.scene, file)
  },
  onSuccess: (result, file) => {
    emit('imported', result)
    toast.success(t('groups.reference.groupFiles.imported', { name: file.name }))
  },
  onError: (error) =>
    toast.error(t('groups.reference.groupFiles.importFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => {
    pending.value = null
  },
})

function details(file: GroupFile) {
  return [formatBytes(file.size), file.uploader, formatDateTime(file.uploaded)].filter(Boolean).join(' · ')
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.reference.groupFiles.title')" size="lg">
    <nav class="mb-3 flex min-w-0 flex-wrap items-center gap-0.5 text-sm">
      <button
        type="button"
        class="cursor-pointer rounded-sm px-1 py-0.5 transition-colors hover:bg-hover focus-visible:focus-ring"
        :class="!trail.length ? 'font-medium text-ink' : 'text-muted hover:text-ink'"
        @click="trail = []"
      >
        {{ t('groups.reference.groupFiles.root') }}
      </button>
      <template v-for="(item, position) in trail" :key="item.folder_id">
        <ChevronRight :size="13" class="shrink-0 text-subtle" aria-hidden="true" />
        <button
          type="button"
          class="max-w-48 cursor-pointer truncate rounded-sm px-1 py-0.5 transition-colors hover:bg-hover focus-visible:focus-ring"
          :class="position === trail.length - 1 ? 'font-medium text-ink' : 'text-muted hover:text-ink'"
          @click="trail = trail.slice(0, position + 1)"
        >
          {{ item.name }}
        </button>
      </template>
    </nav>
    <Input
      v-if="!listing.isPending.value && !listing.isError.value && !empty"
      v-model="filter"
      size="sm"
      :icon="Search"
      :placeholder="t('groups.reference.groupFiles.searchPlaceholder')"
      :aria-label="t('groups.reference.groupFiles.searchPlaceholder')"
      clearable
      class="mb-3"
    />
    <Skeleton v-if="listing.isPending.value" :lines="5" />
    <ErrorNote
      v-else-if="listing.isError.value"
      :title="t('groups.reference.groupFiles.readFailed')"
      :error="listing.error.value"
      :retry="listing.refetch"
    />
    <EmptyState
      v-else-if="empty"
      :icon="FolderOpen"
      :title="t('groups.reference.groupFiles.empty')"
      compact
    />
    <EmptyState v-else-if="noFilteredMatch" :title="t('common.noResults')" compact />
    <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
      <li v-for="item in filteredFolders" :key="item.folder_id">
        <button
          type="button"
          class="flex w-full min-w-0 cursor-pointer items-center gap-3 px-2 py-2.5 text-left transition-colors duration-150 hover:bg-hover focus-visible:focus-ring"
          @click="trail = [...trail, item]"
        >
          <Folder :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-sm font-medium text-ink">{{ item.name }}</span>
          <span class="shrink-0 text-xs text-muted tabular">
            {{ t('groups.reference.groupFiles.count', { n: formatNumber(item.files) }) }}
          </span>
          <ChevronRight :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
        </button>
      </li>
      <li
        v-for="file in filteredFiles"
        :key="file.file_id"
        class="flex min-w-0 items-center gap-3 px-2 py-2.5"
        :class="{ 'opacity-60': !pick && !file.supported }"
      >
        <FileText :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
        <div class="min-w-0 flex-1">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <span class="truncate text-sm font-medium text-ink">{{ file.name }}</span>
            <Badge v-if="existing.includes(file.name)" tone="success">
              {{ t(pick ? 'groups.reference.groupFiles.picked' : 'groups.reference.groupFiles.added') }}
            </Badge>
            <Badge v-if="isTooLarge(file)" tone="warning">
              {{ t('groups.reference.groupFiles.tooLarge') }}
            </Badge>
            <Badge v-if="isUnsupportedFormat(file)" tone="neutral">
              {{ t('groups.reference.groupFiles.unsupportedFormat') }}
            </Badge>
          </div>
          <p class="mt-0.5 truncate text-xs text-muted tabular">{{ details(file) }}</p>
        </div>
        <Button v-if="pick" size="sm" :disabled="existing.includes(file.name)" @click="emit('picked', file)">
          {{ t('groups.reference.groupFiles.pick') }}
        </Button>
        <Button
          v-else-if="file.supported"
          size="sm"
          :loading="pending === file.file_id"
          :disabled="importing.isPending.value && pending !== file.file_id"
          @click="importing.mutate(file)"
        >
          {{
            t(
              existing.includes(file.name)
                ? 'groups.reference.groupFiles.update'
                : 'groups.reference.groupFiles.add',
            )
          }}
        </Button>
      </li>
    </ul>
  </Dialog>
</template>
