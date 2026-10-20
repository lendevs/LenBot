<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { schedulesApi } from '../../../api/schedules'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { toast } from '../../../ui/toast'
import SchedulePicker from './SchedulePicker.vue'

const props = defineProps<{ scene: string; timezone: string }>()
const emit = defineEmits<{ dirty: [value: boolean]; added: []; close: [] }>()

const { t } = useI18n()
const ACCOUNT = /^[a-z][a-z0-9_-]*:[^:\s/\\]+$/
const note = ref('')
const when = ref('')
const target = ref<'self' | 'other'>('self')
const account = ref('')
const targets = computed(() =>
  (['self', 'other'] as const).map((value) => ({ value, label: t(`groups.tasks.schedules.dialog.${value}`) })),
)
const accountError = computed(() =>
  target.value === 'other' && account.value.trim() && !ACCOUNT.test(account.value.trim())
    ? t('groups.tasks.schedules.dialog.accountInvalid')
    : null,
)
const ready = computed(
  () =>
    Boolean(note.value.trim() && when.value) &&
    (target.value === 'self' || (Boolean(account.value.trim()) && !accountError.value)),
)
const dirty = computed(() => Boolean(note.value.trim() || account.value.trim()))
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const create = useMutation({
  mutationFn: () =>
    schedulesApi.create(props.scene, {
      when: when.value,
      note: note.value.trim(),
      for: target.value === 'self' ? 'self' : account.value.trim(),
    }),
  onSuccess: () => {
    toast.success(t('groups.tasks.schedules.dialog.added'))
    emit('dirty', false)
    emit('added')
  },
})

const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) void close()
  },
})
async function close() {
  if (dirty.value && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') }))) return
  emit('dirty', false)
  emit('close')
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.tasks.schedules.dialog.title')" size="md" :busy="create.isPending.value">
    <form id="new-schedule" class="flex flex-col gap-4" @submit.prevent="ready && create.mutate()">
      <Field :label="t('groups.tasks.schedules.dialog.note')" required>
        <Textarea v-model="note" :rows="2" :max-rows="6" />
      </Field>
      <SchedulePicker v-model="when" :timezone="timezone" />
      <Field :label="t('groups.tasks.schedules.dialog.target')">
        <SegmentedControl v-model="target" :options="targets" size="sm" class="self-start" />
      </Field>
      <Field v-if="target === 'other'" :label="t('groups.tasks.schedules.dialog.account')" :error="accountError">
        <Input v-model="account" mono placeholder="onebot:10001" />
      </Field>
      <ErrorNote v-if="create.isError.value" :title="t('groups.tasks.schedules.dialog.failed')" :error="create.error.value" />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="create.isPending.value" @click="close">{{ t('common.cancel') }}</Button>
      <Button variant="primary" type="submit" form="new-schedule" :loading="create.isPending.value" :disabled="!ready">
        {{ t('groups.tasks.schedules.dialog.add') }}
      </Button>
    </template>
  </Dialog>
</template>
