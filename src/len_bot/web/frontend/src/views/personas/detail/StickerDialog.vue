<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ImageUp } from '@lucide/vue'
import { personasApi, type StickerEntry, type StickerListing } from '../../../api/personas'
import { formatBytes } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'

/** `entry` null adds a new image; an entry with an empty description describes an image already uploaded. */
const props = defineProps<{
  persona: string
  listing: StickerListing
  entry: StickerEntry | null
  hasNext?: boolean
}>()
const emit = defineEmits<{ saved: [result: StickerListing, continueNext: boolean]; failed: []; close: [] }>()

const { t } = useI18n()
const mac = /Mac|iPhone|iPad/.test(navigator.platform)
const picker = ref<HTMLInputElement | null>(null)
const descArea = ref<InstanceType<typeof Textarea> | null>(null)
const file = ref<File | null>(null)
const fileName = ref('')
/** Records a successfully uploaded filename in add mode so retrying step 2 skips re-uploading and avoids 409. */
const uploadedName = ref<string | null>(null)
const preview = ref<string | null>(null)
watch(file, (value) => {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = value ? URL.createObjectURL(value) : null
})
onBeforeUnmount(() => preview.value && URL.revokeObjectURL(preview.value))

const description = ref(props.entry?.description ?? '')
const emotions = ref([...(props.entry?.emotions ?? [])])
const tags = ref([...(props.entry?.tags ?? [])])

onMounted(() => {
  if (props.entry) {
    void nextTick(() => descArea.value?.focus())
  }
})

const image = computed(
  () =>
    preview.value ??
    (props.entry
      ? personasApi.stickerImage(props.persona, props.listing.saved_path, props.entry.file)
      : uploadedName.value
        ? personasApi.stickerImage(props.persona, props.listing.saved_path, uploadedName.value)
        : null),
)

const existingFiles = computed(() => new Set(props.listing.files.map((item) => item.file)))
const validStickerName = (value: string) => {
  if (!value || value === 'index.yaml' || value.includes('\\')) return false
  return value.split('/').every((part) => {
    if (!part || part === '.' || part === '..') return false
    for (let i = 0; i < part.length; i++) {
      if (part.charCodeAt(i) < 32) return false
    }
    return true
  })
}
const fileNameError = computed(() => {
  if (props.entry || uploadedName.value || !file.value) return null
  const trimmed = fileName.value.trim()
  if (!trimmed) return t('personas.detail.stickers.fileNameRequired')
  if (!validStickerName(trimmed)) return t('personas.detail.stickers.fileNameInvalid')
  if (existingFiles.value.has(trimmed)) return t('personas.detail.stickers.fileTaken')
  return null
})

