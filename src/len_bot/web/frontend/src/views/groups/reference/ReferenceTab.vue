<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { FileText, FolderOpen, RotateCw, Search, Trash2, Upload, Users } from '@lucide/vue'
import { keys } from '../../../api/query'
import {
  referenceApi,
  type ReferenceFile,
  type ReferenceListing,
  type ReferenceScope,
} from '../../../api/reference'
import { formatBytes, formatDateTime, formatNumber, formatRelative } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import GroupFilesDialog from './GroupFilesDialog.vue'

const props = defineProps<{ scene: string }>()

const { t } = useI18n()
const client = useQueryClient()
const key = computed(() => keys.reference.scene(props.scene))
const listing = useQuery({
  queryKey: key,
  queryFn: ({ signal }) => referenceApi.listing(props.scene, signal),
  // Host events refresh it when processing ends; this covers a file that takes a while.
  refetchInterval: (query) =>
    query.state.data?.processing || query.state.data?.files.some((file) => file.status === 'processing')
      ? 3000
      : false,
})
const files = computed(() => listing.data.value?.files ?? [])
const formats = computed(() => (listing.data.value?.formats ?? []).map((ext) => ext.toLowerCase()))
const accept = computed(() => formats.value.join(','))
const input = ref<HTMLInputElement | null>(null)
const picking = ref(false)

function adopt(result: ReferenceListing) {
  client.setQueryData(key.value, result)
}
const failed = (title: string) => (error: unknown) =>
  toast.error(title, { detail: describeError(error, t('ui.error.network')).message })

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot >= 0 ? filename.slice(dot).toLowerCase() : ''
}

const uploadProgress = ref<{ current: number; total: number } | null>(null)
const uploading = computed(() => uploadProgress.value !== null)
const uploadLabel = computed(() =>
  uploadProgress.value && uploadProgress.value.total > 1
    ? t('groups.reference.uploadingProgress', uploadProgress.value)
    : t('groups.reference.upload'),
)

async function handleFiles(chosen: File[]) {
  if (!chosen.length || uploading.value) return
  const allowed = formats.value
  const maxBytes = listing.data.value?.max_bytes ?? 0
  const valid: File[] = []
  const badFormat: string[] = []
  const tooLarge: string[] = []

  for (const file of chosen) {
    if (allowed.length && !allowed.includes(extensionOf(file.name))) {
      badFormat.push(file.name)
    } else if (maxBytes > 0 && file.size > maxBytes) {
      tooLarge.push(file.name)
    } else {
      valid.push(file)
    }
  }

  if (badFormat.length) {
    toast.error(t('groups.reference.unsupportedFormat', { formats: allowed.join(' / ') }), {
      detail: badFormat.join(', '),
    })
  }
  if (tooLarge.length) {
    toast.error(t('groups.reference.fileTooLarge', { max: formatBytes(maxBytes) }), {
      detail: tooLarge.join(', '),
    })
  }
  if (!valid.length) return

  const existingNames = new Set(files.value.map((item) => item.filename))
  const duplicates = valid.filter((file) => existingNames.has(file.name))
  if (duplicates.length) {
    const ok = await confirm({
      title:
        duplicates.length === 1
          ? t('groups.reference.overwriteTitle', { name: duplicates[0]!.name })
          : t('groups.reference.overwriteMultiTitle', { n: duplicates.length }),
      message: duplicates.length > 1 ? duplicates.map((file) => file.name).join(', ') : undefined,
      confirmLabel: t('groups.reference.overwriteConfirm'),
    })
    if (!ok) return
  }

  const total = valid.length
  let succeeded = 0
  const failedItems: { name: string; reason: string }[] = []

  for (let i = 0; i < total; i++) {
    const file = valid[i]!
    uploadProgress.value = { current: i + 1, total }
    try {
      const latest = await referenceApi.upload(props.scene, file)
      adopt(latest)
      succeeded += 1
    } catch (error) {
      failedItems.push({
        name: file.name,
        reason: describeError(error, t('ui.error.network')).message,
      })
    }
  }

  uploadProgress.value = null

  if (failedItems.length) {
    toast.error(
      succeeded > 0
        ? t('groups.reference.uploadPartial', { done: succeeded, failed: failedItems.length })
        : t('groups.reference.uploadFailed'),
      {
        detail: failedItems.map((item) => `${item.name}: ${item.reason}`).join('\n'),
      },
    )
  } else if (succeeded > 0) {
    toast.success(t('groups.reference.uploaded', { n: succeeded }, succeeded))
  }
}

const dragDepth = ref(0)
const dragging = computed(() => dragDepth.value > 0)
const hasDraggedFiles = (event: DragEvent) => Boolean(event.dataTransfer?.types.includes('Files'))
function onDragEnter(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  dragDepth.value += 1
}
function onDragOver(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}
function onDragLeave(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}
function onDrop(event: DragEvent) {
  dragDepth.value = 0
  if (!hasDraggedFiles(event)) return
  const dropped = Array.from(event.dataTransfer?.files ?? [])
  if (dropped.length) void handleFiles(dropped)
}

