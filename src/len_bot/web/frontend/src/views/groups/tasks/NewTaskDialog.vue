<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import type { ResourceInput } from '../../../api/resources'
import { tasksApi, type Task } from '../../../api/tasks'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import Combobox from '../../../ui/Combobox.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { toast } from '../../../ui/toast'

/** `resources` are files picked from task spaces; each can be renamed for the new task's inputs. */
const props = withDefaults(defineProps<{ scene: string; resources?: ResourceInput[] }>(), { resources: () => [] })
const emit = defineEmits<{ dirty: [value: boolean]; created: [task: Task]; close: [] }>()

const { t } = useI18n()
const goal = ref('')
const deliverable = ref('')
const context = ref('')
const materials = ref<string[]>([])
const accountBrowser = ref(false)
const picked = ref(props.resources.map((item) => ({ reference: { ...item.reference }, name: item.name })))

const shared = useQuery({
  queryKey: computed(() => keys.tasks.materials(props.scene)),
  queryFn: ({ signal }) => tasksApi.materials(props.scene, signal),
})
const options = computed(() => (shared.data.value?.files ?? []).map((file) => ({ value: file.name, label: file.name })))

const dirty = computed(() =>
  Boolean(goal.value || deliverable.value || context.value || materials.value.length || accountBrowser.value),
)
watch(dirty, (value) => emit('dirty', value), { immediate: true })
const names = computed(() => [...materials.value, ...picked.value.map((item) => item.name.trim())])
const problem = computed(() => {
  if (names.value.length > 16) return t('groups.tasks.new.tooMany')
  if (picked.value.some((item) => !item.name.trim() || item.name.length > 240 || /[/\\\0\r\n]/.test(item.name)))
    return t('groups.tasks.new.badName')
  if (new Set(names.value).size !== names.value.length) return t('groups.tasks.new.duplicate')
  return null
})

const create = useMutation({
  mutationFn: () =>
    tasksApi.delegate(props.scene, {
      goal: goal.value.trim(),
      deliverable: deliverable.value.trim(),
      context: context.value.trim(),
      account_browser: accountBrowser.value,
      materials: materials.value,
      resources: picked.value.map((item) => ({ reference: item.reference, name: item.name.trim() })),
    }),
  onSuccess: (task) => {
    toast.success(t('groups.tasks.new.created'))
    emit('created', task)
  },
})

const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) void close()
  },
})
async function close() {
  if (dirty.value && !(await confirm({ title: t('groups.tasks.new.discardTitle'), confirmLabel: t('common.discard') })))
    return
  emit('dirty', false)
  emit('close')
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.tasks.new.title')" size="md" :busy="create.isPending.value">
    <form id="new-task" class="flex flex-col gap-4" @submit.prevent="create.mutate()">
      <Field :label="t('groups.tasks.new.goal')" required>
        <Textarea v-model="goal" :rows="3" :max-rows="8" />
      </Field>
      <Field :label="t('groups.tasks.new.deliverable')" required>
        <Textarea v-model="deliverable" :rows="2" :max-rows="6" :placeholder="t('groups.tasks.new.deliverablePlaceholder')" />
      </Field>
      <Field :label="t('groups.tasks.new.context')">
        <Textarea v-model="context" :rows="2" :max-rows="8" />
      </Field>
      <Field :label="t('groups.tasks.new.materials')" :error="picked.length ? null : problem">
        <Combobox
          v-model="materials"
          :options="options"
          multiple
          :disabled="shared.isPending.value || !options.length"
          :placeholder="shared.isSuccess.value && !options.length ? t('groups.tasks.new.noMaterials') : undefined"
        />
      </Field>
      <Field v-if="picked.length" :label="t('groups.tasks.new.picked')" :error="problem">
        <ul class="flex list-none flex-col gap-2">
          <li v-for="(item, index) in picked" :key="index" class="flex items-center gap-2">
            <div class="min-w-0 flex-1"><Input v-model="item.name" size="sm" /></div>
            <Button size="sm" variant="ghost" @click="picked.splice(index, 1)">{{ t('groups.tasks.new.remove') }}</Button>
          </li>
        </ul>
      </Field>
      <ErrorNote v-if="shared.isError.value" :title="t('groups.tasks.new.materialsFailed')" :error="shared.error.value" />
      <label class="flex cursor-pointer items-center gap-2 text-sm">
        <Checkbox :model-value="accountBrowser" @update:model-value="(on) => (accountBrowser = on === true)" />
        {{ t('groups.tasks.new.accountBrowser') }}
      </label>
      <ErrorNote v-if="create.isError.value" :title="t('groups.tasks.new.failed')" :error="create.error.value" />
      <p v-if="create.isError.value && names.length" class="text-xs text-muted">{{ t('groups.tasks.new.maybeCreated') }}</p>
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="create.isPending.value" @click="close">{{ t('common.cancel') }}</Button>
      <Button
        variant="primary"
        type="submit"
        form="new-task"
        :loading="create.isPending.value"
        :disabled="!goal.trim() || !deliverable.trim() || Boolean(problem)"
      >
        {{ t('groups.tasks.new.start') }}
      </Button>
    </template>
  </Dialog>
</template>
