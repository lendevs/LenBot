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
  disabled?: boolean
}

/** Panels are named slots, one per tab value; tabs without a slot only switch the value (for routed pages). */
const model = defineModel<T>({ required: true })
const props = withDefaults(defineProps<{ items: TabItem<T>[]; label?: string }>(), { label: undefined })

const list = ref<InstanceType<typeof TabsList>>()
const overflowLeft = ref(false)
const overflowRight = ref(false)

function updateOverflow() {
  const element = list.value?.$el as HTMLElement | undefined
  if (!element) return
  overflowLeft.value = element.scrollLeft > 2
  overflowRight.value = element.scrollLeft + element.clientWidth < element.scrollWidth - 2
}

function keepActiveInView() {
  const element = list.value?.$el as HTMLElement | undefined
  const active = element?.querySelector<HTMLElement>('[data-state="active"]')
  if (!element || !active) {
    updateOverflow()
    return
  }
  const margin = 24
  const start = active.offsetLeft - element.scrollLeft
  if (start < margin) {
    element.scrollTo({ left: Math.max(0, active.offsetLeft - margin), behavior: 'smooth' })
  } else if (start + active.offsetWidth > element.clientWidth - margin) {
    element.scrollTo({
      left: active.offsetLeft + active.offsetWidth + margin - element.clientWidth,
      behavior: 'smooth',
    })
  }
  updateOverflow()
}

watch(model, () => nextTick(keepActiveInView))
watch(
  () => props.items,
  () => nextTick(updateOverflow),
  { deep: true },
)
onMounted(() => nextTick(keepActiveInView))
useResizeObserver(() => list.value?.$el as HTMLElement | undefined, updateOverflow)
</script>

<template>
  <TabsRoot v-model="model" class="flex min-w-0 flex-col" :unmount-on-hide="true">
    <div
      class="relative before:pointer-events-none before:absolute before:inset-x-0 before:bottom-0 before:h-px before:bg-line"
    >
      <TabsList
        ref="list"
        :aria-label="label"
        :data-overflow-left="overflowLeft || undefined"
        :data-overflow-right="overflowRight || undefined"
        class="ui-tabs-list relative flex shrink-0 items-center gap-1 overflow-x-auto scrollbar-none"
        @scroll.passive="updateOverflow"
      >
        <TabsIndicator
          class="pointer-events-none absolute bottom-0 left-0 z-1 h-0.5 w-(--reka-tabs-indicator-size) translate-x-(--reka-tabs-indicator-position) rounded-full transition-[width,translate] duration-200 ease-out"
        >
          <span class="block size-full rounded-full bg-brand" />
        </TabsIndicator>
        <TabsTrigger
          v-for="item in items"
          :key="item.value"
          :value="item.value"
          :disabled="item.disabled"
          class="group relative inline-flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-t-md px-3 text-sm font-medium whitespace-nowrap text-muted transition-colors duration-150 outline-none hover:text-ink focus-visible:focus-ring data-disabled:cursor-not-allowed data-disabled:opacity-45 data-[state=active]:font-semibold data-[state=active]:text-ink"
        >
          <component :is="item.icon" v-if="item.icon" :size="15" class="shrink-0" aria-hidden="true" />
          <span>{{ item.label }}</span>
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
        class="min-w-0 animate-fade pt-5 outline-none focus-visible:focus-ring"
      >
        <slot :name="item.value" />
      </TabsContent>
    </template>
  </TabsRoot>
</template>
