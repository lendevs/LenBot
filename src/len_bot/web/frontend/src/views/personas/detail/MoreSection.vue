<script setup lang="ts">
import { ChevronDown } from '@lucide/vue'

/** Fields most roles leave alone, folded under one heading at the end of a role tab. */
const open = defineModel<boolean>({ default: false })
defineProps<{ title: string }>()
</script>

<template>
  <section class="border-t border-line pt-6">
    <button
      type="button"
      class="flex w-full cursor-pointer items-center justify-between gap-3 rounded-sm text-left focus-visible:focus-ring"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="text-base font-semibold text-ink">{{ title }}</span>
      <ChevronDown
        :size="18"
        class="text-subtle transition-transform"
        :class="open && 'rotate-180'"
        aria-hidden="true"
      />
    </button>
    <div v-if="open" class="mt-5 flex animate-rise flex-col gap-8">
      <slot />
    </div>
  </section>
</template>
