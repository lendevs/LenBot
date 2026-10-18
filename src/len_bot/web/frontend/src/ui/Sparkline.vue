<script setup lang="ts">
import { computed, useId } from 'vue'
import type { Tone } from './Badge.vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    height?: number
    tone?: Tone
    /** Fill the area under the line. */
    area?: boolean
    /** Accessible description, such as 最近 24 小时消息数. */
    label?: string
  }>(),
  { height: 32, tone: 'brand', area: true, label: undefined },
)

const gradient = useId()
const colors: Record<Tone, string> = {
  neutral: 'var(--subtle)',
  brand: 'var(--brand)',
  success: 'var(--success)',
  warning: 'var(--warning)',
  error: 'var(--error)',
  info: 'var(--info)',
}
const width = 100
const points = computed(() => {
  const values = props.values.length > 1 ? props.values : [props.values[0] ?? 0, props.values[0] ?? 0]
  const max = Math.max(...values)
  const min = Math.min(0, ...values)
  const span = max - min || 1
  const pad = 2
  return values.map((value, index) => [
    (index / (values.length - 1)) * width,
    pad + (1 - (value - min) / span) * (props.height - pad * 2),
  ])
})
const line = computed(() => points.value.map(([x, y], index) => `${index ? 'L' : 'M'}${x},${y}`).join(' '))
const fill = computed(() => `${line.value} L${width},${props.height} L0,${props.height} Z`)
</script>

<template>
  <svg
    class="block w-full overflow-visible"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    preserveAspectRatio="none"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
    :style="{ color: colors[tone] }"
  >
    <defs>
      <linearGradient :id="gradient" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="currentColor" stop-opacity="0.22" />
        <stop offset="1" stop-color="currentColor" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path v-if="area" :d="fill" :fill="`url(#${gradient})`" />
    <path
      :d="line"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linejoin="round"
      stroke-linecap="round"
      vector-effect="non-scaling-stroke"
    />
  </svg>
</template>
