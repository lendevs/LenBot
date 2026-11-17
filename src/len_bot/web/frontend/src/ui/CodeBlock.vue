<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown, Copy } from '@lucide/vue'

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
  <div class="group relative min-w-0 overflow-hidden rounded-md border border-line bg-code text-ink-2">
    <div
      v-if="label"
      class="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5 text-xs font-medium text-subtle"
    >
      <span class="min-w-0 truncate">{{ label }}</span>
      <button
        type="button"
        class="-my-0.5 -mr-1 inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-sm text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
        :aria-label="copied ? t('ui.code.copied') : t('ui.code.copy')"
        @click="copy"
      >
        <Check v-if="copied" :size="13" class="text-success" aria-hidden="true" />
        <Copy v-else :size="13" aria-hidden="true" />
      </button>
    </div>
    <div class="relative">
      <pre
        class="overflow-x-auto px-3 py-2.5 font-mono text-xs leading-5 scrollbar-thin"
        :class="[
          !label && 'pr-10',
          wrap && 'break-words whitespace-pre-wrap',
          collapsible && !expanded && 'overflow-hidden',
        ]"
        :style="collapsible && !expanded ? { maxHeight: `${maxLines * 20 + 20}px` } : undefined"
      ><code>{{ text }}</code></pre>
      <button
        v-if="!label"
        type="button"
        class="absolute top-1.5 right-1.5 inline-flex size-7 cursor-pointer items-center justify-center rounded-md border border-line bg-surface text-muted opacity-0 shadow-card transition-[opacity,color,background-color] group-hover:opacity-100 hover:bg-hover hover:text-ink focus-visible:opacity-100 focus-visible:focus-ring pointer-coarse:opacity-100"
        :aria-label="copied ? t('ui.code.copied') : t('ui.code.copy')"
        @click="copy"
      >
        <Check v-if="copied" :size="14" class="text-success" aria-hidden="true" />
        <Copy v-else :size="14" aria-hidden="true" />
      </button>
    </div>
    <button
      v-if="collapsible"
      type="button"
      class="flex w-full cursor-pointer items-center justify-center gap-1 border-t border-line bg-surface/50 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <ChevronDown
        :size="13"
        class="transition-transform duration-150"
        :class="expanded && 'rotate-180'"
        aria-hidden="true"
      />
      <span class="tabular">
        {{ expanded ? t('ui.code.collapse') : t('ui.code.expand', { n: lineCount }) }}
      </span>
    </button>
  </div>
</template>
