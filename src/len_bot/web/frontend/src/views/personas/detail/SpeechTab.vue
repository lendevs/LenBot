<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowDown, ArrowUp, Plus, Search, Trash2 } from '@lucide/vue'
import Button from '../../../ui/Button.vue'
import Combobox from '../../../ui/Combobox.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'
import MoreSection from './MoreSection.vue'
import { useProfile } from './profileForm'

const { t } = useI18n()
const form = useProfile()
const draft = computed(() => form.draft.value!)

let nextItemId = 1
const itemIds = new WeakMap<object, number>()
function keyOf(item: object): number {
  let id = itemIds.get(item)
  if (!id) {
    id = nextItemId++
    itemIds.set(item, id)
  }
  return id
}

const percent = (weight: number) => Math.round(weight * 10000) / 100
const total = computed(() => percent(draft.value.styles.reduce((sum, style) => sum + style.weight, 0)))
const totalBalanced = computed(() => Math.abs(total.value - 100) < 0.01)

function addStyle() {
  draft.value.styles.push({ name: '', weight: draft.value.styles.length ? 0 : 1, note: null })
}

function splitEvenly() {
  const styles = draft.value.styles
  const n = styles.length
  if (!n) return
  const base = Math.floor(100 / n)
  const extra = 100 - base * n
  styles.forEach((style, index) => {
    style.weight = (base + (index < extra ? 1 : 0)) / 100
  })
}

function balanceTo100() {
  const styles = draft.value.styles
  if (!styles.length) return
  const sum = styles.reduce((acc, item) => acc + item.weight, 0)
  if (sum <= 0) {
    splitEvenly()
    return
  }
  const zeros = styles.filter((item) => item.weight <= 0)
  if (zeros.length > 0 && sum < 1) {
    const roundedNonZero = styles.map((item) => (item.weight > 0 ? Math.round(item.weight * 100) : 0))
    const used = roundedNonZero.reduce((acc, val) => acc + val, 0)
    if (used < 100) {
      const missing = 100 - used
      const base = Math.floor(missing / zeros.length)
      const extra = missing - base * zeros.length
      let zeroIdx = 0
      styles.forEach((style, index) => {
        if (style.weight > 0) {
          style.weight = roundedNonZero[index]! / 100
        } else {
          style.weight = (base + (zeroIdx < extra ? 1 : 0)) / 100
          zeroIdx += 1
        }
      })
      return
    }
  }
  const exact = styles.map((style) => (style.weight / sum) * 100)
  const floored = exact.map((val) => Math.floor(val))
  const remainder = 100 - floored.reduce((acc, val) => acc + val, 0)
  const order = exact
    .map((val, index) => ({ index, frac: val - floored[index]! }))
    .sort((a, b) => b.frac - a.frac)
  for (let i = 0; i < remainder; i++) {
    floored[order[i % order.length]!.index]! += 1
  }
  styles.forEach((style, index) => {
    style.weight = floored[index]! / 100
  })
}

// Folded unless the role already uses styles or a filter, so nothing written is hidden.
const more = ref(Boolean(draft.value.styles.length || draft.value.example_tags.length))

const tags = computed(() => [...new Set(draft.value.examples.flatMap((example) => example.tags))])
const tagOptions = computed(() => tags.value.map((tag) => ({ value: tag, label: tag })))
// A filter tag no example carries any more would hide every example from the model.
watch(tags, (value) => {
  const kept = draft.value.example_tags.filter((tag) => value.includes(tag))
  if (kept.length !== draft.value.example_tags.length) draft.value.example_tags = kept
  if (selectedTag.value && !value.includes(selectedTag.value)) selectedTag.value = null
})

const exampleSearch = ref('')
const selectedTag = ref<string | null>(null)
const showExampleFilter = computed(
  () => draft.value.examples.length > 3 || Boolean(exampleSearch.value.trim()) || selectedTag.value !== null,
)
const isExampleFiltered = computed(() => Boolean(exampleSearch.value.trim()) || selectedTag.value !== null)
const shownExamples = computed(() => {
  const words = exampleSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const tag = selectedTag.value
  return draft.value.examples
    .map((example, index) => ({ example, index }))
    .filter(({ example }) => {
      if (tag && !example.tags.includes(tag)) return false
      if (!words.length) return true
      const text = [example.context, example.line, ...example.tags].join(' ').toLowerCase()
      return words.every((word) => text.includes(word))
    })
})

