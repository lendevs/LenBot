<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, Plus, Trash2 } from '@lucide/vue'
import type { ConfigField } from '../../../api/plugins'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import SchemaField from './SchemaField.vue'
import { fieldLabel, initialField, rowSummary, type DraftValue, type Row } from './config'

/** An object list edited row by row: each row folds to a one-line summary and opens to its sub-fields. */
const model = defineModel<Row[]>({ required: true })
const props = defineProps<{ field: ConfigField; sceneChoices: string[]; problems: Record<string, string> }>()

const { t } = useI18n()
const opened = ref(new Set<number>())
const summaries = computed(() => model.value.map((row) => rowSummary(props.field.fields, row, groupLabel, t)))
const problemsIn = (index: number) =>
  props.field.fields.some((child) => props.problems[`${props.field.key}.${index}.${child.key}`])

function toggle(index: number) {
  const next = new Set(opened.value)
  if (!next.delete(index)) next.add(index)
  opened.value = next
}
function set(index: number, key: string, value: DraftValue) {
  model.value = model.value.map((row, at) => (at === index ? { ...row, [key]: value } : row))
}
function add() {
  const next = [
    ...model.value,
    Object.fromEntries(props.field.fields.map((child) => [child.key, initialField(child)])),
  ]
  model.value = next
  opened.value = new Set([...opened.value, next.length - 1])
}
function remove(index: number) {
  model.value = model.value.filter((_, at) => at !== index)
  opened.value = new Set(
    [...opened.value].filter((at) => at !== index).map((at) => (at > index ? at - 1 : at)),
  )
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-2">
    <ul v-if="model.length" class="flex list-none flex-col gap-2">
      <li
        v-for="(row, index) in model"
        :key="index"
        class="rounded-md border bg-surface transition-[border-color,box-shadow] duration-150"
        :class="[
          opened.has(index) ? 'border-line-strong shadow-card' : 'border-line hover:border-line-strong',
          problemsIn(index) && !opened.has(index) && 'border-error',
        ]"
      >
        <button
          type="button"
          class="flex min-h-13 w-full cursor-pointer items-center gap-3 rounded-md py-2 pr-3 pl-4 text-left focus-visible:focus-ring"
          :aria-expanded="opened.has(index)"
          @click="toggle(index)"
        >
          <span class="flex min-w-0 flex-1 flex-col">
            <strong class="truncate text-sm font-medium text-ink">
              {{ summaries[index].title || t('plugins.form.row', { n: index + 1 }) }}
            </strong>
            <span v-if="summaries[index].meta" class="truncate text-xs text-muted">
              {{ summaries[index].meta }}
            </span>
          </span>
          <span class="flex max-w-1/2 flex-wrap justify-end gap-1.5 max-sm:hidden">
            <Badge v-for="badge in summaries[index].badges" :key="badge">{{ badge }}</Badge>
          </span>
          <ChevronDown
            :size="18"
            class="shrink-0 text-subtle transition-transform"
            :class="opened.has(index) && 'rotate-180'"
            aria-hidden="true"
          />
        </button>
        <div v-if="opened.has(index)" class="flex flex-col gap-4 border-t border-line p-4">
          <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
            <SchemaField
              v-for="child in field.fields"
              :key="child.key"
              :model-value="row[child.key]"
              :field="child"
              :scene-choices="sceneChoices"
              :error="problems[`${field.key}.${index}.${child.key}`]"
              @update:model-value="(value) => set(index, child.key, value)"
            />
          </div>
          <div class="flex justify-end">
            <Button size="sm" variant="danger-ghost" :icon="Trash2" @click="remove(index)">
              {{ t('plugins.form.removeRow') }}
            </Button>
          </div>
        </div>
      </li>
    </ul>
    <p v-else class="text-sm text-muted">{{ t('plugins.form.noRows') }}</p>
    <div>
      <Button size="sm" variant="ghost" :icon="Plus" class="-ml-2" @click="add">
        {{ t('plugins.form.addRow', { name: fieldLabel(field) }) }}
      </Button>
    </div>
  </div>
</template>
