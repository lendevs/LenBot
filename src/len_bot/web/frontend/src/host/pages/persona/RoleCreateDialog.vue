<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../../api.js'
import { useAction } from '../../../composables/useResource.js'
import { notify } from '../../store.js'
import ErrorNote from '../../ui/ErrorNote.vue'
import FormDialog from '../../ui/FormDialog.vue'
import { folderProblem, roleBase, roleLabel } from './roles.js'

// kind: create a blank role, copy `source`, or import a ZIP; all three make a new folder.
const props = defineProps({ request: { type: Object, default: null } })
const emit = defineEmits(['close', 'done'])
const name = ref(''), folder = ref(''), zip = ref(null)
const action = useAction()
watch(() => props.request, request => {
  if (!request) return
  const source = request.source
  name.value = source ? `${roleLabel(source)} 副本` : ''
  folder.value = source ? `${source.key}-copy`.toLowerCase().replace(/[^a-z0-9-]/g, '').replace(/^-+/, '') : ''
  zip.value = null
  action.error.value = null
}, { immediate: true })
const kind = computed(() => props.request?.kind)
const titles = { create: '新建角色', copy: '复制角色', import: '导入角色 ZIP' }
const problem = computed(() => !folder.value ? '起一个文件夹名' : folderProblem(folder.value)
  || (kind.value !== 'import' && !name.value.trim() ? '写上名字' : '')
  || (kind.value === 'import' && !zip.value ? '选一个 ZIP 文件' : ''))

async function submit() {
  const result = await action.run(() => {
    if (kind.value === 'import') {
      const form = new FormData()
      form.append('name', folder.value)
      form.append('file', zip.value)
      return api('/api/host/personas/import', { method: 'POST', body: form })
    }
    return api(kind.value === 'copy' ? `${roleBase(props.request.source.key)}/copy` : '/api/host/personas', { method: 'POST',
      body: JSON.stringify({ folder: folder.value, name: name.value.trim() }) })
  })
  if (!result) return
  notify(result.renamed_id ? `已导入，ID 和已有角色重复，改成了 ${result.renamed_id.to}`
    : { copy: '已复制', import: '已导入', create: '已新建' }[kind.value])
  emit('done', folder.value)
}
</script>

<template>
  <FormDialog :model-value="request !== null" :title="request ? titles[request.kind] : ''" :busy="action.busy.value"
    @update:model-value="value => { if (!value) emit('close') }">
    <template v-if="request">
      <v-text-field v-if="kind !== 'import'" v-model="name" label="名字" autofocus />
      <v-text-field v-model="folder" label="文件夹名" placeholder="jiaran" :error-messages="folderProblem(folder)" />
      <v-file-input v-if="kind === 'import'" v-model="zip" label="角色 ZIP" accept=".zip,application/zip" prepend-icon="" />
      <ErrorNote v-if="action.error.value" title="没有完成" :error="action.error.value" />
    </template>
    <template #actions>
      <v-tooltip :text="problem" :disabled="!problem" location="top">
        <template #activator="{ props: tip }">
          <span v-bind="tip"><v-btn color="primary" :loading="action.busy.value" :disabled="Boolean(problem)" @click="submit">
            {{ { import: '导入', copy: '复制', create: '新建' }[kind] }}</v-btn></span>
        </template>
      </v-tooltip>
    </template>
  </FormDialog>
</template>