function addExample() {
  exampleSearch.value = ''
  selectedTag.value = null
  draft.value.examples.push({ context: '', line: '', tags: [] })
}
function moveUp(index: number) {
  if (index <= 0) return
  const [item] = draft.value.examples.splice(index, 1)
  draft.value.examples.splice(index - 1, 0, item!)
}
function moveDown(index: number) {
  if (index >= draft.value.examples.length - 1) return
  const [item] = draft.value.examples.splice(index, 1)
  draft.value.examples.splice(index + 1, 0, item!)
}
</script>

<template>
  <form
    v-if="form.draft.value"
    class="flex max-w-3xl flex-col gap-8 pb-6"
    @submit.prevent="form.save('speech')"
  >
    <div
      v-if="form.remoteUpdated.value.speech"
      role="status"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
    >
      <span class="min-w-0 flex-1">{{ t('ui.draft.remoteUpdated') }}</span>
      <Button size="sm" variant="ghost" @click="form.discard('speech')">
        {{ t('ui.draft.reloadRemote') }}
      </Button>
    </div>

    <FormSection :title="t('personas.detail.speech.voice')" :columns="1">
      <Field>
        <Textarea v-model="draft.voice" :rows="5" :aria-label="t('personas.detail.speech.voice')" />
      </Field>
    </FormSection>

    <FormSection :title="t('personas.detail.speech.examples')" :columns="1">
      <EmptyState v-if="!draft.examples.length" :title="t('personas.detail.speech.noExamples')" compact />
      <template v-else>
        <div v-if="showExampleFilter" class="flex flex-col gap-2">
          <div class="max-w-xs">
            <Input
              v-model="exampleSearch"
              type="search"
              size="sm"
              :icon="Search"
              clearable
              :placeholder="t('personas.detail.speech.searchExamples')"
              :aria-label="t('personas.detail.speech.searchExamples')"
            />
          </div>
          <div v-if="tags.length" class="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              class="cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus-visible:focus-ring"
              :class="
                selectedTag === null
                  ? 'border-primary bg-selected text-ink'
                  : 'border-line bg-fill text-muted hover:text-ink'
              "
              :aria-pressed="selectedTag === null"
              @click="selectedTag = null"
            >
              {{ t('personas.detail.speech.allTags') }}
            </button>
            <button
              v-for="tag in tags"
              :key="tag"
              type="button"
              class="cursor-pointer rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus-visible:focus-ring"
              :class="
                selectedTag === tag
                  ? 'border-primary bg-selected text-ink'
                  : 'border-line bg-fill text-muted hover:text-ink'
              "
              :aria-pressed="selectedTag === tag"
              @click="selectedTag = selectedTag === tag ? null : tag"
            >
              {{ tag }}
            </button>
          </div>
        </div>
        <p v-if="!shownExamples.length" class="py-4 text-center text-sm text-muted">
          {{ t('common.noResults') }}
        </p>
        <ol v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
          <li
            v-for="{ example, index } in shownExamples"
            :key="keyOf(example)"
            class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 py-4"
          >
            <div class="grid min-w-0 gap-3 sm:grid-cols-2">
              <Field
                :label="t('personas.detail.speech.context')"
                :error="example.context.trim() ? null : t('common.required')"
              >
                <Textarea v-model="example.context" :rows="1" />
              </Field>
              <Field
                :label="t('personas.detail.speech.line')"
                :error="example.line.trim() ? null : t('common.required')"
              >
                <Textarea v-model="example.line" :rows="1" />
              </Field>
              <Field :label="t('personas.detail.speech.tags')" wide>
                <TagInput v-model="example.tags" />
              </Field>
            </div>
            <div class="flex flex-col gap-1 pt-5">
              <IconButton
                v-if="!isExampleFiltered && index > 0"
                :icon="ArrowUp"
                :label="t('personas.detail.speech.moveUp')"
                size="sm"
                @click="moveUp(index)"
              />
              <IconButton
                v-if="!isExampleFiltered && index < draft.examples.length - 1"
                :icon="ArrowDown"
                :label="t('personas.detail.speech.moveDown')"
                size="sm"
                @click="moveDown(index)"
              />
              <IconButton
                :icon="Trash2"
                :label="t('personas.detail.speech.removeExample')"
                size="sm"
                variant="danger-ghost"
                @click="draft.examples.splice(index, 1)"
              />
            </div>
          </li>
        </ol>
      </template>
      <div>
        <Button size="sm" variant="ghost" :icon="Plus" @click="addExample">
          {{ t('personas.detail.speech.addExample') }}
        </Button>
      </div>
    </FormSection>

    <MoreSection v-model="more" :title="t('personas.detail.more')">
      <FormSection :title="t('personas.detail.speech.styles')" :columns="1">
        <template #actions>
          <div v-if="draft.styles.length" class="flex flex-wrap items-center gap-1.5">
            <span class="text-sm tabular" :class="totalBalanced ? 'text-muted' : 'text-error'">
              {{ t('personas.detail.speech.total', { n: total }) }}
            </span>
            <Button v-if="!totalBalanced" size="sm" variant="ghost" @click="balanceTo100">
              {{ t('personas.detail.speech.balanceTotal') }}
            </Button>
            <Button v-if="draft.styles.length > 1" size="sm" variant="ghost" @click="splitEvenly">
              {{ t('personas.detail.speech.splitEvenly') }}
            </Button>
          </div>
        </template>
        <ul
          v-if="draft.styles.length"
          class="flex list-none flex-col gap-3 max-sm:gap-0 max-sm:divide-y max-sm:divide-line max-sm:border-y max-sm:border-line"
        >
          <li
            v-for="(style, index) in draft.styles"
            :key="keyOf(style)"
            class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 max-sm:py-3 sm:grid-cols-[minmax(0,1fr)_10rem_minmax(0,1.6fr)_auto]"
          >
            <div class="order-1 min-w-0">
              <Field
                :label="t('personas.detail.speech.styleName')"
                :error="style.name.trim() ? null : t('common.required')"
              >
                <Input v-model="style.name" />
              </Field>
            </div>
            <div class="order-2 flex justify-end pt-6.5 sm:order-4">
              <IconButton
                :icon="Trash2"
                :label="t('personas.detail.speech.removeStyle')"
                size="sm"
                variant="danger-ghost"
                @click="draft.styles.splice(index, 1)"
              />
            </div>
            <div class="order-3 col-span-2 min-w-0 sm:order-2 sm:col-span-1">
              <Field :label="t('personas.detail.speech.share')">
                <NumberInput
                  :model-value="percent(style.weight)"
                  :min="0"
                  :max="100"
                  :step="5"
                  unit="%"
                  @update:model-value="(value) => (style.weight = (value ?? 0) / 100)"
                />
              </Field>
            </div>
            <div class="order-4 col-span-2 min-w-0 sm:order-3 sm:col-span-1">
              <Field :label="t('personas.detail.speech.note')">
                <Input
                  :model-value="style.note ?? ''"
                  @update:model-value="(value) => (style.note = value || null)"
                />
              </Field>
            </div>
          </li>
        </ul>
        <div>
          <Button size="sm" variant="ghost" :icon="Plus" @click="addStyle">
            {{ t('personas.detail.speech.addStyle') }}
          </Button>
        </div>
      </FormSection>
      <FormSection v-if="tags.length" :columns="1">
        <Field :label="t('personas.detail.speech.filter')">
          <Combobox
            v-model="draft.example_tags"
            :options="tagOptions"
            multiple
            :placeholder="t('personas.detail.speech.filterAll')"
          />
        </Field>
      </FormSection>
    </MoreSection>

    <SaveBar
      :dirty="form.dirty.value.speech"
      :saving="form.isSaving('speech')"
      :error="form.saveError('speech') ?? form.problem('speech')"
      :raw-error="form.saveRawError('speech')"
      :invalid="Boolean(form.problem('speech'))"
      @save="form.save('speech')"
      @discard="form.discard('speech')"
    />
  </form>
</template>
