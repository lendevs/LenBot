<script setup>
import { computed, ref, useId } from 'vue'
import { mdiEyeOffOutline, mdiEyeOutline } from '@mdi/js'
import { wideField } from '../pluginConfig.js'
import FieldInfo from '../ui/FieldInfo.vue'
import ScenePicker from './ScenePicker.vue'

const props = defineProps({
  field: { type: Object, required: true },
  sceneChoices: { type: Array, required: true },
  configured: Boolean,
})
const model = defineModel({ required: true })
const id = useId(), reveal = ref(false)
const title = computed(() => props.field.label || props.field.key)
const secretKept = computed(() => props.field.type === 'secret' && props.configured)
// A handful of short choices reads better as a segmented control than as a dropdown.
const segmented = computed(() => props.field.options?.length <= 3 && props.field.options.every(option => String(option.label).length <= 8))
const inputType = computed(() => props.field.type === 'secret' ? (reveal.value ? 'text' : 'password')
  : ['integer', 'number'].includes(props.field.type) ? 'number' : props.field.type === 'url' ? 'url' : 'text')
const range = computed(() => {
  const { minimum: low, maximum: high } = props.field
  if (low !== null && high !== null) return `${low}–${high}`
  // A lone lower bound of 0 or 1 only says the number is not negative, which goes without saying.
  if (low !== null) return low > 1 ? `≥ ${low}` : undefined
  return high !== null ? `≤ ${high}` : undefined
})
const placeholder = computed(() => secretKept.value ? '已保存，留空不修改' : props.field.placeholder ?? undefined)
</script>

<template>
  <div class="schema-field" :class="{ wide: wideField(field) }">
    <div v-if="field.type === 'boolean'" class="toggle-row">
      <label :for="id" class="toggle-label">{{ title }}</label>
      <FieldInfo v-if="field.description" :text="field.description" :size="15" />
      <v-switch :id="id" v-model="model" class="toggle-switch" />
    </div>
    <template v-else>
      <div class="field-label">
        <label :for="id">{{ title }}</label>
        <span v-if="field.required" class="required" aria-hidden="true">*</span>
        <FieldInfo v-if="field.description" :text="field.description" :size="15" />
        <span v-if="secretKept" class="saved-tag">已保存</span>
      </div>
      <v-btn-toggle v-if="field.options && segmented" v-model="model" mandatory class="segments" :aria-label="title">
        <v-btn v-for="option in field.options" :key="String(option.value)" :value="option.value">{{ option.label }}</v-btn>
      </v-btn-toggle>
      <v-select v-else-if="field.options" :id="id" v-model="model" :items="field.options" item-title="label" item-value="value" density="compact" />
      <ScenePicker v-else-if="field.type === 'scene'" :id="id" v-model="model" :choices="sceneChoices" single />
      <ScenePicker v-else-if="field.type === 'scene_list'" :id="id" v-model="model" :choices="sceneChoices" />
      <v-combobox v-else-if="field.type === 'string_list'" :id="id" v-model="model" multiple chips closable-chips hide-no-data
        :delimiters="['\n']" density="compact" placeholder="输入后回车添加" class="list-input" />
      <v-textarea v-else-if="field.type === 'string' && field.multiline" :id="id" v-model="model" rows="3" auto-grow density="compact"
        :placeholder="placeholder" />
      <v-textarea v-else-if="field.type === 'object_list'" :id="id" v-model="model" rows="5" auto-grow density="compact" class="mono"
        placeholder="JSON 对象列表" />
      <v-text-field v-else :id="id" v-model="model" :type="inputType" :placeholder="placeholder" density="compact"
        :class="{ mono: field.type === 'path' }" :suffix="range"
        :min="field.minimum ?? undefined" :max="field.maximum ?? undefined" :step="field.type === 'integer' ? 1 : 'any'"
        :autocomplete="field.type === 'secret' ? 'off' : undefined">
        <template v-if="field.type === 'secret'" #append-inner>
          <v-btn :icon="reveal ? mdiEyeOffOutline : mdiEyeOutline" variant="text" size="x-small" :aria-label="reveal ? '隐藏' : '显示'" @click="reveal = !reveal" />
        </template>
      </v-text-field>
    </template>
  </div>
</template>

<style scoped>
.schema-field{display:grid;gap:6px;min-width:0;align-content:end}
.schema-field.wide{grid-column:1 / -1}
.field-label{display:flex;align-items:center;gap:4px;min-height:20px;font-size:var(--fs-sm);font-weight:600;line-height:1.4}
.field-label label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.required{color:var(--error);font-weight:600}
.saved-tag{margin-left:auto;padding:0 6px;border-radius:4px;background:var(--success-bg);color:var(--success);font-size:var(--fs-xs);font-weight:600;line-height:18px}
.toggle-row{display:flex;align-items:center;gap:4px;min-height:40px;padding:0 var(--sp-2) 0 var(--sp-3);border-radius:var(--radius);background:var(--fill)}
.toggle-label{font-size:var(--fs-md);cursor:pointer;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toggle-switch{flex:none;margin-left:auto}
.toggle-switch :deep(.v-selection-control){min-height:36px}
.segments.v-btn-toggle{justify-self:start;height:40px;padding:3px}
.segments.v-btn-toggle :deep(.v-btn){height:34px !important;min-width:72px;padding:0 var(--sp-4)}
.list-input :deep(.v-field__input){padding-top:6px;padding-bottom:6px;gap:4px}
.list-input :deep(.v-chip){margin:0;background:var(--surface);border:1px solid var(--line-strong);color:var(--ink)}
.list-input :deep(.v-chip .v-chip__underlay){opacity:0}
.list-input :deep(.v-chip__close){opacity:.45;font-size:14px}
.list-input :deep(.v-chip__close:hover){opacity:.8}
.schema-field :deep(.v-text-field__suffix){color:var(--muted);font-size:var(--fs-sm);opacity:1}
</style>
