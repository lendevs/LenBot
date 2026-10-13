<script setup>
import { computed, ref } from 'vue'
import { mdiChevronDown, mdiPlus } from '@mdi/js'
import { sceneName } from '../../api.js'
import { initialField, rowSummary } from '../pluginConfig.js'
import SchemaField from './SchemaField.vue'

const props = defineProps({
  field: { type: Object, required: true },
  sceneChoices: { type: Array, required: true },
})
const model = defineModel({ required: true })
const opened = ref(new Set())
const title = () => props.field.label || props.field.key
const summaries = computed(() => model.value.map(row => rowSummary(props.field.fields, row, sceneName)))

function toggle(index) {
  const next = new Set(opened.value)
  if (!next.delete(index)) next.add(index)
  opened.value = next
}
function add() {
  // The model keeps its old value until the parent passes the new list back, so count from the new list itself.
  const next = [...model.value, Object.fromEntries(props.field.fields.map(child => [child.key, initialField(child)]))]
  model.value = next
  opened.value = new Set([...opened.value, next.length - 1])
}
function remove(index) {
  model.value = model.value.filter((_, i) => i !== index)
  opened.value = new Set([...opened.value].filter(i => i !== index).map(i => i > index ? i - 1 : i))
}
</script>

<template>
  <div class="schema-rows">
    <div v-for="(row, index) in model" :key="index" class="row" :class="{ open: opened.has(index) }">
      <button type="button" class="row-head" :aria-expanded="opened.has(index)" @click="toggle(index)">
        <span class="row-text">
          <strong>{{ summaries[index].title || `第 ${index + 1} 项` }}</strong>
          <span v-if="summaries[index].meta" class="muted small">{{ summaries[index].meta }}</span>
        </span>
        <span class="row-badges"><span v-for="badge in summaries[index].badges" :key="badge" class="badge">{{ badge }}</span></span>
        <v-icon :icon="mdiChevronDown" size="20" class="chevron" />
      </button>
      <div v-if="opened.has(index)" class="row-body">
        <div class="schema-grid">
          <SchemaField v-for="child in field.fields" :key="child.key" v-model="row[child.key]" :field="child" :scene-choices="sceneChoices" />
        </div>
        <v-btn size="small" variant="text" color="error" class="row-remove" @click="remove(index)">删除这一项</v-btn>
      </div>
    </div>
    <p v-if="!model.length" class="muted small empty">还没有添加</p>
    <v-btn variant="text" color="primary" size="small" :prepend-icon="mdiPlus" class="row-add" @click="add">添加{{ title() }}</v-btn>
  </div>
</template>

<style scoped>
.schema-rows{display:grid;gap:var(--sp-2);min-width:0}
.row{border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);transition:border-color var(--dur-2),box-shadow var(--dur-2)}
.row:hover{border-color:var(--line-strong)}
.row.open{border-color:var(--line-strong);box-shadow:var(--shadow-card)}
.row-head{display:flex;align-items:center;gap:var(--sp-3);width:100%;min-height:52px;padding:var(--sp-2) var(--sp-3) var(--sp-2) var(--sp-4);border:0;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer;border-radius:var(--radius)}
.row-text{display:grid;flex:1;min-width:0;line-height:1.4}
.row-text strong,.row-text span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row-text strong{font-weight:600}
.row-badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;max-width:50%}
.badge{padding:1px 8px;border-radius:999px;background:var(--fill);color:var(--muted);font-size:var(--fs-xs);line-height:20px;white-space:nowrap}
.chevron{flex:none;color:var(--muted);transition:transform var(--dur-2) var(--ease-out)}
.open .chevron{transform:rotate(180deg)}
.schema-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--sp-4) var(--sp-3);align-items:end}
.row-body{display:grid;gap:var(--sp-3);padding:var(--sp-4) var(--sp-4) var(--sp-3);border-top:1px solid var(--line)}
.row-remove{justify-self:end}
.row-add{justify-self:start}
.empty{margin:0}
@media(max-width:700px){.row-badges{display:none}.schema-grid{grid-template-columns:minmax(0,1fr)}}
</style>
