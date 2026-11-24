<script setup lang="ts" generic="T">
import { computed, nextTick, onBeforeUnmount, ref, watch, type ComponentPublicInstance } from 'vue'
import { usePreferredReducedMotion, useResizeObserver } from '@vueuse/core'
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
const headerEl = ref<HTMLElement>()
const headerHeight = ref(0)
const atEnd = ref(true)
const reducedMotion = usePreferredReducedMotion()

useResizeObserver(headerEl, (entries) => {
  headerHeight.value = Math.round(entries[0]?.contentRect.height ?? headerEl.value?.offsetHeight ?? 0)
})

const virtualizer = useVirtualizer(
  computed(() => ({
    count: props.items.length,
    getScrollElement: () => scroller.value ?? null,
    estimateSize: () => props.estimateSize,
    overscan: props.overscan,
    gap: props.gap,
    scrollMargin: headerHeight.value,
    getItemKey: (index: number) => props.getKey(props.items[index] as T),
  })),
)
const rows = computed(() => virtualizer.value.getVirtualItems())
const total = computed(() => virtualizer.value.getTotalSize())

let pinFrame: number | undefined
let pinTimer: ReturnType<typeof setTimeout> | undefined
let anchorFrame: number | undefined
let pinning = false
let followResize = false
let adjusting = false
let lastScrollTop = 0
let lastTouchY: number | null = null

function cancelPin() {
  if (pinFrame !== undefined) {
    cancelAnimationFrame(pinFrame)
    pinFrame = undefined
  }
  if (pinTimer !== undefined) {
    clearTimeout(pinTimer)
    pinTimer = undefined
  }
  pinning = false
}

function detachFollow() {
  cancelPin()
  followResize = false
  atEnd.value = false
}

function measure(element: Element | ComponentPublicInstance | null) {
  if (element instanceof Element) virtualizer.value.measureElement(element)
}

function onWheel(event: WheelEvent) {
  if (event.deltaY < 0) detachFollow()
}

function onTouchStart(event: TouchEvent) {
  lastTouchY = event.touches[0]?.clientY ?? null
}

function onTouchMove(event: TouchEvent) {
  const y = event.touches[0]?.clientY
  if (y === undefined) return
  if (lastTouchY !== null && y > lastTouchY + 2) detachFollow()
  lastTouchY = y
}

function onScroll() {
  const element = scroller.value
  if (!element) return
  const fromEnd = element.scrollHeight - element.scrollTop - element.clientHeight
  if (!pinning) {
    if (element.scrollTop < lastScrollTop - 1 && fromEnd >= 24) detachFollow()
    else atEnd.value = fromEnd < 24
  }
  lastScrollTop = element.scrollTop
  if (adjusting || !props.items.length) return
  if (element.scrollTop < props.threshold) emit('reachStart')
  if (fromEnd < props.threshold) emit('reachEnd')
}

/**
 * Rows near the end may not be measured yet, so scrolling by index lands short of the real end. The scroller
 * is pinned to its full height instead, again on the next frames while newly rendered rows report their size.
 */
function scrollToEnd(behavior: ScrollBehavior = 'auto') {
  const element = scroller.value
  if (!element || !props.items.length) return
  const effectiveBehavior: ScrollBehavior =
    behavior === 'smooth' && reducedMotion.value === 'reduce' ? 'auto' : behavior
  cancelPin()
  atEnd.value = true
  pinning = true
  followResize = true
  let frames = 3
  const pin = () => {
    if (!atEnd.value) {
      pinning = false
      followResize = false
      return
    }
    element.scrollTop = element.scrollHeight
    lastScrollTop = element.scrollTop
    atEnd.value = true
    if (--frames > 0) pinFrame = requestAnimationFrame(pin)
    else {
      pinFrame = undefined
      pinning = false
      followResize = false
    }
  }
  if (effectiveBehavior === 'smooth') {
    element.scrollTo({ top: element.scrollHeight, behavior: effectiveBehavior })
    pinTimer = setTimeout(() => {
      pinTimer = undefined
      if (atEnd.value) pin()
      else {
        pinning = false
        followResize = false
      }
    }, 450)
  } else pin()
}

/**
 * Prepending older rows (loading history) keeps the visible anchor row fixed in the viewport; appending while
 * pinned to the end follows only when new rows arrive at the tail.
 */
