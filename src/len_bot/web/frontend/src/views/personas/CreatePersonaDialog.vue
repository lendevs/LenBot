<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { FileArchive, Upload } from '@lucide/vue'
import { personasApi, validFolder, type PersonaRole } from '../../api/personas'
import { formatBytes } from '../../i18n/format'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import { toast } from '../../ui/toast'

export type CreateRequest = { kind: 'create' } | { kind: 'import' } | { kind: 'copy'; source: PersonaRole }

const MAX_ZIP_BYTES = 64 * 1024 * 1024
const MAX_LENGTH = 64

function sanitizeSlug(raw: string, maxLength = MAX_LENGTH): string {
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, maxLength)
    .replace(/-+$/, '')
}

function suggestCopyFolder(sourceKey: string): string {
  const suffix = '-copy'
  const stem = sanitizeSlug(sourceKey, MAX_LENGTH - suffix.length)
  return stem ? `${stem}${suffix}` : 'copy'
}

function suggestZipFolder(filename: string): string {
  const withoutExt = filename.replace(/\.zip$/i, '')
  const stripped = withoutExt.replace(/^persona-/i, '')
  return sanitizeSlug(stripped || withoutExt)
}

/** Each of the three makes a new folder, which is also the role's id. */
const props = withDefaults(defineProps<{ request: CreateRequest; existingKeys?: string[] }>(), {
  existingKeys: () => [],
})
const emit = defineEmits<{ done: [folder: string]; close: [] }>()

const { t } = useI18n()
const source = props.request.kind === 'copy' ? props.request.source : null
const initialCopyName = () => {
  if (!source) return ''
  const rawName = source.name || source.key
  const full = t('personas.create.copyName', { name: rawName })
  if (full.length <= MAX_LENGTH) return full
  const overhead = t('personas.create.copyName', { name: '' }).length
  const allowed = Math.max(1, MAX_LENGTH - overhead)
  return t('personas.create.copyName', { name: rawName.slice(0, allowed).trimEnd() }).slice(0, MAX_LENGTH)
}
const name = ref(initialCopyName())
const folder = ref(source ? suggestCopyFolder(source.key) : '')
const picker = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const fileError = ref<string | null>(null)
const dragging = ref(false)
let dragDepth = 0

function selectFile(picked: File | null) {
  fileError.value = null
  if (!picked) {
    file.value = null
    return
  }
  if (!picked.name.toLowerCase().endsWith('.zip')) {
    file.value = null
    fileError.value = t('personas.create.zipOnly')
    return
  }
  file.value = picked
  if (picked.size > MAX_ZIP_BYTES) {
    fileError.value = t('personas.create.zipTooLarge', { max: '64 MiB' })
  }
  if (!folder.value.trim()) {
    const suggested = suggestZipFolder(picked.name)
    if (suggested && validFolder(suggested)) folder.value = suggested
  }
}

function chosen(event: Event) {
  const input = event.target as HTMLInputElement
  selectFile(input.files?.[0] ?? null)
  input.value = ''
}

function onDragEnter(event: DragEvent) {
  if (save.isPending.value) return
  event.preventDefault()
  dragDepth += 1
  dragging.value = true
}
function onDragOver(event: DragEvent) {
  if (save.isPending.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  dragging.value = true
}
function onDragLeave(event: DragEvent) {
  if (save.isPending.value) return
  event.preventDefault()
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragging.value = false
  }
}
function onDrop(event: DragEvent) {
  if (save.isPending.value) return
  event.preventDefault()
  dragDepth = 0
  dragging.value = false
  const dropped = event.dataTransfer?.files?.[0] ?? null
  if (dropped) selectFile(dropped)
}

const existingSet = computed(() => new Set(props.existingKeys))
const folderTaken = computed(() => Boolean(folder.value) && existingSet.value.has(folder.value))
const folderError = computed(() => {
  if (!folder.value) return null
  if (!validFolder(folder.value)) return t('personas.create.folderInvalid')
  if (folderTaken.value) return t('personas.create.folderTaken')
  return null
})
const nameError = computed(() =>
  props.request.kind !== 'import' && name.value.trim().length > MAX_LENGTH
    ? t('personas.create.nameTooLong')
    : null,
)
const ready = computed(
  () =>
    validFolder(folder.value) &&
    !folderTaken.value &&
    (props.request.kind === 'import'
      ? file.value !== null && !fileError.value
      : Boolean(name.value.trim()) && !nameError.value),
)

const save = useMutation({
  mutationFn: async () => {
    if (props.request.kind === 'import') {
      const result = await personasApi.importZip(folder.value, file.value!)
      return result.renamed_id
        ? t('personas.create.renamed', { id: result.renamed_id.to })
        : t('personas.create.imported')
    }
    if (props.request.kind === 'copy')
      await personasApi.copy(props.request.source.key, folder.value, name.value.trim())
    else await personasApi.create(folder.value, name.value.trim())
    return t(props.request.kind === 'copy' ? 'personas.create.copied' : 'personas.create.created')
  },
  onSuccess: (message) => {
    toast.success(message)
    emit('done', folder.value)
  },
})
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
    :title="t(`personas.create.${request.kind}Title`)"
    size="sm"
    :busy="save.isPending.value"
  >
    <form id="create-persona" class="flex flex-col gap-4" @submit.prevent="ready && save.mutate()">
      <Field v-if="request.kind !== 'import'" :label="t('personas.create.name')" :error="nameError" required>
        <Input v-model="name" autofocus />
      </Field>
      <Field :label="t('personas.create.folder')" required :error="folderError">
        <Input v-model="folder" mono placeholder="jiaran" />
      </Field>
      <Field
        v-if="request.kind === 'import'"
        :label="t('personas.create.choose')"
        :error="fileError"
        required
      >
        <input
          ref="picker"
          type="file"
          accept=".zip,application/zip"
          class="sr-only"
          tabindex="-1"
          aria-hidden="true"
          @change="chosen"
        />
        <button
          type="button"
          :disabled="save.isPending.value"
          class="flex w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed px-4 py-5 text-center transition-colors focus-visible:focus-ring disabled:pointer-events-none disabled:opacity-50"
          :class="
            dragging
              ? 'border-primary bg-selected/40 text-ink'
              : fileError
                ? 'border-error bg-error-bg/40 text-ink'
                : 'border-line-strong bg-fill/40 text-muted hover:border-subtle hover:bg-hover/50 hover:text-ink'
          "
          @click="picker?.click()"
          @dragenter="onDragEnter"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
        >
          <FileArchive v-if="file" :size="20" class="shrink-0 text-primary" aria-hidden="true" />
          <Upload v-else :size="20" class="shrink-0" aria-hidden="true" />
          <template v-if="file">
            <span class="max-w-full truncate text-sm font-medium text-ink">{{ file.name }}</span>
            <span class="text-xs text-muted tabular">
              {{ formatBytes(file.size) }} · {{ t('personas.create.replaceZip') }}
            </span>
          </template>
          <span v-else class="text-sm">{{ t('personas.create.dropZip') }}</span>
        </button>
      </Field>
      <ErrorNote v-if="save.isError.value" :title="t('personas.create.failed')" :error="save.error.value" />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="save.isPending.value" @click="emit('close')">
        {{ t('common.cancel') }}
      </Button>
      <Button
        variant="primary"
        type="submit"
        form="create-persona"
        :loading="save.isPending.value"
        :disabled="!ready"
      >
        {{ t(`personas.create.${request.kind}`) }}
      </Button>
    </template>
  </Dialog>
</template>
