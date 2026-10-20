<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { Paperclip } from '@lucide/vue'
import { personasApi, validFolder, type PersonaRole } from '../../api/personas'
import { formatBytes } from '../../i18n/format'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import { toast } from '../../ui/toast'

export type CreateRequest = { kind: 'create' } | { kind: 'import' } | { kind: 'copy'; source: PersonaRole }

/** Each of the three makes a new folder, which is also the role's id. */
const props = defineProps<{ request: CreateRequest }>()
const emit = defineEmits<{ done: [folder: string]; close: [] }>()

const { t } = useI18n()
const source = props.request.kind === 'copy' ? props.request.source : null
const name = ref(source ? t('personas.create.copyName', { name: source.name || source.key }) : '')
const folder = ref(
  source
    ? `${source.key}-copy`
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '')
        .replace(/^-+/, '')
    : '',
)
const picker = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
function chosen(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
const folderError = computed(() =>
  folder.value && !validFolder(folder.value) ? t('personas.create.folderInvalid') : null,
)
const ready = computed(
  () =>
    validFolder(folder.value) &&
    (props.request.kind === 'import' ? file.value !== null : Boolean(name.value.trim())),
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
      <Field v-if="request.kind !== 'import'" :label="t('personas.create.name')" required>
        <Input v-model="name" autofocus />
      </Field>
      <Field :label="t('personas.create.folder')" required :error="folderError">
        <Input v-model="folder" mono placeholder="jiaran" />
      </Field>
      <template v-if="request.kind === 'import'">
        <input
          ref="picker"
          type="file"
          accept=".zip,application/zip"
          class="sr-only"
          tabindex="-1"
          aria-hidden="true"
          @change="chosen"
        />
        <div class="flex min-w-0 items-center gap-3">
          <Button size="sm" :icon="Paperclip" :disabled="save.isPending.value" @click="picker?.click()">
            {{ t('personas.create.choose') }}
          </Button>
          <span v-if="file" class="min-w-0 truncate text-sm text-ink-2">
            {{ file.name }} ·
            <span class="tabular">{{ formatBytes(file.size) }}</span>
          </span>
        </div>
      </template>
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
