<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ImageOff, MoreHorizontal, Pencil, Plus, Search, Smile, Trash2, Upload } from '@lucide/vue'
import { keys } from '../../../api/query'
import { personasApi, type StickerEntry, type StickerListing } from '../../../api/personas'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import FormSection from '../../../ui/FormSection.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import StickerDialog from './StickerDialog.vue'
import { useRoleWrites } from './writes'

const ALLOWED_IMAGE_EXT = /\.(?:png|jpe?g|gif|webp)$/i

const props = defineProps<{ persona: string }>()

const { t } = useI18n()
const client = useQueryClient()
const writes = useRoleWrites(computed(() => props.persona))
const listingKey = computed(() => keys.personas.part(props.persona, 'stickers'))
const listing = useQuery({
  queryKey: listingKey,
  queryFn: ({ signal }) => personasApi.stickers(props.persona, signal),
})
const entries = computed(() => listing.data.value?.entries ?? [])
const indexedFiles = computed(() => new Set(entries.value.map((entry) => entry.file)))
/** Images in the folder that the index does not list yet. */
const loose = computed(() =>
  (listing.data.value?.files ?? []).filter((file) => !indexedFiles.value.has(file.file)),
)

const search = ref('')
const selectedTag = ref<string | null>(null)
const allFilterTags = computed(() => {
  const counts = new Map<string, number>()
  for (const entry of entries.value) {
    for (const tag of new Set([...entry.emotions, ...entry.tags])) {
      const trimmed = tag.trim()
      if (trimmed) counts.set(trimmed, (counts.get(trimmed) ?? 0) + 1)
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name]) => name)
})
watch(allFilterTags, (list) => {
  if (selectedTag.value && !list.includes(selectedTag.value)) selectedTag.value = null
})

const keyword = computed(() => search.value.trim().toLowerCase())
const filteredEntries = computed(() => {
  const q = keyword.value
  const tag = selectedTag.value
  return entries.value.filter((entry) => {
    if (tag && !entry.emotions.includes(tag) && !entry.tags.includes(tag)) return false
    if (!q) return true
    return [entry.file, entry.description, ...entry.emotions, ...entry.tags].some((part) =>
      part.toLowerCase().includes(q),
    )
  })
})
const filteredLoose = computed(() => {
  const q = keyword.value
  if (!q) return loose.value
  return loose.value.filter((item) => item.file.toLowerCase().includes(q))
})
const extraTags = (entry: StickerEntry) => {
  const emotions = new Set(entry.emotions)
  return entry.tags.filter((tag) => !emotions.has(tag))
}
const image = (file: string) => personasApi.stickerImage(props.persona, listing.data.value!.saved_path, file)
const broken = ref(new Set<string>())

/** `undefined` closes the dialog; `null` adds a new image. */
const editing = ref<StickerEntry | null | undefined>(undefined)
const describingLoose = ref(false)
const nextLoose = computed(() => {
  if (!describingLoose.value || !editing.value) return null
  const list = loose.value.map((item) => item.file)
  const idx = list.indexOf(editing.value.file)
  if (idx === -1 || list.length <= 1) return null
  return list[(idx + 1) % list.length] ?? null
})

function openAdd() {
  describingLoose.value = false
  editing.value = null
}
function openEdit(entry: StickerEntry) {
  describingLoose.value = false
  editing.value = entry
}
function describe(file: string) {
  describingLoose.value = true
  editing.value = { file, description: '', emotions: [], tags: [] }
}
function closeDialog() {
  describingLoose.value = false
  editing.value = undefined
}
function saved(result: StickerListing, continueNext: boolean) {
  const preferredNext = nextLoose.value
  client.setQueryData(listingKey.value, result)
  writes.done(result)
  if (continueNext) {
    const indexed = new Set((result.entries ?? []).map((item) => item.file))
    const remaining = result.files.map((item) => item.file).filter((name) => !indexed.has(name))
    const next = preferredNext && remaining.includes(preferredNext) ? preferredNext : remaining[0]
    if (next) {
      describingLoose.value = true
      editing.value = { file: next, description: '', emotions: [], tags: [] }
      return
    }
  }
  closeDialog()
}
// A failed add may still have uploaded the image; read the folder again so it shows up.
const reread = () => void listing.refetch()

const batchPicker = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
let dragDepth = 0

