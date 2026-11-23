<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { formatNumber } from '../i18n/format'
import type { Tone } from './Badge.vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    height?: number
    tone?: Tone
    /** Fill the area under the line. */
    area?: boolean
    /** Accessible description of the series. */
    label?: string
    /** Optional bucket labels shown on hover (defaults to 00:00..23:00 for 24-bucket series). */
    labels?: string[]
    /** Optional value formatter for the hover tooltip. */
    formatValue?: (value: number) => string
  }>(),
  { height: 32, tone: 'brand', area: true, label: undefined, labels: undefined, formatValue: undefined },
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
const hovered = ref<number | null>(null)
const series = computed(() =>
  props.values.length > 1 ? props.values : [props.values[0] ?? 0, props.values[0] ?? 0],
)
const points = computed(() => {
  const values = series.value
  const rawMax = Math.max(...values)
  const min = Math.min(0, ...values)
  const constantPositive = rawMax > 0 && values.every((item) => item === rawMax)
  const max = constantPositive ? rawMax * 1.75 : rawMax
  const span = max - min || 1
  const pad = 2
  return values.map((value, index): [number, number] => [
    (index / (values.length - 1)) * width,
    pad + (1 - (value - min) / span) * (props.height - pad * 2),
  ])
})
const line = computed(() => points.value.map(([x, y], index) => `${index ? 'L' : 'M'}${x},${y}`).join(' '))
const fill = computed(() => `${line.value} L${width},${props.height} L0,${props.height} Z`)

const activePoint = computed(() => {
  const index = hovered.value
  if (index === null || !props.values.length) return null
  const clamped = Math.min(Math.max(0, index), props.values.length - 1)
  const point = points.value[clamped]
  if (!point) return null
  const value = props.values[clamped] ?? 0
  const period =
    props.labels?.[clamped] ??
    (props.values.length === 24 ? `${String(clamped).padStart(2, '0')}:00` : `#${clamped + 1}`)
  const text = props.formatValue ? props.formatValue(value) : formatNumber(value)
  return { x: point[0], y: point[1], period, text }
})

function onMove(event: MouseEvent) {
  if (!props.values.length) return
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  if (rect.width <= 0) return
  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
  hovered.value = props.values.length === 1 ? 0 : Math.round(ratio * (props.values.length - 1))
}
</script>

<template>
  <div
    class="relative w-full select-none"
    :style="{ color: colors[tone] }"
    @mousemove="onMove"
    @mouseleave="hovered = null"
  >
    <svg
      class="block w-full overflow-visible"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      preserveAspectRatio="none"
      :role="label ? 'img' : undefined"
      :aria-label="label"
      :aria-hidden="label ? undefined : 'true'"
    >
      <defs>
        <linearGradient :id="gradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="currentColor" stop-opacity="0.2" />
          <stop offset="1" stop-color="currentColor" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path v-if="area" :d="fill" :fill="`url(#${gradient})`" />
      <path
        :d="line"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linejoin="round"
        stroke-linecap="round"
        vector-effect="non-scaling-stroke"
      />
    </svg>
    <template v-if="activePoint">
      <span
        class="pointer-events-none absolute top-0 bottom-0 w-px bg-current/35"
        :style="{ left: `${activePoint.x}%` }"
        aria-hidden="true"
      />
      <span
        class="pointer-events-none absolute size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-current ring-2 ring-surface"
        :style="{ left: `${activePoint.x}%`, top: `${activePoint.y}px` }"
        aria-hidden="true"
      />
      <div
        class="pointer-events-none absolute -top-6 z-10 whitespace-nowrap rounded-sm border border-line bg-surface-raised px-1.5 py-0.5 text-2xs font-medium text-ink shadow-card tabular"
        :style="{
          left: `${activePoint.x}%`,
          transform:
            activePoint.x < 18
              ? 'translateX(0%)'
              : activePoint.x > 82
                ? 'translateX(-100%)'
                : 'translateX(-50%)',
        }"
      >
        <span class="text-muted">{{ activePoint.period }}</span>
        <span class="mx-1 text-subtle">·</span>
        <span>{{ activePoint.text }}</span>
      </div>
    </template>
  </div>
</template>
