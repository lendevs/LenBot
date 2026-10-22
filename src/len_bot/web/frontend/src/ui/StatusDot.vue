<script setup lang="ts">
import type { Tone } from './Badge.vue'

withDefaults(defineProps<{ tone?: Tone | 'idle'; pulse?: boolean; label?: string }>(), {
  tone: 'neutral',
  label: undefined,
})

const tones: Record<Tone | 'idle', string> = {
  neutral: 'bg-subtle text-subtle',
  idle: 'bg-idle text-idle',
  brand: 'bg-brand text-brand',
  success: 'bg-success text-success',
  warning: 'bg-warning text-warning',
  error: 'bg-error text-error',
  info: 'bg-info text-info',
}
</script>

<template>
  <span
    class="inline-block size-2 shrink-0 rounded-full"
    :class="[tones[tone], pulse && 'animate-pulse-dot']"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
  />
</template>