const batchUpload = useMutation({
  mutationFn: async (files: File[]) => {
    const current = listing.data.value!
    const directory = current.saved_path
    if (current.entries === null) {
      await personasApi.saveStickers(props.persona, directory, [])
    }
    let uploaded = 0
    const failed: string[] = []
    for (const item of files) {
      try {
        await personasApi.uploadSticker(props.persona, directory, item)
        uploaded += 1
      } catch (error) {
        failed.push(`${item.name}: ${describeError(error, t('ui.error.network')).message}`)
      }
    }
    return { uploaded, failed }
  },
  onSuccess: ({ uploaded, failed }) => {
    void listing.refetch()
    if (uploaded && !failed.length) {
      toast.success(t('personas.detail.stickers.batchUploaded', { n: uploaded }, uploaded))
    } else if (uploaded && failed.length) {
      toast.error(t('personas.detail.stickers.batchPartial', { ok: uploaded, fail: failed.length }), {
        detail: failed.join('\n'),
      })
    } else if (failed.length) {
      toast.error(t('personas.detail.stickers.batchFailed'), { detail: failed.join('\n') })
    }
  },
  onError: (error) => {
    toast.error(t('personas.detail.stickers.batchFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
    reread()
  },
})

function startBatchUpload(picked: File[]) {
  if (!picked.length || batchUpload.isPending.value) return
  const images = picked.filter(
    (item) =>
      ['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(item.type) ||
      ALLOWED_IMAGE_EXT.test(item.name),
  )
  if (!images.length) {
    toast.error(t('personas.detail.stickers.imageOnly'))
    return
  }
  batchUpload.mutate(images)
}

function batchChosen(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = Array.from(input.files ?? [])
  input.value = ''
  if (picked.length) startBatchUpload(picked)
}

function onDragEnter(event: DragEvent) {
  if (batchUpload.isPending.value) return
  event.preventDefault()
  dragDepth += 1
  dragging.value = true
}
function onDragOver(event: DragEvent) {
  if (batchUpload.isPending.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  dragging.value = true
}
function onDragLeave(event: DragEvent) {
  if (batchUpload.isPending.value) return
  event.preventDefault()
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragging.value = false
  }
}
function onDrop(event: DragEvent) {
  if (batchUpload.isPending.value) return
  event.preventDefault()
  dragDepth = 0
  dragging.value = false
  const dropped = Array.from(event.dataTransfer?.files ?? [])
  if (dropped.length) startBatchUpload(dropped)
}

const removal = useMutation({
  mutationFn: async (file: string) => {
    const current = listing.data.value!
    if (current.entries?.some((item) => item.file === file)) {
      await personasApi.saveStickers(
        props.persona,
        current.saved_path,
        current.entries.filter((item) => item.file !== file),
      )
    }
    await personasApi.removeSticker(props.persona, current.saved_path, file)
    return personasApi.stickers(props.persona)
  },
  onSuccess: (result) => {
    client.setQueryData(listingKey.value, result)
    writes.done(result, [], t('personas.detail.stickers.removed'))
  },
  onError: (error) => {
    toast.error(t('personas.detail.stickers.removeFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
    reread()
  },
})
async function remove(file: string) {
  const sure = await confirm({
    title: t('personas.detail.stickers.removeTitle'),
    message: t('personas.detail.stickers.removeMessage'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) removal.mutate(file)
}
const menu = (entry: StickerEntry): MenuEntry[] => [
  { label: t('common.edit'), icon: Pencil, select: () => openEdit(entry) },
  { type: 'separator' },
  { label: t('common.delete'), icon: Trash2, danger: true, select: () => void remove(entry.file) },
]
</script>

<template>
  <Skeleton v-if="listing.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="listing.isError.value"
    :title="t('personas.detail.stickers.readFailed')"
    :error="listing.error.value"
    :retry="listing.refetch"
  />
  <div
    v-else
    class="flex flex-col gap-8"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="batchPicker"
      type="file"
      accept="image/png,image/jpeg,image/gif,image/webp"
      multiple
      class="sr-only"
      tabindex="-1"
      aria-hidden="true"
      @change="batchChosen"
    />

    <FormSection :title="t('personas.detail.stickers.title')" :columns="1">
      <template #actions>
        <div class="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            :icon="Upload"
            :loading="batchUpload.isPending.value"
            @click="batchPicker?.click()"
          >
            {{ t('personas.detail.stickers.batchUpload') }}
          </Button>
          <Button size="sm" :icon="Plus" @click="openAdd">
            {{ t('personas.detail.stickers.add') }}
          </Button>
        </div>
      </template>

      <button
        type="button"
        :disabled="batchUpload.isPending.value"
        class="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-3 text-sm transition-colors focus-visible:focus-ring disabled:pointer-events-none disabled:opacity-50"
        :class="
          dragging
            ? 'border-primary bg-selected/40 text-ink'
            : 'border-line-strong bg-fill/35 text-muted hover:border-subtle hover:bg-hover/50 hover:text-ink'
        "
        @click="batchPicker?.click()"
      >
        <Upload :size="15" class="shrink-0" aria-hidden="true" />
        <span>{{ t('personas.detail.stickers.dropImages') }}</span>
      </button>

      <EmptyState v-if="!entries.length" :icon="Smile" :title="t('personas.detail.stickers.empty')" compact />
      <template v-else>
        <div class="flex flex-col gap-2">
          <div class="max-w-xs">
            <Input
              v-model="search"
              type="search"
              size="sm"
              :icon="Search"
              clearable
              :placeholder="t('common.search')"
              :aria-label="t('common.search')"
            />
          </div>
          <div v-if="allFilterTags.length" class="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              class="cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus-visible:focus-ring"
              :class="
                selectedTag === null
                  ? 'border-primary bg-selected text-ink'
                  : 'border-line bg-fill text-muted hover:text-ink'
              "
              :aria-pressed="selectedTag === null"
              @click="selectedTag = null"
            >
              {{ t('personas.detail.stickers.allTags') }}
            </button>
            <button
              v-for="tag in allFilterTags"
              :key="tag"
              type="button"
              class="cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus-visible:focus-ring"
              :class="
                selectedTag === tag
                  ? 'border-primary bg-selected text-ink'
                  : 'border-line bg-fill text-muted hover:text-ink'
              "
              :aria-pressed="selectedTag === tag"
              @click="selectedTag = selectedTag === tag ? null : tag"
            >
              {{ tag }}
            </button>
          </div>
        </div>
        <p v-if="!filteredEntries.length" class="py-6 text-center text-sm text-muted">
          {{ t('common.noResults') }}
        </p>
        <ul v-else class="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))]">
          <li
            v-for="entry in filteredEntries"
            :key="entry.file"
            class="group flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-2.5 transition-colors hover:border-line-strong"
          >
            <div class="relative grid h-28 place-items-center overflow-hidden rounded-md bg-fill sm:h-32">
              <button
                type="button"
                class="grid size-full cursor-pointer place-items-center p-2 focus-visible:focus-ring"
                :aria-label="`${t('common.edit')}: ${entry.description}`"
                @click="openEdit(entry)"
              >
                <ImageOff v-if="broken.has(entry.file)" :size="20" class="text-subtle" aria-hidden="true" />
                <img
                  v-else
                  :src="image(entry.file)"
                  :alt="entry.description"
                  loading="lazy"
                  class="max-h-full max-w-full object-contain"
                  @error="broken.add(entry.file)"
                />
              </button>
              <div
                class="absolute top-1.5 right-1.5 z-10 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100"
                :class="removal.isPending.value && removal.variables.value === entry.file && 'opacity-100'"
              >
                <DropdownMenu :items="menu(entry)" align="end">
                  <IconButton
                    :icon="MoreHorizontal"
                    :label="t('common.more')"
                    size="sm"
                    variant="secondary"
                    :tooltip="false"
                    :loading="removal.isPending.value && removal.variables.value === entry.file"
                  />
                </DropdownMenu>
              </div>
            </div>
            <p class="line-clamp-2 text-sm text-ink-2">{{ entry.description }}</p>
            <div v-if="entry.emotions.length || entry.tags.length" class="flex flex-wrap gap-1">
              <Badge v-for="item in entry.emotions" :key="`e${item}`" tone="info">{{ item }}</Badge>
              <Badge v-for="item in extraTags(entry)" :key="`t${item}`">
                {{ item }}
              </Badge>
            </div>
          </li>
        </ul>
      </template>
    </FormSection>

    <FormSection v-if="filteredLoose.length" :title="t('personas.detail.stickers.loose')" :columns="1">
      <ul class="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))]">
        <li
          v-for="item in filteredLoose"
          :key="item.file"
          class="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-2.5"
        >
          <div class="grid h-28 place-items-center overflow-hidden rounded-md bg-fill p-2 sm:h-32">
            <img
              :src="image(item.file)"
              :alt="item.file"
              loading="lazy"
              class="max-h-full max-w-full object-contain"
            />
          </div>
          <p class="truncate font-mono text-xs text-muted" :title="item.file">{{ item.file }}</p>
          <div class="flex min-w-0 items-center justify-between gap-1.5">
            <Button size="sm" :icon="Pencil" @click="describe(item.file)">
              {{ t('personas.detail.stickers.describe') }}
            </Button>
            <IconButton
              :icon="Trash2"
              :label="t('common.delete')"
              size="sm"
              variant="danger-ghost"
              :loading="removal.isPending.value && removal.variables.value === item.file"
              @click="remove(item.file)"
            />
          </div>
        </li>
      </ul>
    </FormSection>
    <StickerDialog
      v-if="editing !== undefined && listing.data.value"
      :key="editing ? editing.file : '__new__'"
      :persona="persona"
      :listing="listing.data.value"
      :entry="editing"
      :has-next="Boolean(nextLoose)"
      @saved="saved"
      @failed="reread"
      @close="closeDialog"
    />
  </div>
</template>
