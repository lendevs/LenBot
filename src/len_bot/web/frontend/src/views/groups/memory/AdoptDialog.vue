<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { memoryApi } from '../../../api/memory'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Textarea from '../../../ui/Textarea.vue'

/** Turn material imported from the old version into a real memory file the Bot reads. */
const props = defineProps<{ scene: string; source: string; original: string }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ adopted: [result: { target: string; source_removed: boolean }] }>()

const { t } = useI18n()
const target = ref('')
const content = ref('')
const reason = ref('')
const removeSource = ref(true)
watch(open, (value) => {
  if (!value) return
  target.value = ''
  content.value = ''
  reason.value = t('groups.memory.adopt.reason')
  removeSource.value = true
})
const valid = computed(() => target.value.trim().endsWith('.md') && content.value.trim() && reason.value.trim())
const adopt = useMutation({
  mutationFn: () =>
    memoryApi.adoptPending({
      scene: props.scene,
      source: props.source,
      original: props.original,
      target: target.value.trim(),
      content: content.value,
      reason: reason.value.trim(),
      remove_source: removeSource.value,
    }),
  onSuccess: (result) => emit('adopted', result),
})
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.memory.adopt.action')" size="lg" :busy="adopt.isPending.value">
    <div class="flex flex-col gap-4">
      <CodeBlock :code="original" :max-lines="8" :label="t('groups.memory.adopt.original')" />
      <Field :label="t('groups.memory.adopt.target')">
        <Input v-model="target" placeholder="people/name.md" mono />
      </Field>
      <Field :label="t('groups.memory.adopt.content')">
        <Textarea v-model="content" :rows="8" />
      </Field>
      <Field :label="t('groups.memory.file.reason')">
        <Input v-model="reason" />
      </Field>
      <label class="flex cursor-pointer items-center gap-2.5 text-sm text-ink">
        <Checkbox v-model="removeSource" />{{ t('groups.memory.adopt.removeSource') }}
      </label>
      <ErrorNote v-if="adopt.isError.value" :title="t('groups.memory.adopt.failed')" :error="adopt.error.value" />
    </div>
    <template #footer>
      <Button variant="ghost" :disabled="adopt.isPending.value" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="primary" :loading="adopt.isPending.value" :disabled="!valid" @click="adopt.mutate()">
        {{ t('common.save') }}
      </Button>
    </template>
  </Dialog>
</template>
