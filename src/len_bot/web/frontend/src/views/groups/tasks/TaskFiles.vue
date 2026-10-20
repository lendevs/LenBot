<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { Download, FileText, FolderInput } from '@lucide/vue'
import { keys } from '../../../api/query'
import { tasksApi, type RegisteredFile } from '../../../api/tasks'
import { formatBytes } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { uploadTone } from './labels'

const props = defineProps<{ scene: string; taskId: number; files: RegisteredFile[]; canKeep: boolean }>()

const { t } = useI18n()
const client = useQueryClient()

const download = useMutation({
  mutationFn: (file: RegisteredFile) => tasksApi.download(props.scene, props.taskId, file.id),
  onSuccess: (blob, file) => {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
  onError: (error) =>
    toast.error(t('groups.tasks.files.downloadFailed'), { detail: describeError(error, t('ui.error.network')).message }),
})

/** Copying a delivered file into the group's shared materials. */
const keeping = ref<RegisteredFile | null>(null)
const name = ref('')
const keepOpen = computed({
  get: () => keeping.value !== null,
  set: (value: boolean) => {
    if (!value) keeping.value = null
  },
})
function startKeep(file: RegisteredFile) {
  keeping.value = file
  name.value = file.name
  keep.reset()
}
const keep = useMutation({
  mutationFn: async () => {
    const materials = await tasksApi.materials(props.scene)
    return tasksApi.adoptMaterial(props.scene, {
      task_id: props.taskId,
      file_id: keeping.value!.id,
      name: name.value.trim(),
      directory: materials.directory,
    })
  },
  onSuccess: (result) => {
    keeping.value = null
    toast.success(t('groups.tasks.files.kept', { name: result.name }))
    void client.invalidateQueries({ queryKey: keys.tasks.materials(props.scene) })
  },
})
</script>

<template>
  <section class="flex flex-col gap-2">
    <h3 class="text-sm font-medium text-ink">{{ t('groups.tasks.files.title') }}</h3>
    <ul class="flex list-none flex-col divide-y divide-line rounded-lg border border-line">
      <li v-for="file in files" :key="file.id" class="flex flex-col gap-1.5 px-3 py-2">
        <div class="flex items-center gap-2.5">
          <FileText :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm text-ink">{{ file.name }}</p>
            <p class="text-xs text-muted">
              <span class="tabular">{{ formatBytes(file.size) }}</span>
              <template v-if="file.note"> · {{ file.note }}</template>
              <template v-if="!file.exists"> · {{ t('groups.tasks.files.missing') }}</template>
            </p>
          </div>
          <Badge v-if="file.upload" :tone="uploadTone[file.upload.status] ?? 'neutral'" size="sm">
            {{ t(`groups.tasks.files.upload.${file.upload.status}`) }}
          </Badge>
          <IconButton
            v-if="canKeep && file.exists"
            :icon="FolderInput"
            :label="t('groups.tasks.files.keep')"
            variant="ghost"
            size="sm"
            @click="startKeep(file)"
          />
          <IconButton
            :icon="Download"
            :label="t('groups.tasks.files.download')"
            variant="ghost"
            size="sm"
            :disabled="!file.exists || (download.isPending.value && download.variables.value?.id === file.id)"
            @click="download.mutate(file)"
          />
        </div>
        <ErrorNote v-if="file.upload?.error" :title="t('groups.tasks.files.uploadFailed')" :error="String(file.upload.error)" />
      </li>
    </ul>

    <Dialog v-model:open="keepOpen" :title="t('groups.tasks.files.keepTitle')" size="sm" :busy="keep.isPending.value">
      <form id="keep-file" class="flex flex-col gap-3" @submit.prevent="keep.mutate()">
        <Field :label="t('groups.tasks.files.keepName')">
          <Input v-model="name" />
        </Field>
        <ErrorNote v-if="keep.isError.value" :title="t('groups.tasks.files.keepFailed')" :error="keep.error.value" />
      </form>
      <template #footer>
        <Button variant="ghost" :disabled="keep.isPending.value" @click="keeping = null">{{ t('common.cancel') }}</Button>
        <Button variant="primary" type="submit" form="keep-file" :loading="keep.isPending.value" :disabled="!name.trim()">
          {{ t('common.save') }}
        </Button>
      </template>
    </Dialog>
  </section>
</template>
