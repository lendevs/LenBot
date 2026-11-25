<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Several text lines with staggered widths; the last one is shorter. */
    lines?: number
    width?: string
    height?: string
    rounded?: string
  }>(),
  { lines: 0, width: '100%', height: '14px', rounded: 'rounded-sm' },
)
const bar = 'block animate-skeleton bg-track/85'
const lineWidths = ['100%', '88%', '94%', '82%']
function lineWidth(line: number, total: number): string {
  if (total <= 1) return '100%'
  if (line === total) return '64%'
  return lineWidths[(line - 1) % lineWidths.length] as string
}
</script>

<template>
  <span v-if="lines" class="flex flex-col gap-2" :style="{ width }" aria-hidden="true">
    <span
      v-for="line in lines"
      :key="line"
      :class="[bar, rounded]"
      :style="{ height, width: lineWidth(line, lines) }"
    />
  </span>
  <span v-else :class="[bar, rounded]" :style="{ width, height }" aria-hidden="true" />
</template>
