<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { TagsInputInput, TagsInputItem, TagsInputItemDelete, TagsInputItemText, TagsInputRoot } from 'reka-ui'
import { X } from '@lucide/vue'
import { useFieldControl } from './field'
import { controlFrameBase } from './styles'

const model = defineModel<string[]>({ default: () => [] })
const props = withDefaults(
  defineProps<{
    placeholder?: string
    /** Typed or pasted text is split here; commas (both widths) and line breaks by default. */
    delimiter?: string | RegExp
    max?: number
    size?: 'sm' | 'md'
    id?: string
    invalid?: boolean
    disabled?: boolean
  }>(),
  { placeholder: undefined, delimiter: undefined, max: 0, size: 'md', id: undefined },
)

const SEPARATORS = /[,\uff0c\n]/
const { t } = useI18n()
const field = useFieldControl(props)
const duplicate = ref<string | null>(null)
let duplicateTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(duplicateTimer))

function onInvalid(payload: unknown) {
  const value = typeof payload === 'string' ? payload : String(payload ?? '')
  if (!model.value.includes(value)) return
  duplicate.value = value
  clearTimeout(duplicateTimer)
  duplicateTimer = setTimeout(() => {
    duplicate.value = null
  }, 900)
}
</script>

<template>
  <TagsInputRoot
    v-model="model"
    :delimiter="delimiter ?? SEPARATORS"
    :max="max"
    :disabled="field.disabled.value"
    add-on-paste
    add-on-blur
    :class="[
      controlFrameBase,
      size === 'sm' ? 'min-h-8 text-sm pointer-coarse:min-h-10' : 'min-h-9 text-base pointer-coarse:min-h-11',
      'flex-wrap gap-1.5 py-1 pr-3 pl-1.5',
    ]"
    :data-invalid="field.invalid.value || undefined"
    :data-disabled="field.disabled.value || undefined"
    @invalid="onInvalid"
  >
    <TransitionGroup name="ui-list">
      <TagsInputItem
        v-for="item in model"
        :key="item"
        :value="item"
        class="inline-flex h-6 max-w-full items-center gap-1 rounded-sm border pr-0.5 pl-2 text-xs font-medium transition-[border-color,background-color,color] duration-(--dur-1) ease-out data-[state=active]:border-line-strong data-[state=active]:bg-hover data-[state=active]:text-ink pointer-coarse:min-h-7"
        :class="duplicate === item ? 'border-primary bg-selected text-ink' : 'border-line bg-fill text-ink-2'"
      >
        <TagsInputItemText class="truncate" />
        <TagsInputItemDelete
          class="inline-flex size-5 cursor-pointer items-center justify-center rounded-xs text-subtle transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring pointer-coarse:size-7"
          :aria-label="t('ui.tags.remove', { name: item })"
        >
          <X :size="12" aria-hidden="true" />
        </TagsInputItemDelete>
      </TagsInputItem>
    </TransitionGroup>
    <TagsInputInput
      :id="field.id.value"
      :placeholder="model.length ? undefined : (placeholder ?? t('ui.tags.placeholder'))"
      :aria-invalid="field.invalid.value || undefined"
      :aria-describedby="field.describedBy.value"
      class="h-6 min-w-20 flex-1 bg-transparent px-1 outline-none placeholder:text-subtle focus-visible:outline-none disabled:cursor-not-allowed"
    />
  </TagsInputRoot>
</template>
