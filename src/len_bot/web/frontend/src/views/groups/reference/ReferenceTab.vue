<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { FileText, FolderOpen, RotateCw, Trash2, Upload, Users } from '@lucide/vue'
import { keys } from '../../../api/query'
import { referenceApi, type ReferenceFile, type ReferenceListing } from '../../../api/reference'
import { formatBytes } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
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
const accept = computed(() => (listing.data.value?.formats ?? []).join(','))
const input = ref<HTMLInputElement | null>(null)
const picking = ref(false)

function adopt(result: ReferenceListing) {
  client.setQueryData(key.value, result)
}
const failed = (title: string) => (error: unknown) =>
  toast.error(title, { detail: describeError(error, t('ui.error.network')).message })

const upload = useMutation({
  mutationFn: async (picked: File[]) => {
    let result: ReferenceListing | null = null
    for (const file of picked) result = await referenceApi.upload(props.scene, file)
    return result
  },
  onSuccess: (result) => result && adopt(result),
  onError: failed(t('groups.reference.uploadFailed')),
})
const removal = useMutation({
  mutationFn: (filename: string) => referenceApi.remove(props.scene, filename),
  onSuccess: (result) => {
    adopt(result)
    toast.success(t('groups.reference.removed'))
  },
  onError: failed(t('groups.reference.removeFailed')),
})
const reprocess = useMutation({
  mutationFn: (filename: string) => referenceApi.reprocess(props.scene, filename),
  onSuccess: adopt,
  onError: failed(t('groups.reference.reprocessFailed')),
})

function picked(event: Event) {
  const target = event.target as HTMLInputElement
  const chosen = Array.from(target.files ?? [])
  target.value = ''
  if (chosen.length) upload.mutate(chosen)
}
async function remove(file: ReferenceFile) {
  const sure = await confirm({
    title: t('groups.reference.removeTitle', { name: file.filename }),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) removal.mutate(file.filename)
}

const tones = { processing: 'info', indexed: 'success', failed: 'error' } as const
function details(file: ReferenceFile) {
  const parts = [formatBytes(file.size)]
  if (file.pages !== null) parts.push(t('groups.reference.pages', { n: file.pages }))
  if (file.chars !== null) parts.push(t('groups.reference.chars', { n: file.chars }))
  if (file.status === 'indexed') {
    parts.push(t('groups.reference.chunks', { n: file.chunks }))
    if (listing.data.value?.vectors)
      parts.push(t('groups.reference.vectors', { n: file.vectors, total: file.chunks }))
  }
  return parts.join(' · ')
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
  <section v-else class="grid min-w-0 gap-3">
    <div class="flex items-center justify-between gap-2">
      <h3 class="text-base font-semibold">{{ t('groups.reference.title') }}</h3>
      <div class="flex items-center gap-2">
        <Button v-if="listing.data.value?.group_files" size="sm" :icon="Users" @click="picking = true">
          {{ t('groups.reference.groupFiles.open') }}
        </Button>
        <Button size="sm" :icon="Upload" :loading="upload.isPending.value" @click="input?.click()">
          {{ t('groups.reference.upload') }}
        </Button>
      </div>
      <input ref="input" type="file" class="hidden" multiple :accept="accept" @change="picked" />
    </div>
    <GroupFilesDialog
      v-model:open="picking"
      :scene="scene"
      :existing="files.map((file) => file.filename)"
      @imported="adopt"
    />
    <EmptyState v-if="!files.length" :icon="FolderOpen" :title="t('groups.reference.empty')" compact />
    <ul v-else class="flex list-none flex-col divide-y divide-line rounded-lg border border-line">
      <li v-for="file in files" :key="file.filename" class="flex min-w-0 items-center gap-3 px-3 py-2.5">
        <FileText :size="16" class="shrink-0 text-muted" aria-hidden="true" />
        <div class="min-w-0 flex-1">
          <div class="flex min-w-0 items-center gap-2">
            <span class="truncate text-sm font-medium text-ink">{{ file.filename }}</span>
            <Badge :tone="tones[file.status]">{{ t(`groups.reference.status.${file.status}`) }}</Badge>
          </div>
          <p class="truncate text-xs text-muted">{{ details(file) }}</p>
          <p v-if="file.error" class="text-xs break-words text-error">{{ file.error }}</p>
        </div>
        <IconButton
          :icon="RotateCw"
          :label="t('groups.reference.reprocess')"
          :disabled="file.status === 'processing' || reprocess.isPending.value"
          @click="reprocess.mutate(file.filename)"
        />
        <IconButton
          :icon="Trash2"
          :label="t('common.delete')"
          :disabled="removal.isPending.value"
          @click="remove(file)"
        />
      </li>
    </ul>
  </section>
</template>
