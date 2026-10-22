<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Info } from '@lucide/vue'
import type { ConfigField } from '../../../api/plugins'
import Badge from '../../../ui/Badge.vue'
import Tooltip from '../../../ui/Tooltip.vue'
import SchemaField from './SchemaField.vue'
import SchemaRows from './SchemaRows.vue'
import { fieldLabel, hasRows, type Draft, type DraftValue, type Row } from './config'

/**
 * A plugin's parameters laid out as developer/plugins-v1.md describes: one card per `group`, ungrouped fields
 * first in a card without a title, a top-level object list in a card of its own, an index beside four or more.
 */
const values = defineModel<Draft>({ required: true })
const props = defineProps<{
  fields: ConfigField[]
  sceneChoices: string[]
  /** Secrets that already have a saved value. */
  configured: Record<string, boolean>
  problems: Record<string, string>
}>()

const { t } = useI18n()
const prefix = useId()

interface Section {
  id: string
  title: string
  description?: string
  list?: ConfigField
  fields: ConfigField[]
}
const sections = computed<Section[]>(() => {
  const ungrouped: Omit<Section, 'id'>[] = []
  const groups = new Map<string, Omit<Section, 'id'>>()
  let loose: Omit<Section, 'id'> | null = null
  for (const field of props.fields) {
    if (!field.group && hasRows(field)) {
      ungrouped.push({ title: fieldLabel(field), description: field.description, list: field, fields: [] })
    } else if (!field.group) {
      if (!loose) ungrouped.push((loose = { title: '', fields: [] }))
      loose.fields.push(field)
    } else {
      if (!groups.has(field.group)) groups.set(field.group, { title: field.group, fields: [] })
      groups.get(field.group)!.fields.push(field)
    }
  }
  return [...ungrouped, ...groups.values()].map((section, index) => ({
    ...section,
    id: `${prefix}-${index}`,
  }))
})
const undeclared = computed(() =>
  props.fields.filter((field) => field.type === 'object_list' && !field.fields.length),
)
const set = (key: string, value: DraftValue) => (values.value = { ...values.value, [key]: value })
const rows = (key: string) => values.value[key] as Row[]

// The index only pays off on long forms.
const indexed = computed(() => sections.value.length >= 4)
const current = ref('')
let observer: IntersectionObserver | null = null
function observe() {
  observer?.disconnect()
  if (!indexed.value) return
  observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (visible.length) current.value = visible[0].target.id
    },
    { rootMargin: '-80px 0px -55% 0px' },
  )
  for (const section of sections.value) {
    const element = document.getElementById(section.id)
    if (element) observer.observe(element)
  }
}
watch(sections, () => nextTick(observe), { immediate: true, flush: 'post' })
onBeforeUnmount(() => observer?.disconnect())
function jump(id: string) {
  current.value = id
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <div class="grid min-w-0 items-start gap-5" :class="indexed && 'xl:grid-cols-[168px_minmax(0,1fr)]'">
    <nav v-if="indexed" class="sticky top-20 hidden flex-col xl:flex" :aria-label="t('plugins.form.index')">
      <button
        v-for="section in sections"
        :key="section.id"
        type="button"
        class="h-8 cursor-pointer truncate border-l-2 px-3 text-left text-sm transition-colors"
        :class="
          current === section.id
            ? 'border-brand font-medium text-ink'
            : 'border-line text-muted hover:text-ink'
        "
        @click="jump(section.id)"
      >
        {{ section.title || t('plugins.form.general') }}
      </button>
    </nav>
    <div class="flex min-w-0 flex-col gap-4">
      <section
        v-for="section in sections"
        :id="section.id"
        :key="section.id"
        class="flex min-w-0 scroll-mt-20 flex-col gap-4 rounded-xl border border-line bg-surface p-5 max-sm:p-4"
      >
        <header v-if="section.title" class="flex items-center gap-1.5">
          <h3 class="text-base font-semibold text-ink">{{ section.title }}</h3>
          <Tooltip v-if="section.description" :text="section.description">
            <button
              type="button"
              class="inline-flex cursor-help rounded-sm text-subtle hover:text-ink-2 focus-visible:focus-ring"
              :aria-label="section.description"
            >
              <Info :size="14" aria-hidden="true" />
            </button>
          </Tooltip>
          <Badge v-if="section.list">{{ rows(section.list.key).length }}</Badge>
        </header>
        <SchemaRows
          v-if="section.list"
          :model-value="rows(section.list.key)"
          :field="section.list"
          :scene-choices="sceneChoices"
          :problems="problems"
          @update:model-value="(value) => set(section.list!.key, value)"
        />
        <div v-else class="grid items-end gap-x-5 gap-y-5 sm:grid-cols-2">
          <template v-for="field in section.fields" :key="field.key">
            <div v-if="hasRows(field)" class="flex min-w-0 flex-col gap-2 sm:col-span-2">
              <div class="flex items-center gap-1.5">
                <h4 class="text-sm font-medium text-ink-2">{{ fieldLabel(field) }}</h4>
                <Tooltip v-if="field.description" :text="field.description">
                  <button
                    type="button"
                    class="inline-flex cursor-help rounded-sm text-subtle hover:text-ink-2 focus-visible:focus-ring"
                    :aria-label="field.description"
                  >
                    <Info :size="14" aria-hidden="true" />
                  </button>
                </Tooltip>
              </div>
              <SchemaRows
                :model-value="rows(field.key)"
                :field="field"
                :scene-choices="sceneChoices"
                :problems="problems"
                @update:model-value="(value) => set(field.key, value)"
              />
            </div>
            <SchemaField
              v-else
              :model-value="values[field.key]"
              :field="field"
              :scene-choices="sceneChoices"
              :configured="Boolean(configured[field.key])"
              :error="problems[field.key]"
              @update:model-value="(value) => set(field.key, value)"
            />
          </template>
        </div>
      </section>
      <p v-if="undeclared.length" class="text-xs text-muted">
        {{
          t('plugins.form.undeclared', { names: undeclared.map(fieldLabel).join(t('personas.separator')) })
        }}
      </p>
    </div>
  </div>
</template>
