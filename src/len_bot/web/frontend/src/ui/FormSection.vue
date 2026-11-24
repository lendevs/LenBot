<script setup lang="ts">
withDefaults(defineProps<{ id?: string; title?: string; columns?: 1 | 2; compact?: boolean }>(), {
  id: undefined,
  title: undefined,
  columns: 2,
})
</script>

<template>
  <section
    :id="id"
    class="scroll-mt-20 border-t border-line first:border-t-0 first:pt-0"
    :class="compact ? 'pt-4' : 'pt-6'"
  >
    <header v-if="title || $slots.actions" class="flex min-h-8 flex-wrap items-center justify-between gap-3">
      <h3 v-if="title" class="text-base font-semibold text-ink">{{ title }}</h3>
      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2"><slot name="actions" /></div>
    </header>
    <!-- A section whose fields are all switched off collapses to its header. -->
    <div
      class="grid empty:hidden"
      :class="[
        compact ? 'gap-x-4 gap-y-4' : 'gap-x-5 gap-y-5',
        columns === 2 && 'sm:grid-cols-2',
        (title || $slots.actions) && (compact ? 'mt-3' : 'mt-4'),
      ]"
    >
      <slot />
    </div>
  </section>
</template>
