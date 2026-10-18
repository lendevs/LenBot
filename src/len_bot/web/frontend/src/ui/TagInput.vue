<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { TagsInputInput, TagsInputItem, TagsInputItemDelete, TagsInputItemText, TagsInputRoot } from 'reka-ui'
import { X } from '@lucide/vue'
import { useFieldControl } from './field'
import { controlFrame } from './styles'

const model = defineModel<string[]>({ default: () => [] })
const props = withDefaults(
  defineProps<{
    placeholder?: string
    /** Typed or pasted text is split here; commas (both widths) and line breaks by default. */
    delimiter?: string | RegExp
    max?: number
    id?: string
    invalid?: boolean
    disabled?: boolean
  }>(),
  { placeholder: undefined, delimiter: undefined, max: 0, id: undefined },
)

const SEPARATORS = /[,，\n]/
const { t } = useI18n()
const field = useFieldControl(props)
</script>

<template>
  <TagsInputRoot
    v-model="model"
    :delimiter="delimiter ?? SEPARATORS"
    :max="max"
    :disabled="field.disabled.value"
    add-on-paste
    add-on-blur
    :class="[controlFrame, 'min-h-9 flex-wrap gap-1.5 py-1 pl-1.5 pointer-coarse:min-h-11']"
    :data-invalid="field.invalid.value || undefined"
    :data-disabled="field.disabled.value || undefined"
  >
    <TagsInputItem
      v-for="item in model"
      :key="item"
      :value="item"
      class="inline-flex h-6 max-w-full animate-fade items-center gap-1 rounded-sm bg-fill pr-0.5 pl-2 text-sm text-ink-2 data-[state=active]:bg-selected data-[state=active]:text-primary"
    >
      <TagsInputItemText class="truncate" />
      <TagsInputItemDelete
        class="inline-flex size-5 cursor-pointer items-center justify-center rounded-sm text-subtle hover:bg-hover hover:text-ink"
        :aria-label="t('ui.tags.remove', { name: item })"
      >
        <X :size="12" aria-hidden="true" />
      </TagsInputItemDelete>
    </TagsInputItem>
    <TagsInputInput
      :id="field.id.value"
      :placeholder="model.length ? undefined : (placeholder ?? t('ui.tags.placeholder'))"
      :aria-invalid="field.invalid.value || undefined"
      :aria-describedby="field.describedBy.value"
      class="h-7 min-w-24 flex-1 bg-transparent px-1 outline-none placeholder:text-subtle focus-visible:outline-none"
    />
  </TagsInputRoot>
</template>