const frequentEmotions = computed(() => {
  const counts = new Map<string, number>()
  for (const item of props.listing.entries ?? []) {
    for (const emotion of item.emotions) {
      const trimmed = emotion.trim()
      if (trimmed) counts.set(trimmed, (counts.get(trimmed) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 12)
    .map(([name]) => name)
})

function toggleEmotion(value: string) {
  if (emotions.value.includes(value)) {
    emotions.value = emotions.value.filter((item) => item !== value)
  } else {
    emotions.value = [...emotions.value, value]
  }
}

const ready = computed(() =>
  Boolean(
    description.value.trim() && (props.entry || uploadedName.value || (file.value && !fileNameError.value)),
  ),
)

// A new image is uploaded first and then listed in the index; the index is created empty when missing.
const save = useMutation({
  mutationFn: async (continueNext: boolean) => {
    const directory = props.listing.saved_path
    let current = props.listing.entries ?? []
    let name = props.entry?.file ?? uploadedName.value
    if (!name) {
      if (props.listing.entries === null) {
        current = (await personasApi.saveStickers(props.persona, directory, [])).entries ?? []
      }
      const targetName = fileName.value.trim() || file.value!.name
      name = (await personasApi.uploadSticker(props.persona, directory, file.value!, targetName)).file
      uploadedName.value = name
    }
    const entry = {
      file: name,
      description: description.value.trim(),
      emotions: emotions.value,
      tags: tags.value,
    }
    const known = current.some((item) => item.file === name)
    const result = await personasApi.saveStickers(
      props.persona,
      directory,
      known ? current.map((item) => (item.file === name ? entry : item)) : [...current, entry],
    )
    return { result, continueNext }
  },
  onSuccess: ({ result, continueNext }) => emit('saved', result, continueNext),
  onError: () => emit('failed'),
})

function submit(continueNext = false) {
  if (!ready.value || save.isPending.value) return
  save.mutate(continueNext)
}

function onFormKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || !(mac ? event.metaKey : event.ctrlKey)) return
  if (!ready.value || save.isPending.value) return
  event.preventDefault()
  submit(Boolean(props.hasNext))
}

function chosen(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0] ?? null
  input.value = ''
  if (!picked) return
  file.value = picked
  fileName.value = picked.name
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
    <form
      id="sticker-form"
      class="flex flex-col gap-4"
      @submit.prevent="submit(false)"
      @keydown="onFormKeydown"
    >
      <div class="flex flex-wrap items-start gap-4">
        <div
          class="grid size-32 shrink-0 place-items-center overflow-hidden rounded-lg border border-line bg-fill p-2 sm:size-40"
        >
          <img v-if="image" :src="image" alt="" class="max-h-full max-w-full object-contain" />
          <ImageUp v-else :size="28" class="text-subtle" aria-hidden="true" />
        </div>
        <div class="flex min-w-0 flex-1 flex-col gap-2">
          <template v-if="!entry">
            <input
              ref="picker"
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              class="sr-only"
              tabindex="-1"
              aria-hidden="true"
              @change="chosen"
            />
            <div>
              <Button
                size="sm"
                :icon="ImageUp"
                :disabled="save.isPending.value || Boolean(uploadedName)"
                @click="picker?.click()"
              >
                {{ t('personas.detail.stickers.choose') }}
              </Button>
            </div>
            <span v-if="file" class="truncate text-xs text-muted tabular">
              {{ formatBytes(file.size) }}
            </span>
            <Field
              v-if="file || uploadedName"
              :label="t('personas.detail.stickers.fileName')"
              :error="fileNameError"
              required
            >
              <Input
                v-model="fileName"
                mono
                size="sm"
                :disabled="save.isPending.value || Boolean(uploadedName)"
              />
            </Field>
          </template>
          <code v-else class="truncate font-mono text-xs text-muted" :title="entry.file">
            {{ entry.file }}
          </code>
        </div>
      </div>

      <Field :label="t('personas.detail.stickers.description')" required>
        <Textarea ref="descArea" v-model="description" :rows="2" />
      </Field>
      <Field :label="t('personas.detail.stickers.emotions')">
        <div class="flex flex-col gap-2">
          <TagInput v-model="emotions" />
          <div v-if="frequentEmotions.length" class="flex flex-wrap gap-1.5">
            <button
              v-for="item in frequentEmotions"
              :key="item"
              type="button"
              class="cursor-pointer rounded-full border px-2 py-0.5 text-xs font-medium transition-colors focus-visible:focus-ring"
              :class="
                emotions.includes(item)
                  ? 'border-primary bg-selected text-ink'
                  : 'border-line bg-fill text-muted hover:text-ink'
              "
              :aria-pressed="emotions.includes(item)"
              @click="toggleEmotion(item)"
            >
              {{ item }}
            </button>
          </div>
        </div>
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
        :variant="hasNext ? 'secondary' : 'primary'"
        type="submit"
        form="sticker-form"
        :loading="save.isPending.value && save.variables.value === false"
        :disabled="!ready || save.isPending.value"
      >
        {{ t('common.save') }}
      </Button>
      <Button
        v-if="hasNext"
        variant="primary"
        type="button"
        :loading="save.isPending.value && save.variables.value === true"
        :disabled="!ready || save.isPending.value"
        @click="submit(true)"
      >
        {{ t('personas.detail.stickers.saveAndNext') }}
        <span class="ml-0.5 text-2xs font-medium opacity-75 max-sm:hidden">
          {{ mac ? '⌘↵' : 'Ctrl ↵' }}
        </span>
      </Button>
    </template>
  </Dialog>
</template>
