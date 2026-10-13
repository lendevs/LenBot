<script setup lang="ts">
export type Tone = 'neutral' | 'brand' | 'success' | 'warning' | 'error' | 'info'

withDefaults(defineProps<{ tone?: Tone; dot?: boolean; pulse?: boolean }>(), { tone: 'neutral' })

const tones: Record<Tone, string> = {
  neutral: 'bg-fill text-muted',
  brand: 'bg-brand-soft text-primary',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning',
  error: 'bg-error-bg text-error',
  info: 'bg-info-bg text-info',
}
</script>

<template>
  <span
    class="inline-flex h-5 max-w-full shrink-0 items-center gap-1.5 rounded-full px-2 text-xs font-medium whitespace-nowrap"
    :class="tones[tone]"
  >
    <span
      v-if="dot"
      class="size-1.5 shrink-0 rounded-full bg-current"
      :class="pulse && 'animate-pulse-dot'"
    />
    <span class="truncate"><slot /></span>
  </span>
</template>
