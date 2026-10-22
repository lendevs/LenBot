<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ImageUp } from '@lucide/vue'
import { personasApi, type StickerEntry, type StickerListing } from '../../../api/personas'
import { formatBytes } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'

/** `entry` null adds a new image; an entry with an empty description describes an image already uploaded. */
const props = defineProps<{ persona: string; listing: StickerListing; entry: StickerEntry | null }>()
const emit = defineEmits<{ saved: [result: StickerListing]; failed: []; close: [] }>()

const { t } = useI18n()
const picker = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const preview = ref<string | null>(null)
watch(file, (value) => {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = value ? URL.createObjectURL(value) : null
})
onBeforeUnmount(() => preview.value && URL.revokeObjectURL(preview.value))
const description = ref(props.entry?.description ?? '')
const emotions = ref([...(props.entry?.emotions ?? [])])
const tags = ref([...(props.entry?.tags ?? [])])
const image = computed(
  () =>
    preview.value ??
    (props.entry
      ? personasApi.stickerImage(props.persona, props.listing.saved_path, props.entry.file)
      : null),
)
const ready = computed(() => Boolean(description.value.trim() && (props.entry || file.value)))

// A new image is uploaded first and then listed in the index; the index is created empty when missing.
const save = useMutation({
  mutationFn: async () => {
    const directory = props.listing.saved_path
    let current = props.listing.entries ?? []
    let name = props.entry?.file
    if (!name) {
      if (props.listing.entries === null)
        current = (await personasApi.saveStickers(props.persona, directory, [])).entries ?? []
      name = (await personasApi.uploadSticker(props.persona, directory, file.value!)).file
    }
    const entry = {
      file: name,
      description: description.value.trim(),
      emotions: emotions.value,
      tags: tags.value,
    }
    const known = current.some((item) => item.file === name)
    return personasApi.saveStickers(
      props.persona,
      directory,
      known ? current.map((item) => (item.file === name ? entry : item)) : [...current, entry],
    )
  },
  onSuccess: (result) => emit('saved', result),
  onError: () => emit('failed'),
})
function chosen(event: Event) {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
  input.value = ''
}
const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})
</script>

<template>
  <Dialog
    v-model:open="open"
    :title="entry ? t('personas.detail.stickers.editTitle') : t('personas.detail.stickers.addTitle')"
    :busy="save.isPending.value"
  >
    <form id="sticker-form" class="flex flex-col gap-4" @submit.prevent="ready && save.mutate()">
      <div class="flex items-center gap-4">
        <div class="grid size-28 shrink-0 place-items-center overflow-hidden rounded-lg bg-fill">
          <img v-if="image" :src="image" alt="" class="max-h-full max-w-full object-contain" />
          <ImageUp v-else :size="24" class="text-subtle" aria-hidden="true" />
        </div>
        <div v-if="!entry" class="flex min-w-0 flex-col gap-1.5">
          <input
            ref="picker"
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            class="sr-only"
            tabindex="-1"
            aria-hidden="true"
            @change="chosen"
          />
          <Button
            size="sm"
            :icon="ImageUp"
            :disabled="save.isPending.value"
            class="self-start"
            @click="picker?.click()"
          >
            {{ t('personas.detail.stickers.choose') }}
          </Button>
          <span v-if="file" class="truncate text-sm text-ink-2">
            {{ file.name }} ·
            <span class="tabular">{{ formatBytes(file.size) }}</span>
          </span>
          <span v-else class="text-xs text-subtle">PNG · JPG · GIF · WebP · 10 MB</span>
        </div>
      </div>
      <Field :label="t('personas.detail.stickers.description')" required>
        <Textarea v-model="description" :rows="2" />
      </Field>
      <Field :label="t('personas.detail.stickers.emotions')">
        <TagInput v-model="emotions" />
      </Field>
      <Field :label="t('personas.detail.stickers.tags')">
        <TagInput v-model="tags" />
      </Field>
      <ErrorNote
        v-if="save.isError.value"
        :title="t('personas.detail.stickers.saveFailed')"
        :error="save.error.value"
      />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="save.isPending.value" @click="emit('close')">
        {{ t('common.cancel') }}
      </Button>
      <Button
        variant="primary"
        type="submit"
        form="sticker-form"
        :loading="save.isPending.value"
        :disabled="!ready"
      >
        {{ t('common.save') }}
      </Button>
    </template>
  </Dialog>
</template>
