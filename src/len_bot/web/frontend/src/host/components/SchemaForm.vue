<script setup>
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import FieldInfo from '../ui/FieldInfo.vue'
import SchemaField from './SchemaField.vue'
import SchemaRows from './SchemaRows.vue'

const props = defineProps({
  fields: { type: Array, required: true },
  sceneChoices: { type: Array, required: true },
  configured: { type: Object, default: () => ({}) },
})
const values = defineModel({ type: Object, required: true })
const prefix = useId()
const rows = field => field.type === 'object_list' && field.fields.length > 0

// Each group is one card. A top-level object list gets a card of its own because its rows carry their own fields.
// Ungrouped cards come first, the rest keep the order they were declared in.
const sections = computed(() => {
  const ungrouped = [], groups = new Map()
  let loose = null
  for (const field of props.fields) {
    if (!field.group && rows(field)) {
      ungrouped.push({ title: field.label || field.key, description: field.description, list: field, fields: [] })
    } else if (!field.group) {
      if (!loose) ungrouped.push(loose = { title: '', fields: [] })
      loose.fields.push(field)
    } else {
      if (!groups.has(field.group)) groups.set(field.group, { title: field.group, fields: [] })
      groups.get(field.group).fields.push(field)
    }
  }
  return [...ungrouped, ...groups.values()].map((section, index) => ({ ...section, id: `${prefix}-${index}` }))
})
const undeclared = computed(() => props.fields.filter(field => field.type === 'object_list' && !field.fields.length))

// The side index only pays off on long forms.
const indexed = computed(() => sections.value.length >= 4)
const current = ref('')
let observer = null
function observe() {
  observer?.disconnect()
  if (!indexed.value) return
  observer = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
    if (visible.length) current.value = visible[0].target.id
  }, { rootMargin: '-80px 0px -55% 0px' })
  for (const section of sections.value) {
    const element = document.getElementById(section.id)
    if (element) observer.observe(element)
  }
}
watch(sections, () => nextTick(observe), { immediate: true, flush: 'post' })
onBeforeUnmount(() => observer?.disconnect())
function jump(id) {
  current.value = id
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const sectionName = section => section.title || '常规'
</script>

<template>
  <div class="schema-form" :class="{ indexed }">
    <nav v-if="indexed" class="schema-index" aria-label="参数分组">
      <button v-for="section in sections" :key="section.id" type="button" :class="{ active: current === section.id }" @click="jump(section.id)">
        {{ sectionName(section) }}</button>
    </nav>
    <div class="schema-sections">
      <section v-for="section in sections" :id="section.id" :key="section.id" class="schema-card">
        <header v-if="section.title" class="card-head">
          <h3>{{ section.title }}</h3>
          <FieldInfo v-if="section.description" :text="section.description" :size="15" />
          <span v-if="section.list" class="count">{{ values[section.list.key].length }}</span>
        </header>
        <SchemaRows v-if="section.list" v-model="values[section.list.key]" :field="section.list" :scene-choices="sceneChoices" />
        <div v-else class="schema-grid">
          <template v-for="field in section.fields" :key="field.key">
            <div v-if="rows(field)" class="nested">
              <div class="nested-head"><h4>{{ field.label || field.key }}</h4><FieldInfo v-if="field.description" :text="field.description" :size="15" /></div>
              <SchemaRows v-model="values[field.key]" :field="field" :scene-choices="sceneChoices" />
            </div>
            <SchemaField v-else v-model="values[field.key]" :field="field" :scene-choices="sceneChoices" :configured="Boolean(configured[field.key])" />
          </template>
        </div>
      </section>
      <p v-if="undeclared.length" class="muted small">
        {{ undeclared.map(field => field.label || field.key).join('、') }} 没有声明子字段，只能按 JSON 填写；插件作者可以在 plugin.toml 里补上 fields。
      </p>
    </div>
  </div>
</template>

<style scoped>
.schema-form{display:grid;gap:var(--sp-5);min-width:0;align-items:start}
.schema-sections{display:grid;gap:var(--sp-4);min-width:0}
.schema-card{display:grid;gap:var(--sp-4);padding:var(--sp-5);border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);scroll-margin-top:88px;min-width:0}
.card-head{display:flex;align-items:center;gap:6px}
.card-head h3{font-size:var(--fs-lg);font-weight:650}
.count{padding:0 7px;border-radius:999px;background:var(--fill);color:var(--muted);font-size:var(--fs-xs);font-weight:600;line-height:20px}
.schema-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--sp-4) var(--sp-3);align-items:end}
.nested{grid-column:1 / -1;display:grid;gap:var(--sp-2)}
.nested-head{display:flex;align-items:center;gap:4px}
.nested-head h4{font-size:var(--fs-sm);font-weight:600}
.schema-index{display:none}
@media(min-width:1280px){
  .schema-form.indexed{grid-template-columns:168px minmax(0,1fr)}
  .schema-index{position:sticky;top:88px;display:grid;gap:2px}
  .schema-index button{height:32px;padding:0 var(--sp-3);border:0;border-left:2px solid var(--line);background:none;color:var(--muted);font:inherit;font-size:var(--fs-sm);text-align:left;cursor:pointer;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:color var(--dur-1),border-color var(--dur-2)}
  .schema-index button:hover{color:var(--ink)}
  .schema-index button.active{color:var(--ink);font-weight:600;border-left-color:var(--brand)}
}
@media(max-width:700px){
  .schema-card{padding:var(--sp-4)}
  .schema-grid{grid-template-columns:minmax(0,1fr)}
}
</style>
