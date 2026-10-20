<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { resourcesApi, type ResourceEntry } from '../../../api/resources'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Textarea from '../../../ui/Textarea.vue'
import { toast } from '../../../ui/toast'

/** Copies a task file as a delivery (`register`) or into the group's shared materials (`adopt`). */
const props = defineProps<{ scene: string; entry: ResourceEntry; mode: 'register' | 'adopt' }>()
const emit = defineEmits<{ done: []; close: [] }>()

const { t } = useI18n()
const name = ref(props.entry.name)
const note = ref('')
const save = useMutation({
  mutationFn: () =>
    props.mode === 'register'
      ? resourcesApi.register(props.scene, { reference: props.entry.reference, name: name.value.trim(), note: note.value })
      : resourcesApi.adopt(props.scene, { reference: props.entry.reference, name: name.value.trim() }),
  onSuccess: (value) => {
    toast.success(t(`groups.tasks.space.${props.mode}Done`, { name: value.name }))
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
    :title="t(mode === 'register' ? 'groups.tasks.space.registerTitle' : 'groups.tasks.files.keepTitle')"
    size="sm"
    :busy="save.isPending.value"
  >
    <form id="copy-file" class="flex flex-col gap-3" @submit.prevent="name.trim() && save.mutate()">
      <Field :label="t('groups.tasks.files.keepName')">
        <Input v-model="name" />
      </Field>
      <Field v-if="mode === 'register'" :label="t('groups.tasks.space.note')">
        <Textarea v-model="note" :rows="2" :max-rows="6" />
      </Field>
      <ErrorNote v-if="save.isError.value" :title="t('groups.tasks.files.keepFailed')" :error="save.error.value" />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="save.isPending.value" @click="emit('close')">{{ t('common.cancel') }}</Button>
      <Button variant="primary" type="submit" form="copy-file" :loading="save.isPending.value" :disabled="!name.trim()">
        {{ t('common.save') }}
      </Button>
    </template>
  </Dialog>
</template>
