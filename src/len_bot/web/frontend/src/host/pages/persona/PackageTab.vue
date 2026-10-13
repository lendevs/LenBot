<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../../api.js'
import { useAction, useResource } from '../../../composables/useResource.js'
import { notify } from '../../store.js'
import { confirm } from '../../../composables/useConfirm.js'
import Panel from '../../ui/Panel.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import ResourceState from '../../ui/ResourceState.vue'
import DevOnly from '../../ui/DevOnly.vue'
import { roleBase, savedNotice } from './roles.js'

const props = defineProps({ persona: { type: String, required: true } })
const emit = defineEmits(['dirty', 'saved'])

const files = [['persona.yaml', '设定 persona.yaml'], ['voice.md', '说话方式 voice.md'], ['boundaries.md', '底线 boundaries.md'], ['examples.yaml', '样例 examples.yaml']]
const raw = useResource(() => api(`${roleBase(props.persona)}/files`))
const file = ref('persona.yaml'), text = ref('')
watch(raw.data, value => { if (value) text.value = value.saved[file.value] })
const dirty = computed(() => Boolean(raw.data.value && text.value !== raw.data.value.saved[file.value]))
watch(dirty, value => emit('dirty', value), { immediate: true })
async function pick(next) {
  if (dirty.value && !await confirm({ title: '这个文件还没保存，放弃修改？', confirmLabel: '放弃', danger: true })) return
  file.value = next
  text.value = raw.data.value.saved[next]
}
const save = useAction()
async function saveRaw() {
  const result = await save.run(() => api(`${roleBase(props.persona)}/files/${file.value}`, {
    method: 'PUT', body: JSON.stringify({ content: text.value, directory: raw.data.value.saved_path }) }))
  if (!result) return
  raw.data.value = result
  notify(savedNotice(result))
  emit('saved')
}
</script>

<template>
  <ResourceState :resource="raw" error-title="读取角色文件失败">
    <Panel tag="form" title="角色文件" @submit.prevent="saveRaw">
      <v-btn-toggle :model-value="file" mandatory density="comfortable" class="file-switch" @update:model-value="pick">
        <v-btn v-for="[value, title] in files" :key="value" :value="value">{{ title.split(' ')[0] }}</v-btn>
      </v-btn-toggle>
      <v-textarea v-model="text" rows="18" auto-grow spellcheck="false" class="mono" :label="file" />
      <ErrorNote v-if="save.error.value" title="没有保存成功" :error="save.error.value" />
      <DevOnly label="文件位置"><code>{{ raw.data.value.saved_path }}</code></DevOnly>
      <template #footer><v-spacer /><v-btn type="submit" color="primary" :loading="save.busy.value" :disabled="!dirty">保存这个文件</v-btn></template>
    </Panel>
  </ResourceState>
</template>

<style scoped>
.file-switch{flex-wrap:wrap;height:auto;margin-bottom:var(--sp-3)}
</style>
