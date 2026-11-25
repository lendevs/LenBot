<script setup lang="ts" generic="T extends string">
import { nextTick, onMounted, ref, watch, type Component } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import { TabsContent, TabsIndicator, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'

export interface TabItem<V> {
  value: V
  label: string
  icon?: Component
  /** A count shown after the label, such as unread errors. */
  count?: number
  /** A status dot shown after the label (`'error'` uses error tone; others use warning). */
  dot?: 'warning' | 'error' | boolean
  disabled?: boolean
}

/** Panels are named slots, one per tab value; tabs without a slot only switch the value (for routed pages). */
const model = defineModel<T>({ required: true })
const props = withDefaults(
  defineProps<{ items: TabItem<T>[]; label?: string; orientation?: 'horizontal' | 'vertical' }>(),
  { label: undefined, orientation: 'horizontal' },
)

const list = ref<InstanceType<typeof TabsList>>()
const overflowLeft = ref(false)
const overflowRight = ref(false)
const ready = ref(false)

function updateOverflow() {
  if (props.orientation === 'vertical') {
    overflowLeft.value = false
    overflowRight.value = false
    return
  }
  const element = list.value?.$el as HTMLElement | undefined
  if (!element) return
  overflowLeft.value = element.scrollLeft > 2
  overflowRight.value = element.scrollLeft + element.clientWidth < element.scrollWidth - 2
}

function keepActiveInView() {
  if (props.orientation === 'vertical') {
    updateOverflow()
    return
  }
  const element = list.value?.$el as HTMLElement | undefined
  const active = element?.querySelector<HTMLElement>('[data-state="active"]')
  if (!element || !active) {
    updateOverflow()
    return
  }
  const behavior: ScrollBehavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? 'auto'
    : 'smooth'
  const margin = 24
  const start = active.offsetLeft - element.scrollLeft
  if (start < margin) {
    element.scrollTo({ left: Math.max(0, active.offsetLeft - margin), behavior })
  } else if (start + active.offsetWidth > element.clientWidth - margin) {
    element.scrollTo({
      left: active.offsetLeft + active.offsetWidth + margin - element.clientWidth,
      behavior,
    })
  }
  updateOverflow()
}

watch(model, () => nextTick(keepActiveInView))
watch(
  () => [props.items, props.orientation],
  () => nextTick(updateOverflow),
  { deep: true },
)
onMounted(() =>
  nextTick(() => {
    keepActiveInView()
    requestAnimationFrame(() => {
      ready.value = true
    })
  }),
)
useResizeObserver(() => list.value?.$el as HTMLElement | undefined, updateOverflow)
</script>

<template>
  <TabsRoot
    v-model="model"
    :orientation="orientation"
    class="flex min-w-0"
    :class="orientation === 'vertical' ? 'flex-row items-start gap-6' : 'flex-col'"
    :unmount-on-hide="true"
  >
    <div
      :class="
        orientation === 'vertical'
          ? 'relative shrink-0'
          : 'relative before:pointer-events-none before:absolute before:inset-x-0 before:bottom-0 before:h-px before:bg-line'
      "
    >
      <TabsList
        ref="list"
        :aria-label="label"
        :data-overflow-left="orientation === 'horizontal' && overflowLeft ? '' : undefined"
        :data-overflow-right="orientation === 'horizontal' && overflowRight ? '' : undefined"
        class="ui-tabs-list relative flex shrink-0"
        :class="
          orientation === 'vertical'
            ? 'flex-col items-stretch gap-0.5 border-r border-line pr-2'
            : 'items-center gap-1 overflow-x-auto scrollbar-none'
        "
        @scroll.passive="updateOverflow"
      >
        <TabsIndicator
          class="pointer-events-none absolute z-1 rounded-full"
          :class="[
            orientation === 'vertical'
              ? 'top-0 -right-px h-(--reka-tabs-indicator-size) w-0.5 translate-y-(--reka-tabs-indicator-position)'
              : 'bottom-0 left-0 h-0.5 w-(--reka-tabs-indicator-size) translate-x-(--reka-tabs-indicator-position)',
            ready &&
              (orientation === 'vertical'
                ? 'transition-[height,translate] duration-(--dur-3) ease-out'
                : 'transition-[width,translate] duration-(--dur-3) ease-out'),
          ]"
        >
          <span class="block size-full rounded-full bg-brand" />
        </TabsIndicator>
        <TabsTrigger
          v-for="item in items"
          :key="item.value"
          :value="item.value"
          :disabled="item.disabled"
          class="group relative inline-flex shrink-0 cursor-pointer items-center gap-1.5 px-3 text-sm font-medium whitespace-nowrap text-muted transition-colors duration-(--dur-1) outline-none hover:text-ink focus-visible:focus-ring data-disabled:cursor-not-allowed data-disabled:opacity-45 data-[state=active]:font-semibold data-[state=active]:text-ink"
          :class="orientation === 'vertical' ? 'h-9 justify-start rounded-md' : 'h-10 rounded-t-md'"
        >
          <component :is="item.icon" v-if="item.icon" :size="15" class="shrink-0" aria-hidden="true" />
          <span class="inline-grid">
            <span class="col-start-1 row-start-1">{{ item.label }}</span>
            <span class="invisible col-start-1 row-start-1 font-semibold select-none" aria-hidden="true">
              {{ item.label }}
            </span>
          </span>
          <span
            v-if="item.dot"
            class="size-1.5 shrink-0 rounded-full"
            :class="item.dot === 'error' ? 'bg-error' : 'bg-warning'"
            aria-hidden="true"
          />
          <span
            v-if="item.count"
            class="inline-flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-fill px-1.5 text-2xs font-medium text-muted tabular transition-colors group-data-[state=active]:bg-hover group-data-[state=active]:text-ink-2"
          >
            {{ item.count }}
          </span>
        </TabsTrigger>
      </TabsList>
    </div>
    <template v-for="item in items" :key="item.value">
      <TabsContent
        v-if="$slots[item.value]"
        :value="item.value"
        class="min-w-0 animate-fade outline-none focus-visible:focus-ring"
        :class="orientation === 'vertical' ? 'flex-1' : 'pt-5'"
      >
        <slot :name="item.value" />
      </TabsContent>
    </template>
  </TabsRoot>
</template>
