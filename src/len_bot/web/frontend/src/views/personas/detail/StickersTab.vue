<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ImageOff, MoreHorizontal, Pencil, Plus, Search, Smile, Trash2 } from '@lucide/vue'
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
const keyword = computed(() => search.value.trim().toLowerCase())
const filteredEntries = computed(() => {
  const q = keyword.value
  if (!q) return entries.value
  return entries.value.filter((entry) =>
    [entry.file, entry.description, ...entry.emotions, ...entry.tags].some((part) =>
      part.toLowerCase().includes(q),
    ),
  )
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
function saved(result: StickerListing) {
  editing.value = undefined
  client.setQueryData(listingKey.value, result)
  writes.done(result)
}
// A failed add may still have uploaded the image; read the folder again so it shows up.
const reread = () => void listing.refetch()

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
  { label: t('common.edit'), icon: Pencil, select: () => (editing.value = entry) },
  { type: 'separator' },
  { label: t('common.delete'), icon: Trash2, danger: true, select: () => void remove(entry.file) },
]
const describe = (file: string) => (editing.value = { file, description: '', emotions: [], tags: [] })
</script>

<template>
  <Skeleton v-if="listing.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="listing.isError.value"
    :title="t('personas.detail.stickers.readFailed')"
    :error="listing.error.value"
    :retry="listing.refetch"
  />
  <div v-else class="flex flex-col gap-8">
    <FormSection :title="t('personas.detail.stickers.title')" :columns="1">
      <template #actions>
        <Button size="sm" :icon="Plus" @click="editing = null">
          {{ t('personas.detail.stickers.add') }}
        </Button>
      </template>
      <EmptyState v-if="!entries.length" :icon="Smile" :title="t('personas.detail.stickers.empty')" compact />
      <template v-else>
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
                @click="editing = entry"
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
      :persona="persona"
      :listing="listing.data.value"
      :entry="editing"
      @saved="saved"
      @failed="reread"
      @close="editing = undefined"
    />
  </div>
</template>
