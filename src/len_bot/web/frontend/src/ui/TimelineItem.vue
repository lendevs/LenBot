<script setup lang="ts">
import type { Component } from 'vue'
import Spinner from './Spinner.vue'
import type { Tone } from './Badge.vue'

withDefaults(
  defineProps<{
    title: string
    tone?: Tone
    icon?: Component
    /** The step is still running: the marker spins and the item fades in. */
    running?: boolean
    /** Right-aligned detail such as a duration or token count. */
    meta?: string
    last?: boolean
  }>(),
  { tone: 'neutral', icon: undefined, meta: undefined },
)

const markers: Record<Tone, string> = {
  neutral: 'bg-fill text-muted',
  brand: 'bg-brand-soft text-primary',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning',
  error: 'bg-error-bg text-error',
  info: 'bg-info-bg text-info',
}
</script>

<template>
  <li class="relative flex animate-rise gap-3 pb-4 last:pb-0">
    <span v-if="!last" class="absolute top-7 bottom-0 left-[11.5px] w-px bg-line" aria-hidden="true" />
    <span
      class="relative z-1 mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full ring-4 ring-surface"
      :class="markers[tone]"
    >
      <Spinner v-if="running" :size="13" />
      <component :is="icon" v-else-if="icon" :size="13" aria-hidden="true" />
      <span v-else class="size-1.5 rounded-full bg-current" aria-hidden="true" />
    </span>
    <div class="min-w-0 flex-1">
      <div class="flex min-h-7 items-center gap-2">
        <span class="min-w-0 flex-1 truncate text-sm font-medium text-ink">{{ title }}</span>
        <slot name="meta">
          <span v-if="meta" class="shrink-0 text-xs text-subtle tabular">{{ meta }}</span>
        </slot>
      </div>
      <div v-if="$slots.default" class="mt-1 min-w-0 text-sm text-ink-2"><slot /></div>
    </div>
  </li>
</template>
