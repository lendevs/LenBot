<script setup lang="ts">
export type Tone = 'neutral' | 'brand' | 'success' | 'warning' | 'error' | 'info'

withDefaults(defineProps<{ tone?: Tone; dot?: boolean; pulse?: boolean; size?: 'sm' | 'md' }>(), {
  tone: 'neutral',
  size: 'sm',
})

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
    class="inline-flex max-w-full shrink-0 items-center gap-1.5 rounded-full font-medium whitespace-nowrap"
    :class="[tones[tone], size === 'md' ? 'h-8 px-3 text-sm' : 'h-5 px-2 text-xs']"
  >
    <span
      v-if="dot"
      class="size-1.5 shrink-0 rounded-full bg-current"
      :class="pulse && 'animate-pulse-dot'"
    />
    <span class="truncate"><slot /></span>
  </span>
</template>
