<script setup lang="ts">
import { ChevronDown } from '@lucide/vue'

/** Settings that rarely change, folded under one heading; opened from outside when one of them is wrong. */
const open = defineModel<boolean>({ default: false })
defineProps<{ title: string }>()
</script>

<template>
  <section class="border-t border-line pt-5">
    <button
      type="button"
      class="group flex w-full cursor-pointer items-center justify-between gap-3 rounded-md py-0.5 text-left transition-colors hover:text-ink focus-visible:focus-ring"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="text-sm font-semibold text-ink-2 transition-colors group-hover:text-ink">{{ title }}</span>
      <ChevronDown
        :size="17"
        class="shrink-0 text-subtle transition-transform duration-200 ease-out group-hover:text-ink-2"
        :class="open && 'rotate-180'"
        aria-hidden="true"
      />
    </button>
    <div v-if="open" class="mt-4 grid animate-rise gap-x-5 gap-y-5 sm:grid-cols-2">
      <slot />
    </div>
  </section>
</template>
