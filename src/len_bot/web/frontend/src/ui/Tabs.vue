<script setup lang="ts" generic="T extends string">
import type { Component } from 'vue'
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
withDefaults(defineProps<{ items: TabItem<T>[]; label?: string }>(), { label: undefined })
</script>

<template>
  <TabsRoot v-model="model" class="flex min-w-0 flex-col" :unmount-on-hide="true">
    <TabsList
      :aria-label="label"
      class="relative flex shrink-0 items-center gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]"
    >
      <TabsIndicator
        class="absolute bottom-0 left-0 h-0.5 w-(--reka-tabs-indicator-size) translate-x-(--reka-tabs-indicator-position) rounded-full transition-[width,translate] duration-250 ease-out"
      >
        <span class="block size-full rounded-full bg-primary" />
      </TabsIndicator>
      <TabsTrigger
        v-for="item in items"
        :key="item.value"
        :value="item.value"
        :disabled="item.disabled"
        class="relative inline-flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-t-md px-3 text-sm font-medium whitespace-nowrap text-muted transition-colors duration-150 outline-none hover:text-ink focus-visible:focus-ring data-disabled:cursor-not-allowed data-disabled:opacity-45 data-[state=active]:text-ink"
      >
        <component :is="item.icon" v-if="item.icon" :size="15" aria-hidden="true" />
        {{ item.label }}
        <span
          v-if="item.count"
          class="inline-flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-fill px-1 text-[11px] text-muted tabular"
        >
          {{ item.count }}
        </span>
      </TabsTrigger>
    </TabsList>
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
