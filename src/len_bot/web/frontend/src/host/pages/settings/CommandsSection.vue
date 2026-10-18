<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../../api.js'
import { useAction } from '../../../composables/useResource.js'
import { confirm } from '../../../composables/useConfirm.js'
import SettingSection from '../../ui/SettingSection.vue'

const props = defineProps({ snapshot: { type: Object, required: true } })
const emit = defineEmits(['saved', 'dirty'])
const saved = computed(() => props.snapshot.saved.commands)
const draft = ref(false)
const save = useAction()
watch(() => saved.value?.group_managers_chat_reset, value => { draft.value = Boolean(value) }, { immediate: true })
const dirty = computed(() => saved.value != null && draft.value !== Boolean(saved.value.group_managers_chat_reset))
watch(dirty, value => emit('dirty', value), { immediate: true })

async function submit() {
  if (draft.value && !await confirm({ title: '让群管理员也能用？', confirmLabel: '保存', danger: true,
    text: '重启后，每个群的群主和群管理员都能用 /chat off 让 Bot 在本群停下，也能用 /reset 清空本群的上下文，不会自动恢复。' })) return
  const result = await save.run(() => api('/api/host/settings/commands', {
    method: 'PUT', body: JSON.stringify({ group_managers_chat_reset: draft.value }) }))
  if (result) emit('saved', result)
}
</script>

<template>
  <SettingSection v-if="saved" title="群内命令"
    :dirty="dirty" :saving="save.busy.value" :error="save.error.value" @save="submit">
    <v-switch v-model="draft" label="群主和群管理员也能用 /chat on|off 和 /reset" />
    <p class="muted small">关闭时（默认）只有主人和全局管理员能用。</p>
  </SettingSection>
</template>

<style scoped>
p{margin:0}
</style>
