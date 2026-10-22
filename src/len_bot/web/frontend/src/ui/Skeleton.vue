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
const shimmer =
  'block animate-shimmer bg-[linear-gradient(90deg,var(--track)_30%,var(--fill)_50%,var(--track)_70%)] bg-size-[200%_100%]'
</script>

<template>
  <span v-if="lines" class="flex flex-col gap-2" aria-hidden="true">
    <span
      v-for="line in lines"
      :key="line"
      :class="[shimmer, rounded]"
      :style="{ height, width: line === lines && lines > 1 ? '62%' : width }"
    />
  </span>
  <span v-else :class="[shimmer, rounded]" :style="{ width, height }" aria-hidden="true" />
</template>
