<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../../api.js'
import { useAction } from '../../../composables/useResource.js'
import { clone, numberOrBlank, same } from '../../forms.js'
import SettingSection from '../../ui/SettingSection.vue'

const props = defineProps({ snapshot: { type: Object, required: true } })
const emit = defineEmits(['saved', 'dirty', 'reload'])
const fields = ['messages_per_hour', 'direct_reserve', 'speech_notice_text']
const pick = value => Object.fromEntries(fields.map(key => [key, value[key]]))
const saved = computed(() => pick(props.snapshot.saved.limits))
const draft = ref(null)
const save = useAction()
// Shown instead of the generic save error when another tab changed the limits first (409).
const conflict = ref('')
watch(() => JSON.stringify(saved.value), () => { draft.value = clone(saved.value) }, { immediate: true })
const dirty = computed(() => !same(draft.value, saved.value))
watch(dirty, value => emit('dirty', value), { immediate: true })
const problem = computed(() => {
  if (!draft.value) return ''
  if (draft.value.messages_per_hour !== null && !(draft.value.messages_per_hour >= 1)) return '每小时条数至少 1 条'
  if (!(draft.value.direct_reserve >= 0)) return '余量不能小于 0'
  if (draft.value.speech_notice_text !== null && !draft.value.speech_notice_text.trim()) return '固定回复不能为空'
  return ''
})

async function submit() {
  // Only this section's fields, plus the version this tab read: a stale tab gets 409 instead of
  // overwriting per-group settings saved elsewhere.
  const body = { ...draft.value, version: props.snapshot.versions?.limits }
  conflict.value = ''
  const result = await save.run(async () => {
    try {
      return await api('/api/host/settings/limits', { method: 'PUT', body: JSON.stringify(body) })
    } catch (error) {
      if (error.status !== 409 || !error.details?.snapshot) throw error
      // Load the latest settings (and version) into the form so the next save works, and say why.
      emit('reload', error.details.snapshot)
      draft.value = clone(pick(error.details.snapshot.saved.limits))
      conflict.value = error.details.message || '已在其他页面或标签页修改，已重新载入最新设置，请确认后再保存。'
      return undefined
    }
  })
  if (result) emit('saved', result)
}
</script>

<template>
  <SettingSection v-if="draft" title="群聊发言上限" :restart="false"
    :dirty="dirty" :saving="save.busy.value" :error="save.error.value" :notice="conflict" :problem="problem" @save="submit">
    <v-switch :model-value="draft.messages_per_hour !== null" label="限制每个群每小时的发言条数"
      @update:model-value="value => draft.messages_per_hour = value ? 60 : null" />
    <div v-if="draft.messages_per_hour !== null" class="form-grid">
      <v-text-field :model-value="draft.messages_per_hour" type="number" label="每个群每小时最多几条"
        @update:model-value="value => draft.messages_per_hour = numberOrBlank(value)" />
      <v-text-field :model-value="draft.direct_reserve" type="number" label="用完后被 @ 时还能说几条"
        @update:model-value="value => draft.direct_reserve = numberOrBlank(value)" />
    </div>
    <template v-if="draft.messages_per_hour !== null">
      <v-switch :model-value="draft.speech_notice_text !== null" label="全部用完后被 @，回一句固定的话"
        @update:model-value="value => draft.speech_notice_text = value ? '' : null" />
      <v-text-field v-if="draft.speech_notice_text !== null" v-model="draft.speech_notice_text" label="固定回复的内容" />
    </template>
  </SettingSection>
</template>
