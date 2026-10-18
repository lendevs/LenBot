<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useFieldControl } from './field'

const model = defineModel<string>({ default: '' })
const props = withDefaults(
  defineProps<{
    placeholder?: string
    rows?: number
    /** Grows with its content up to this many rows, then scrolls. */
    maxRows?: number
    mono?: boolean
    id?: string
    invalid?: boolean
    disabled?: boolean
    readonly?: boolean
  }>(),
  { placeholder: undefined, rows: 3, maxRows: 14, id: undefined },
)

const field = useFieldControl(props)
const area = ref<HTMLTextAreaElement>()

function fit() {
  const element = area.value
  if (!element) return
  const style = getComputedStyle(element)
  const line = parseFloat(style.lineHeight) || 22
  const borders = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
  const frame = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + borders
  element.style.height = 'auto'
  const height = Math.min(
    Math.max(element.scrollHeight + borders, line * props.rows + frame),
    line * props.maxRows + frame,
  )
  element.style.height = `${height}px`
}

watch(model, () => nextTick(fit))
onMounted(fit)
defineExpose({ focus: () => area.value?.focus() })
</script>

<template>
  <textarea
    :id="field.id.value"
    ref="area"
    v-model="model"
    :rows="rows"
    :placeholder="placeholder"
    :disabled="field.disabled.value"
    :readonly="readonly"
    :aria-invalid="field.invalid.value || undefined"
    :aria-describedby="field.describedBy.value"
    :data-invalid="field.invalid.value || undefined"
    class="block w-full min-w-0 resize-none rounded-md border border-line-strong bg-surface px-3 py-2 text-base text-ink transition-[border-color,box-shadow] duration-150 ease-out placeholder:text-subtle scrollbar-thin hover:border-subtle focus:border-primary focus:shadow-[0_0_0_3px_var(--focus-ring)] focus-visible:outline-none disabled:cursor-not-allowed disabled:bg-fill disabled:opacity-60 data-invalid:border-error pointer-coarse:text-lg"
    :class="mono && 'font-mono text-sm leading-5'"
  />
</template>