watch(
  () => props.items,
  (next, previous) => {
    const element = scroller.value
    if (!element || !next.length) return
    if (!previous?.length) {
      if (props.followEnd && atEnd.value) {
        followResize = true
        nextTick(() => atEnd.value && scrollToEnd())
      }
      return
    }
    const wasAtEnd = atEnd.value
    const firstKey = props.getKey(previous[0] as T)
    const prepended =
      props.getKey(next[0] as T) !== firstKey && next.some((item) => props.getKey(item) === firstKey)
    const shouldAnchor = prepended && (props.followEnd || element.scrollTop > 4)

    if (shouldAnchor) {
      const visibleRow =
        rows.value.find((row) => row.end > element.scrollTop + headerHeight.value) ?? rows.value[0]
      const anchorOldIndex = visibleRow ? visibleRow.index : 0
      const anchorKey = props.getKey(previous[anchorOldIndex] as T)
      const anchorNewIndex = next.findIndex((item) => props.getKey(item) === anchorKey)
      const scrollerTop = element.getBoundingClientRect().top
      const anchorEl = element.querySelector<HTMLElement>(`[data-index="${anchorOldIndex}"]`)
      const anchorOffsetBefore = anchorEl ? anchorEl.getBoundingClientRect().top - scrollerTop : null
      const top = element.scrollTop
      const before = total.value

      followResize = false
      cancelPin()
      adjusting = true
      if (anchorFrame !== undefined) cancelAnimationFrame(anchorFrame)
      nextTick(() => {
        element.scrollTop = top + (total.value - before)
        lastScrollTop = element.scrollTop
        anchorFrame = requestAnimationFrame(() => {
          anchorFrame = undefined
          if (anchorNewIndex >= 0 && anchorOffsetBefore !== null) {
            const movedEl = element.querySelector<HTMLElement>(`[data-index="${anchorNewIndex}"]`)
            if (movedEl) {
              const offsetAfter = movedEl.getBoundingClientRect().top - element.getBoundingClientRect().top
              const diff = offsetAfter - anchorOffsetBefore
              if (Math.abs(diff) > 0.5) element.scrollTop += diff
            }
          }
          lastScrollTop = element.scrollTop
          adjusting = false
        })
      })
      return
    }

    if (props.followEnd && wasAtEnd && !prepended) {
      const prevLastKey = props.getKey(previous[previous.length - 1] as T)
      const nextLastKey = props.getKey(next[next.length - 1] as T)
      const tailAppended =
        nextLastKey !== prevLastKey && !previous.some((item) => props.getKey(item) === nextLastKey)
      if (tailAppended || next.length > previous.length) {
        followResize = true
        nextTick(() => atEnd.value && scrollToEnd())
      }
    }
  },
  { flush: 'pre' },
)
watch(total, (nextTotal, prevTotal) => {
  if (adjusting || nextTotal === prevTotal) return
  if (props.followEnd && atEnd.value && followResize) {
    nextTick(() => atEnd.value && !adjusting && followResize && scrollToEnd())
    return
  }
  const element = scroller.value
  if (element && !pinning) {
    nextTick(() => {
      if (!pinning && !adjusting) {
        atEnd.value = element.scrollHeight - element.scrollTop - element.clientHeight < 24
      }
    })
  }
})

onBeforeUnmount(() => {
  cancelPin()
  if (anchorFrame !== undefined) cancelAnimationFrame(anchorFrame)
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
    @wheel.passive="onWheel"
    @touchstart.passive="onTouchStart"
    @touchmove.passive="onTouchMove"
  >
    <div v-if="$slots.header" ref="headerEl">
      <slot name="header" />
    </div>
    <div class="relative w-full" :style="{ height: `${total}px` }">
      <div
        v-for="row in rows"
        :key="row.key as PropertyKey"
        :ref="measure"
        :data-index="row.index"
        class="absolute top-0 left-0 w-full"
        :style="{ transform: `translateY(${row.start - headerHeight}px)` }"
      >
        <slot :item="items[row.index] as T" :index="row.index" />
      </div>
    </div>
    <div v-if="$slots.footer">
      <slot name="footer" />
    </div>
  </div>
</template>
