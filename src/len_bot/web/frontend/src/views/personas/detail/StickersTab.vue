<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ImageOff, MoreHorizontal, Pencil, Plus, Smile, Trash2 } from '@lucide/vue'
import { keys } from '../../../api/query'
import { personasApi, type StickerEntry, type StickerListing } from '../../../api/personas'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import FormSection from '../../../ui/FormSection.vue'
import IconButton from '../../../ui/IconButton.vue'
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
/** Images in the folder that the index does not list yet. */
const loose = computed(() =>
  (listing.data.value?.files ?? []).filter(
    (file) => !entries.value.some((entry) => entry.file === file.file),
  ),
)
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
      <ul v-else class="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-3">
        <li
          v-for="entry in entries"
          :key="entry.file"
          class="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-3"
        >
          <div class="relative grid h-32 place-items-center overflow-hidden rounded-md bg-fill">
            <ImageOff v-if="broken.has(entry.file)" :size="20" class="text-subtle" aria-hidden="true" />
            <img
              v-else
              :src="image(entry.file)"
              :alt="entry.description"
              loading="lazy"
              class="max-h-full max-w-full object-contain"
              @error="broken.add(entry.file)"
            />
            <DropdownMenu :items="menu(entry)">
              <IconButton
                :icon="MoreHorizontal"
                :label="t('common.more')"
                size="sm"
                variant="secondary"
                :tooltip="false"
                :loading="removal.isPending.value && removal.variables.value === entry.file"
                class="absolute top-1.5 right-1.5"
              />
            </DropdownMenu>
          </div>
          <p class="line-clamp-2 text-sm text-ink-2">{{ entry.description }}</p>
          <div v-if="entry.emotions.length || entry.tags.length" class="flex flex-wrap gap-1">
            <Badge v-for="item in entry.emotions" :key="`e${item}`" tone="brand">{{ item }}</Badge>
            <Badge v-for="item in entry.tags" :key="`t${item}`">{{ item }}</Badge>
          </div>
        </li>
      </ul>
    </FormSection>

    <FormSection v-if="loose.length" :title="t('personas.detail.stickers.loose')" :columns="1">
      <ul class="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-3">
        <li
          v-for="item in loose"
          :key="item.file"
          class="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-3"
        >
          <div class="grid h-32 place-items-center overflow-hidden rounded-md bg-fill">
            <img
              :src="image(item.file)"
              :alt="item.file"
              loading="lazy"
              class="max-h-full max-w-full object-contain"
            />
          </div>
          <p class="truncate font-mono text-xs text-muted" :title="item.file">{{ item.file }}</p>
          <div class="flex gap-1">
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
