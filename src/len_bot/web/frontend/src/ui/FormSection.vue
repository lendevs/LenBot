<script setup lang="ts">
withDefaults(defineProps<{ title?: string; columns?: 1 | 2 }>(), { title: undefined, columns: 2 })
</script>

<template>
  <section class="border-t border-line pt-6 first:border-t-0 first:pt-0">
    <header v-if="title || $slots.actions" class="mb-4 flex min-h-8 items-center justify-between gap-3">
      <h3 v-if="title" class="text-base font-semibold text-ink">{{ title }}</h3>
      <div v-if="$slots.actions" class="flex items-center gap-2"><slot name="actions" /></div>
    </header>
    <div class="grid gap-x-5 gap-y-5" :class="columns === 2 && 'sm:grid-cols-2'">
      <slot />
    </div>
  </section>
</template>
