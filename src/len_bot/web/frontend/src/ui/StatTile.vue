<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { TransitionPresets, usePreferredReducedMotion, useTransition } from '@vueuse/core'
import { currentLocale } from '../i18n'
import Skeleton from './Skeleton.vue'
import Sparkline from './Sparkline.vue'
import type { Tone } from './Badge.vue'

const props = withDefaults(
  defineProps<{
    label: string
    value: number | string | null
    unit?: string
    /** Change against the previous period, shown with an arrow. */
    delta?: number | null
    trend?: number[]
    tone?: Tone
    loading?: boolean
    formatOptions?: Intl.NumberFormatOptions
  }>(),
  {
    unit: undefined,
    delta: null,
    trend: undefined,
    tone: 'brand',
    formatOptions: () => ({ maximumFractionDigits: 1 }),
  },
)

const motion = usePreferredReducedMotion()
const target = ref(typeof props.value === 'number' ? props.value : 0)
watch(
  () => props.value,
  (value) => {
    if (typeof value === 'number') target.value = value
  },
)
/** Numbers count up to their new value instead of jumping. */
const shown = useTransition(target, {
  duration: 600,
  transition: TransitionPresets.easeOutCubic,
  disabled: computed(() => motion.value === 'reduce'),
})
const formatter = computed(() => new Intl.NumberFormat(currentLocale.value, props.formatOptions))
const text = computed(() => {
  if (props.value === null) return '—'
  if (typeof props.value === 'string') return props.value
  return formatter.value.format(shown.value)
})
const deltaText = computed(() =>
  props.delta === null
    ? null
    : new Intl.NumberFormat(currentLocale.value, {
        signDisplay: 'exceptZero',
        maximumFractionDigits: 1,
      }).format(props.delta),
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5">
    <span class="truncate text-sm text-muted">{{ label }}</span>
    <Skeleton v-if="loading" width="56%" height="28px" />
    <div v-else class="flex min-w-0 items-baseline gap-1.5">
      <span class="truncate text-2xl font-semibold tracking-tight text-ink tabular">{{ text }}</span>
      <span v-if="unit && value !== null" class="text-sm text-muted">{{ unit }}</span>
      <span
        v-if="deltaText"
        class="ml-auto shrink-0 text-xs font-medium tabular"
        :class="(delta ?? 0) > 0 ? 'text-success' : (delta ?? 0) < 0 ? 'text-error' : 'text-subtle'"
      >
        {{ deltaText }}
      </span>
    </div>
    <Sparkline v-if="trend && !loading" :values="trend" :tone="tone" :height="28" class="mt-1" />
  </div>
</template>
