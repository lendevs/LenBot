<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { pluginsApi } from '../../api/plugins'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import Textarea from '../../ui/Textarea.vue'
import { usePluginsState } from './state'

const props = defineProps<{ paths: string[]; dataDirectory: string }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const paths = ref(props.paths.join('\n'))
const data = ref(props.dataDirectory)
const error = ref<unknown>(null)
const list = computed(() => paths.value.split('\n').map((item) => item.trim()).filter(Boolean))
const dirty = computed(() => list.value.join('\n') !== props.paths.join('\n') || data.value.trim() !== props.dataDirectory)
const saving = computed(() => state.busy.value === 'paths')
const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})
async function submit() {
  if (!dirty.value || !data.value.trim()) return
  error.value = null
  try {
    await state.run('paths', () => pluginsApi.putPaths(list.value, data.value.trim()), { quiet: true, success: t('common.saved') })
    emit('close')
  } catch (problem) {
    error.value = problem
  }
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('plugins.paths.title')" size="sm" :busy="saving">
    <form id="plugin-paths" class="flex flex-col gap-4" @submit.prevent="submit">
      <Field :label="t('plugins.paths.paths')">
        <Textarea v-model="paths" :rows="3" mono placeholder="plugins" />
      </Field>
      <Field :label="t('plugins.paths.data')" required>
        <Input v-model="data" mono />
      </Field>
      <ErrorNote v-if="error" :title="t('plugins.paths.failed')" :error="error" />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</Button>
      <Button variant="primary" type="submit" form="plugin-paths" :loading="saving" :disabled="!dirty || !data.trim()">
        {{ t('common.save') }}
      </Button>
    </template>
  </Dialog>
</template>
