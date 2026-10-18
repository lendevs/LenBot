<script setup lang="ts" generic="T">
import { computed, nextTick, ref, watch, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'

const props = withDefaults(
  defineProps<{
    items: T[]
    getKey: (item: T) => string | number
    /** Initial guess in pixels; rows are measured once rendered. */
    estimateSize?: number
    overscan?: number
    gap?: number
    /** Keep the view pinned to the newest row while the user is already at the end (live timelines). */
    followEnd?: boolean
    /** Distance in pixels from either end that fires reach-start / reach-end. */
    threshold?: number
  }>(),
  { estimateSize: 56, overscan: 8, gap: 0, threshold: 240 },
)
const emit = defineEmits<{ reachStart: []; reachEnd: [] }>()

const scroller = ref<HTMLElement>()
const atEnd = ref(true)
const virtualizer = useVirtualizer(
  computed(() => ({
    count: props.items.length,
    getScrollElement: () => scroller.value ?? null,
    estimateSize: () => props.estimateSize,
    overscan: props.overscan,
    gap: props.gap,
    getItemKey: (index: number) => props.getKey(props.items[index] as T),
  })),
)
const rows = computed(() => virtualizer.value.getVirtualItems())
const total = computed(() => virtualizer.value.getTotalSize())

function measure(element: Element | ComponentPublicInstance | null) {
  if (element instanceof Element) virtualizer.value.measureElement(element)
}

function onScroll() {
  const element = scroller.value
  if (!element) return
  const fromEnd = element.scrollHeight - element.scrollTop - element.clientHeight
  atEnd.value = fromEnd < 24
  if (element.scrollTop < props.threshold) emit('reachStart')
  if (fromEnd < props.threshold) emit('reachEnd')
}

function scrollToEnd(behavior: ScrollBehavior = 'auto') {
  if (!props.items.length) return
  virtualizer.value.scrollToIndex(props.items.length - 1, { align: 'end', behavior })
  atEnd.value = true
}

/**
 * Prepending older rows (loading history) keeps the rows on screen where they were; appending while at the
 * end follows the new rows when followEnd is set. Size changes of rows above the viewport are corrected by
 * the virtualizer itself.
 */
watch(
  () => props.items,
  (next, previous) => {
    const element = scroller.value
    if (!element || !previous?.length || !next.length) return
    const wasAtEnd = atEnd.value
    const firstKey = props.getKey(previous[0] as T)
    const prepended =
      props.getKey(next[0] as T) !== firstKey && next.some((item) => props.getKey(item) === firstKey)
    const top = element.scrollTop
    const before = total.value
    nextTick(() => {
      if (prepended) element.scrollTop = top + (total.value - before)
      else if (props.followEnd && wasAtEnd) scrollToEnd()
    })
  },
  { flush: 'pre' },
)
watch(total, () => {
  if (props.followEnd && atEnd.value) nextTick(() => scrollToEnd())
})

defineExpose({
  scrollToEnd,
  scrollToIndex: (index: number, align: 'start' | 'center' | 'end' | 'auto' = 'auto') =>
    virtualizer.value.scrollToIndex(index, { align }),
  atEnd,
})
</script>

<template>
  <div
    ref="scroller"
    class="relative min-h-0 overflow-y-auto overscroll-contain scrollbar-thin"
    @scroll.passive="onScroll"
  >
    <div class="relative w-full" :style="{ height: `${total}px` }">
      <div
        v-for="row in rows"
        :key="row.key as PropertyKey"
        :ref="measure"
        :data-index="row.index"
        class="absolute top-0 left-0 w-full"
        :style="{ transform: `translateY(${row.start}px)` }"
      >
        <slot :item="items[row.index] as T" :index="row.index" />
      </div>
    </div>
  </div>
</template>