function picked(event: Event) {
  const target = event.target as HTMLInputElement
  const chosen = Array.from(target.files ?? [])
  target.value = ''
  if (chosen.length) void handleFiles(chosen)
}

const reprocessing = ref<Record<string, boolean>>({})
const removing = ref<Record<string, boolean>>({})

async function runReprocess(filename: string) {
  if (reprocessing.value[filename] || removing.value[filename]) return
  reprocessing.value = { ...reprocessing.value, [filename]: true }
  try {
    adopt(await referenceApi.reprocess(props.scene, filename))
  } catch (error) {
    failed(t('groups.reference.reprocessFailed'))(error)
  } finally {
    const next = { ...reprocessing.value }
    delete next[filename]
    reprocessing.value = next
  }
}

async function remove(file: ReferenceFile) {
  if (removing.value[file.filename]) return
  const sure = await confirm({
    title: t('groups.reference.removeTitle', { name: file.filename }),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (!sure) return
  removing.value = { ...removing.value, [file.filename]: true }
  try {
    adopt(await referenceApi.remove(props.scene, file.filename))
    toast.success(t('groups.reference.removed'))
  } catch (error) {
    failed(t('groups.reference.removeFailed'))(error)
  } finally {
    const next = { ...removing.value }
    delete next[file.filename]
    removing.value = next
  }
}

const tones = { processing: 'info', indexed: 'success', failed: 'error' } as const
const hasVectorGap = (file: ReferenceFile) =>
  Boolean(listing.data.value?.vectors) && file.status === 'indexed' && file.vectors < file.chunks

function details(file: ReferenceFile) {
  const parts = [formatBytes(file.size)]
  if (file.pages !== null) parts.push(t('groups.reference.pages', { n: formatNumber(file.pages) }))
  if (file.chars !== null) parts.push(t('groups.reference.chars', { n: formatNumber(file.chars) }))
  if (file.status === 'indexed') {
    parts.push(t('groups.reference.chunks', { n: formatNumber(file.chunks) }))
    if (listing.data.value?.vectors)
      parts.push(
        t('groups.reference.vectors', {
          n: formatNumber(file.vectors),
          total: formatNumber(file.chunks),
        }),
      )
  }
  if (file.modified) parts.push(formatRelative(file.modified))
  return parts.join(' · ')
}

const searchQuery = ref('')
const searchScope = ref<ReferenceScope>('all')
const searchScopes = computed(() =>
  (['all', 'scene', 'persona'] as const).map((value) => ({
    value,
    label: t(`groups.reference.search.scopes.${value}`),
  })),
)
const search = useMutation({
  mutationFn: ({ query, scope }: { query: string; scope: ReferenceScope }) =>
    referenceApi.search(props.scene, query, scope),
})
function runSearch() {
  const query = searchQuery.value.trim()
  if (!query) return
  search.mutate({ query, scope: searchScope.value })
}
watch(searchScope, (nextScope) => {
  const query = search.variables.value?.query ?? searchQuery.value.trim()
  if (search.data.value && query) search.mutate({ query, scope: nextScope })
})
watch(
  () => props.scene,
  () => {
    dragDepth.value = 0
    searchQuery.value = ''
    searchScope.value = 'all'
    search.reset()
  },
)

function highlightParts(preview: string, query: string): { text: string; match: boolean }[] {
  const terms = [...new Set(query.trim().split(/\s+/).filter(Boolean))].sort((a, b) => b.length - a.length)
  if (!terms.length || !preview) return [{ text: preview, match: false }]
  const pattern = new RegExp(
    `(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'gi',
  )
  const parts: { text: string; match: boolean }[] = []
  let last = 0
  for (const found of preview.matchAll(pattern)) {
    const start = found.index ?? 0
    if (start > last) parts.push({ text: preview.slice(last, start), match: false })
    parts.push({ text: found[0], match: true })
    last = start + found[0].length
  }
  if (last < preview.length) parts.push({ text: preview.slice(last), match: false })
  return parts.length ? parts : [{ text: preview, match: false }]
}
</script>

<template>
  <Skeleton v-if="listing.isPending.value" :lines="5" />
  <ErrorNote
    v-else-if="listing.isError.value"
    :title="t('groups.reference.readFailed')"
    :error="listing.error.value"
    :retry="listing.refetch"
  />
  <section
    v-else
    class="-m-2 grid min-w-0 gap-5 rounded-lg border p-2 transition-colors"
    :class="dragging ? 'border-dashed border-primary bg-selected/40' : 'border-transparent'"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <div class="grid min-w-0 gap-3">
      <input ref="input" type="file" class="hidden" multiple :accept="accept" @change="picked" />
      <div v-if="files.length" class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-base font-semibold text-ink">{{ t('groups.reference.title') }}</h3>
        <div class="flex flex-wrap items-center gap-2">
          <Button v-if="listing.data.value?.group_files" size="sm" :icon="Users" @click="picking = true">
            {{ t('groups.reference.groupFiles.open') }}
          </Button>
          <Button size="sm" :icon="Upload" :loading="uploading" @click="input?.click()">
            {{ uploadLabel }}
          </Button>
        </div>
      </div>
      <GroupFilesDialog
        v-model:open="picking"
        :scene="scene"
        :existing="files.map((file) => file.filename)"
        :formats="formats"
        :max-bytes="listing.data.value?.max_bytes"
        @imported="adopt"
      />
      <EmptyState v-if="!files.length" :icon="FolderOpen" :title="t('groups.reference.empty')">
        <Button
          v-if="listing.data.value?.group_files"
          variant="primary"
          :icon="Users"
          @click="picking = true"
        >
          {{ t('groups.reference.groupFiles.open') }}
        </Button>
        <Button
          :variant="listing.data.value?.group_files ? 'secondary' : 'primary'"
          :icon="Upload"
          :loading="uploading"
          @click="input?.click()"
        >
          {{ uploadLabel }}
        </Button>
      </EmptyState>
      <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li v-for="file in files" :key="file.filename" class="flex min-w-0 items-center gap-3 px-2 py-3">
          <FileText :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <span class="truncate text-sm font-medium text-ink">{{ file.filename }}</span>
              <Badge :tone="tones[file.status]" dot :pulse="file.status === 'processing'">
                {{ t(`groups.reference.status.${file.status}`) }}
              </Badge>
              <Badge v-if="hasVectorGap(file)" tone="warning">
                {{
                  t('groups.reference.vectorGap', {
                    n: formatNumber(file.vectors),
                    total: formatNumber(file.chunks),
                  })
                }}
              </Badge>
            </div>
            <p
              class="mt-0.5 truncate text-xs text-muted tabular"
              :title="file.modified ? formatDateTime(file.modified) : undefined"
            >
              {{ details(file) }}
            </p>
            <p v-if="file.error" class="mt-0.5 text-xs break-words text-error">{{ file.error }}</p>
          </div>
          <div class="flex shrink-0 items-center gap-1">
            <IconButton
              :icon="RotateCw"
              :label="t('groups.reference.reprocess')"
              size="sm"
              :loading="Boolean(reprocessing[file.filename])"
              :disabled="file.status === 'processing' || Boolean(removing[file.filename])"
              @click="runReprocess(file.filename)"
            />
            <IconButton
              :icon="Trash2"
              :label="t('common.delete')"
              variant="danger-ghost"
              size="sm"
              :loading="Boolean(removing[file.filename])"
              :disabled="Boolean(reprocessing[file.filename])"
              @click="remove(file)"
            />
          </div>
        </li>
      </ul>
    </div>

    <div class="flex max-w-3xl min-w-0 flex-col gap-3 border-t border-line pt-5">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-base font-semibold text-ink">{{ t('groups.reference.search.title') }}</h3>
        <SegmentedControl
          v-model="searchScope"
          :options="searchScopes"
          size="sm"
          :label="t('groups.reference.search.title')"
        />
      </div>
      <form class="flex gap-2" @submit.prevent="runSearch">
        <div class="min-w-0 flex-1">
          <Input
            v-model="searchQuery"
            :icon="Search"
            :placeholder="t('groups.reference.search.placeholder')"
            :aria-label="t('groups.reference.search.placeholder')"
            clearable
          />
        </div>
        <Button
          type="submit"
          variant="primary"
          :loading="search.isPending.value"
          :disabled="!searchQuery.trim()"
        >
          {{ t('groups.reference.search.action') }}
        </Button>
      </form>
      <ErrorNote
        v-if="search.isError.value"
        :title="t('groups.reference.search.failed')"
        :error="search.error.value"
      />
      <EmptyState
        v-else-if="search.data.value && !search.data.value.hits.length"
        :title="t('groups.reference.search.empty')"
        compact
      />
      <ul
        v-else-if="search.data.value"
        class="flex list-none flex-col divide-y divide-line border-y border-line"
      >
        <li
          v-for="(hit, idx) in search.data.value.hits"
          :key="`${hit.scope}:${hit.path}:${hit.section ?? ''}:${idx}`"
          class="flex flex-col gap-1.5 px-2 py-3"
        >
          <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <Badge :tone="hit.scope === 'persona' ? 'info' : 'neutral'">
              {{
                t(
                  hit.scope === 'persona'
                    ? 'groups.reference.search.scopes.persona'
                    : 'groups.reference.search.scopes.scene',
                )
              }}
            </Badge>
            <span class="min-w-0 truncate font-mono text-sm font-medium text-ink">{{ hit.path }}</span>
            <span v-if="hit.section" class="min-w-0 truncate text-xs text-muted">· {{ hit.section }}</span>
          </div>
          <p class="line-clamp-4 text-sm leading-6 break-words whitespace-pre-wrap text-ink-2">
            <template
              v-for="(part, at) in highlightParts(hit.preview, search.variables.value?.query ?? '')"
              :key="at"
            >
              <mark v-if="part.match" class="rounded-xs bg-selected px-0.5 text-ink">{{ part.text }}</mark>
              <template v-else>{{ part.text }}</template>
            </template>
          </p>
        </li>
      </ul>
    </div>
  </section>
</template>
