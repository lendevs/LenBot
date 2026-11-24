<script setup lang="ts">
import { nextTick, onActivated, onMounted, ref, watch } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import { useFieldControl } from './field'

const LARGE_TEXT_LENGTH = 20_000

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
let atMax = false
let cachedMaxHeight = 0
let lastLength = 0
let lastWidth = 0

function measureMetrics(element: HTMLTextAreaElement) {
  const style = getComputedStyle(element)
  const line = parseFloat(style.lineHeight) || 22
  const borders = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
  const frame = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + borders
  const minHeight = line * props.rows + frame
  const maxHeight = line * props.maxRows + frame
  cachedMaxHeight = maxHeight
  return { borders, minHeight, maxHeight }
}

function fit(force = false) {
  const element = area.value
  if (!element) return
  const length = model.value.length
  if (length > LARGE_TEXT_LENGTH) {
    if (!atMax || force || !cachedMaxHeight) {
      const { maxHeight } = measureMetrics(element)
      element.style.height = `${maxHeight}px`
      atMax = true
    }
    lastLength = length
    return
  }
  if (atMax && !force) {
    if (length >= lastLength || element.scrollHeight > element.clientHeight + 2) {
      lastLength = length
      return
    }
  }
  const { borders, minHeight, maxHeight } = measureMetrics(element)
  element.style.height = 'auto'
  const rawHeight = Math.max(element.scrollHeight + borders, minHeight)
  const clamped = Math.min(rawHeight, maxHeight)
  atMax = rawHeight >= maxHeight
  lastLength = length
  element.style.height = `${clamped}px`
}

watch(model, () => nextTick(() => fit()))
watch([() => props.rows, () => props.maxRows], () => nextTick(() => fit(true)))
onMounted(() => {
  lastWidth = area.value?.clientWidth ?? 0
  fit(true)
})
onActivated(() => {
  lastWidth = area.value?.clientWidth ?? 0
  fit(true)
})
useResizeObserver(area, (entries) => {
  const width = Math.round(entries[0]?.contentRect.width ?? area.value?.clientWidth ?? 0)
  if (width && width !== lastWidth) {
    lastWidth = width
    fit(true)
  }
})
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
    class="block w-full min-w-0 resize-none overflow-y-auto rounded-md border border-line-strong bg-surface px-3 py-2 text-ink transition-[border-color,box-shadow,background-color] duration-(--dur-1) ease-out placeholder:text-subtle scrollbar-thin hover:border-subtle focus:border-primary focus:shadow-focus focus-visible:outline-none read-only:bg-fill/55 disabled:cursor-not-allowed disabled:bg-fill disabled:opacity-60 disabled:hover:border-line-strong data-invalid:border-error data-invalid:hover:border-error data-invalid:focus:border-error data-invalid:focus:shadow-error-focus"
    :class="
      mono
        ? 'font-mono text-sm leading-5 pointer-coarse:text-lg pointer-coarse:leading-6'
        : 'text-base pointer-coarse:text-lg'
    "
  />
</template>
