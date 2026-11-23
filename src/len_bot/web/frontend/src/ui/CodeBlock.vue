<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown, Copy, Download } from '@lucide/vue'
import { formatBytes } from '../i18n/format'

const LARGE_BYTES = 150 * 1024
const LARGE_LINES = 2000
const CHUNK_LINES = 200
const INITIAL_LARGE_CHARS = 32_768
const CHUNK_CHARS = 65_536

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
const copied = ref(false)
const text = computed(() => {
  if (typeof props.code === 'string') return props.code
  try {
    return JSON.stringify(props.code, null, 2) ?? String(props.code)
  } catch {
    return String(props.code)
  }
})
const byteSize = computed(() => new Blob([text.value]).size)
const lines = computed(() => text.value.split('\n'))
const lineCount = computed(() => lines.value.length)
const isLarge = computed(() => byteSize.value > LARGE_BYTES || lineCount.value > LARGE_LINES)
const baseLines = computed(() =>
  props.maxLines > 0 ? props.maxLines : isLarge.value ? CHUNK_LINES : lineCount.value,
)

const shownLines = ref(baseLines.value)
const charLimit = ref(INITIAL_LARGE_CHARS)
watch([() => props.code, () => props.maxLines], () => {
  shownLines.value = baseLines.value
  charLimit.value = INITIAL_LARGE_CHARS
})

const collapsible = computed(() => !isLarge.value && props.maxLines > 0 && lineCount.value > props.maxLines)
const expanded = computed(() => shownLines.value >= lineCount.value)
const sliced = computed(() => {
  if (!isLarge.value && (!collapsible.value || expanded.value)) return text.value
  return lines.value.slice(0, shownLines.value).join('\n')
})
const charsTruncated = computed(() => isLarge.value && sliced.value.length > charLimit.value)
const displayed = computed(() =>
  charsTruncated.value ? `${sliced.value.slice(0, charLimit.value)}…` : sliced.value,
)
const remainingLines = computed(() => Math.max(0, lineCount.value - shownLines.value))
const hasMore = computed(() => remainingLines.value > 0 || charsTruncated.value)
const canCollapseLarge = computed(
  () => isLarge.value && (shownLines.value > baseLines.value || charLimit.value > INITIAL_LARGE_CHARS),
)
const nextLoadCount = computed(() => Math.min(CHUNK_LINES, remainingLines.value || CHUNK_LINES))

let timer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(timer))

function toggle() {
  shownLines.value = expanded.value ? baseLines.value : lineCount.value
}
function loadMore() {
  if (charsTruncated.value) charLimit.value += CHUNK_CHARS
  if (remainingLines.value > 0) shownLines.value = Math.min(lineCount.value, shownLines.value + CHUNK_LINES)
}
function collapseLarge() {
  shownLines.value = baseLines.value
  charLimit.value = INITIAL_LARGE_CHARS
}

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

function download() {
  const isJson = typeof props.code !== 'string' || /^\s*[{[]/.test(text.value)
  const mime = isJson ? 'application/json;charset=utf-8' : 'text/plain;charset=utf-8'
  const ext = isJson ? 'json' : 'txt'
  const base = (props.label ?? 'payload').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-|-$/g, '') || 'payload'
  const filename = base.includes('.') ? base : `${base}.${ext}`
  const blob = new Blob([text.value], { type: mime })
  const url = URL.createObjectURL(blob)
  const link = Object.assign(document.createElement('a'), { href: url, download: filename })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
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
    <div
      v-if="isLarge"
      class="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-warning-bg/60 px-3 py-1.5 text-xs text-warning"
    >
      <span class="min-w-0 flex-1 tabular">
        {{ t('ui.code.largeNotice', { size: formatBytes(byteSize), n: Math.min(shownLines, lineCount) }) }}
      </span>
      <button
        type="button"
        class="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-sm px-1.5 py-0.5 font-medium text-ink transition-colors hover:bg-hover focus-visible:focus-ring"
        @click="download"
      >
        <Download :size="13" aria-hidden="true" />
        {{ t('ui.code.download') }}
      </button>
    </div>
    <div class="relative">
      <pre
        class="overflow-x-auto px-3 py-2.5 font-mono text-xs leading-5 scrollbar-thin"
        :class="[!label && 'pr-10', wrap && 'break-words whitespace-pre-wrap']"
      ><code>{{ displayed }}</code></pre>
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
    <div
      v-if="isLarge && (hasMore || canCollapseLarge)"
      class="flex flex-wrap items-center justify-center divide-x divide-line border-t border-line bg-surface/50"
    >
      <button
        v-if="hasMore"
        type="button"
        class="flex flex-1 cursor-pointer items-center justify-center gap-1 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
        @click="loadMore"
      >
        <ChevronDown :size="13" aria-hidden="true" />
        <span class="tabular">{{ t('ui.code.loadMore', { n: nextLoadCount }) }}</span>
      </button>
      <button
        v-if="canCollapseLarge"
        type="button"
        class="flex flex-1 cursor-pointer items-center justify-center gap-1 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
        @click="collapseLarge"
      >
        <ChevronDown :size="13" class="rotate-180" aria-hidden="true" />
        <span>{{ t('ui.code.collapse') }}</span>
      </button>
    </div>
    <button
      v-else-if="collapsible"
      type="button"
      class="flex w-full cursor-pointer items-center justify-center gap-1 border-t border-line bg-surface/50 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
      :aria-expanded="expanded"
      @click="toggle"
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
