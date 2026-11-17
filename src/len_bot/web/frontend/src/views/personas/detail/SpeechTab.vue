<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUp, Plus, X } from '@lucide/vue'
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

const percent = (weight: number) => Math.round(weight * 10000) / 100
const total = computed(() => percent(draft.value.styles.reduce((sum, style) => sum + style.weight, 0)))
function addStyle() {
  draft.value.styles.push({ name: '', weight: draft.value.styles.length ? 0 : 1, note: null })
}

// Folded unless the role already uses styles or a filter, so nothing written is hidden.
const more = ref(Boolean(draft.value.styles.length || draft.value.example_tags.length))

const tags = computed(() => [...new Set(draft.value.examples.flatMap((example) => example.tags))])
const tagOptions = computed(() => tags.value.map((tag) => ({ value: tag, label: tag })))
// A filter tag no example carries any more would hide every example from the model.
watch(tags, (value) => {
  const kept = draft.value.example_tags.filter((tag) => value.includes(tag))
  if (kept.length !== draft.value.example_tags.length) draft.value.example_tags = kept
})
function addExample() {
  draft.value.examples.push({ context: '', line: '', tags: [] })
}
function moveUp(index: number) {
  const [item] = draft.value.examples.splice(index, 1)
  draft.value.examples.splice(index - 1, 0, item!)
}
</script>

<template>
  <form
    v-if="form.draft.value"
    class="flex max-w-3xl flex-col gap-8 pb-6"
    @submit.prevent="form.save('speech')"
  >
    <FormSection :title="t('personas.detail.speech.voice')" :columns="1">
      <Field>
        <Textarea v-model="draft.voice" :rows="5" :aria-label="t('personas.detail.speech.voice')" />
      </Field>
    </FormSection>

    <FormSection :title="t('personas.detail.speech.examples')" :columns="1">
      <EmptyState v-if="!draft.examples.length" :title="t('personas.detail.speech.noExamples')" compact />
      <ol v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li
          v-for="(example, index) in draft.examples"
          :key="index"
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
              v-if="index"
              :icon="ArrowUp"
              :label="t('personas.detail.speech.moveUp')"
              size="sm"
              @click="moveUp(index)"
            />
            <IconButton
              :icon="X"
              :label="t('personas.detail.speech.removeExample')"
              size="sm"
              @click="draft.examples.splice(index, 1)"
            />
          </div>
        </li>
      </ol>
      <div>
        <Button size="sm" variant="ghost" :icon="Plus" @click="addExample">
          {{ t('personas.detail.speech.addExample') }}
        </Button>
      </div>
    </FormSection>

    <MoreSection v-model="more" :title="t('personas.detail.more')">
      <FormSection :title="t('personas.detail.speech.styles')" :columns="1">
        <template #actions>
          <span
            v-if="draft.styles.length"
            class="text-sm tabular"
            :class="Math.abs(total - 100) < 0.01 ? 'text-muted' : 'text-error'"
          >
            {{ t('personas.detail.speech.total', { n: total }) }}
          </span>
        </template>
        <ul
          v-if="draft.styles.length"
          class="flex list-none flex-col gap-3 max-sm:gap-0 max-sm:divide-y max-sm:divide-line max-sm:border-y max-sm:border-line"
        >
          <li
            v-for="(style, index) in draft.styles"
            :key="index"
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
                :icon="X"
                :label="t('personas.detail.speech.removeStyle')"
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
      :invalid="Boolean(form.problem('speech'))"
      @save="form.save('speech')"
      @discard="form.discard('speech')"
    />
  </form>
</template>
