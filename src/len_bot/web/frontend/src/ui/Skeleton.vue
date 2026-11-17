<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Several text lines; the last one is shorter. */
    lines?: number
    width?: string
    height?: string
    rounded?: string
  }>(),
  { lines: 0, width: '100%', height: '14px', rounded: 'rounded-sm' },
)
const bar = 'block animate-skeleton bg-track/85'
</script>

<template>
  <span v-if="lines" class="flex flex-col gap-2" aria-hidden="true">
    <span
      v-for="line in lines"
      :key="line"
      :class="[bar, rounded]"
      :style="{ height, width: line === lines && lines > 1 ? '62%' : width }"
    />
  </span>
  <span v-else :class="[bar, rounded]" :style="{ width, height }" aria-hidden="true" />
</template>
