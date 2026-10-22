<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Copy } from '@lucide/vue'

const props = withDefaults(
  defineProps<{
    /** Text, or any value shown as indented JSON. */
    code: unknown
    /** Collapse longer content to this many lines. 0 shows everything. */
    maxLines?: number
    wrap?: boolean
    label?: string
  }>(),
  { maxLines: 18, wrap: true, label: undefined },
)

const { t } = useI18n()
const expanded = ref(false)
const copied = ref(false)
const text = computed(() => {
  if (typeof props.code === 'string') return props.code
  try {
    return JSON.stringify(props.code, null, 2) ?? String(props.code)
  } catch {
    return String(props.code)
  }
})
const lineCount = computed(() => text.value.split('\n').length)
const collapsible = computed(() => props.maxLines > 0 && lineCount.value > props.maxLines)
let timer: ReturnType<typeof setTimeout> | undefined

async function copy() {
  try {
    await navigator.clipboard.writeText(text.value)
  } catch {
    return
  }
  copied.value = true
  clearTimeout(timer)
  timer = setTimeout(() => (copied.value = false), 1600)
}
</script>

<template>
  <div class="group relative min-w-0 rounded-md border border-line bg-code text-ink-2">
    <div v-if="label" class="border-b border-line px-3 py-1.5 text-xs font-medium text-subtle">
      {{ label }}
    </div>
    <pre
      class="overflow-x-auto px-3 py-2.5 font-mono text-xs leading-5 scrollbar-thin"
      :class="[wrap && 'break-words whitespace-pre-wrap', collapsible && !expanded && 'overflow-hidden']"
      :style="collapsible && !expanded ? { maxHeight: `${maxLines * 20 + 20}px` } : undefined"
    ><code>{{ text }}</code></pre>
    <div
      v-if="collapsible && !expanded"
      class="pointer-events-none absolute inset-x-0 bottom-0 h-14 rounded-b-md bg-linear-to-t from-code to-transparent"
    />
    <button
      v-if="collapsible"
      type="button"
      class="absolute bottom-1.5 left-1/2 -translate-x-1/2 cursor-pointer rounded-full border border-line bg-surface px-2.5 py-0.5 text-xs font-medium text-muted shadow-card hover:text-ink focus-visible:focus-ring"
      :class="expanded && 'relative bottom-0 left-0 mx-auto mb-2 block translate-x-0'"
      @click="expanded = !expanded"
    >
      {{ expanded ? t('ui.code.collapse') : t('ui.code.expand', { n: lineCount }) }}
    </button>
    <button
      type="button"
      class="absolute top-1.5 right-1.5 inline-flex size-7 cursor-pointer items-center justify-center rounded-md border border-line bg-surface text-muted opacity-0 shadow-card transition-opacity group-hover:opacity-100 hover:text-ink focus-visible:opacity-100 focus-visible:focus-ring pointer-coarse:opacity-100"
      :class="label && 'top-9'"
      :aria-label="copied ? t('ui.code.copied') : t('ui.code.copy')"
      @click="copy"
    >
      <Check v-if="copied" :size="14" class="text-success" aria-hidden="true" />
      <Copy v-else :size="14" aria-hidden="true" />
    </button>
  </div>
</template>
