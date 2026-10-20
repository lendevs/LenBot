<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { Paperclip } from '@lucide/vue'
import { resourcesApi } from '../../../api/resources'
import { formatBytes } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string }>()
const emit = defineEmits<{ done: []; close: [] }>()

const { t } = useI18n()
const picker = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const name = ref('')
function chosen(event: Event) {
  const value = (event.target as HTMLInputElement).files?.[0] ?? null
  file.value = value
  if (value) name.value = value.name
}
const upload = useMutation({
  mutationFn: () => resourcesApi.upload(props.scene, file.value!, name.value.trim()),
  onSuccess: (value) => {
    toast.success(t('groups.tasks.space.uploaded', { name: value.name }))
    emit('done')
    emit('close')
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
    :title="t('groups.tasks.space.uploadTitle')"
    size="sm"
    :busy="upload.isPending.value"
  >
    <form
      id="upload-file"
      class="flex flex-col gap-3"
      @submit.prevent="file && name.trim() && upload.mutate()"
    >
      <input ref="picker" type="file" class="sr-only" tabindex="-1" aria-hidden="true" @change="chosen" />
      <div class="flex min-w-0 items-center gap-3">
        <Button size="sm" :icon="Paperclip" :disabled="upload.isPending.value" @click="picker?.click()">
          {{ t('groups.tasks.space.choose') }}
        </Button>
        <span v-if="file" class="min-w-0 truncate text-sm text-ink-2">
          {{ file.name }} ·
          <span class="tabular">{{ formatBytes(file.size) }}</span>
        </span>
      </div>
      <Field v-if="file" :label="t('groups.tasks.files.keepName')">
        <Input v-model="name" :disabled="upload.isPending.value" />
      </Field>
      <ErrorNote
        v-if="upload.isError.value"
        :title="t('groups.tasks.space.uploadFailed')"
        :error="upload.error.value"
      />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="upload.isPending.value" @click="emit('close')">
        {{ t('common.cancel') }}
      </Button>
      <Button
        variant="primary"
        type="submit"
        form="upload-file"
        :loading="upload.isPending.value"
        :disabled="!file || !name.trim()"
      >
        {{ t('groups.tasks.space.upload') }}
      </Button>
    </template>
  </Dialog>
</template>
