<script setup lang="ts" generic="T extends string">
import { nextTick, onMounted, ref, watch, type Component } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import { ToggleGroupItem, ToggleGroupRoot } from 'reka-ui'

export interface SegmentOption<V> {
  value: V
  label: string
  icon?: Component
  disabled?: boolean
}

const model = defineModel<T>({ required: true })
const props = withDefaults(
  defineProps<{
    options: SegmentOption<T>[]
    size?: 'sm' | 'md'
    block?: boolean
    disabled?: boolean
    /** Accessible name of the group. */
    label?: string
  }>(),
  { size: 'md', label: undefined },
)

const root = ref<InstanceType<typeof ToggleGroupRoot>>()
const activeEl = ref<HTMLElement | null>(null)
const indicator = ref({ left: 0, width: 0, ready: false })

function measure() {
  const element = root.value?.$el as HTMLElement | undefined
  const active = element?.querySelector<HTMLElement>('[data-state="on"]') ?? null
  activeEl.value = active
  if (!active) {
    // No segment matches the value (a hand-tuned setting): hide the indicator.
    indicator.value = { left: 0, width: 0, ready: indicator.value.ready }
    return
  }
  indicator.value = { left: active.offsetLeft, width: active.offsetWidth, ready: indicator.value.ready }
  if (!indicator.value.ready) requestAnimationFrame(() => (indicator.value.ready = true))
  // When the segments scroll sideways (narrow screens, long labels), keep the chosen one in view.
  const start = active.offsetLeft - element!.scrollLeft
  if (start < 0) element!.scrollLeft = active.offsetLeft
  else if (start + active.offsetWidth > element!.clientWidth)
    element!.scrollLeft = active.offsetLeft + active.offsetWidth - element!.clientWidth
}

/** A segmented control always has one value: clicking the active segment again keeps it. */
function choose(value: unknown) {
  if (typeof value === 'string' && value) model.value = value as T
}

watch(model, () => nextTick(measure))
watch(
  () => props.options,
  () => nextTick(measure),
  { deep: true },
)
onMounted(measure)
useResizeObserver(() => root.value?.$el as HTMLElement | undefined, measure)
useResizeObserver(activeEl, measure)
</script>

<template>
  <ToggleGroupRoot
    ref="root"
    type="single"
    :model-value="model"
    :disabled="disabled"
    :aria-label="label"
    class="relative items-center overflow-x-auto rounded-md bg-fill p-0.5 scrollbar-none"
    :class="[block ? 'flex w-full' : 'inline-flex w-fit max-w-full', disabled && 'opacity-60']"
    @update:model-value="choose"
  >
    <span
      class="pointer-events-none absolute top-0.5 bottom-0.5 left-0 rounded-sm border border-transparent bg-surface shadow-control dark:border-line-strong/80 dark:bg-hover"
      :class="[
        indicator.ready && 'transition-[transform,width,opacity] duration-(--dur-2) ease-out',
        indicator.width === 0 && 'opacity-0',
      ]"
      :style="{ width: `${indicator.width}px`, transform: `translateX(${indicator.left}px)` }"
      aria-hidden="true"
    />
    <ToggleGroupItem
      v-for="option in options"
      :key="option.value"
      :value="option.value"
      :disabled="option.disabled"
      class="relative z-1 inline-flex min-w-0 cursor-pointer items-center justify-center gap-1.5 rounded-sm px-3 font-medium whitespace-nowrap text-muted transition-[color,transform] duration-(--dur-1) ease-out hover:text-ink focus-visible:focus-ring enabled:active:scale-[0.98] data-disabled:cursor-not-allowed data-disabled:opacity-45 data-[state=on]:text-ink"
      :class="[
        size === 'sm' ? 'h-7 text-xs pointer-coarse:h-10' : 'h-8 text-sm pointer-coarse:h-10',
        block ? 'flex-1' : 'shrink-0',
      ]"
    >
      <component
        :is="option.icon"
        v-if="option.icon"
        :size="size === 'sm' ? 14 : 15"
        class="shrink-0"
        aria-hidden="true"
      />
      <span class="truncate">{{ option.label }}</span>
    </ToggleGroupItem>
  </ToggleGroupRoot>
</template>
