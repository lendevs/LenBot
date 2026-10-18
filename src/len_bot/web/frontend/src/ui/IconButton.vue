<script setup lang="ts">
import { computed, type Component } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import Spinner from './Spinner.vue'
import Tooltip from './Tooltip.vue'

// The root is the Tooltip, so attributes from a parent (menu and popover triggers) go to the button itself.
defineOptions({ inheritAttrs: false })

type Variant = 'ghost' | 'secondary' | 'primary' | 'danger-ghost'
type Size = 'sm' | 'md' | 'lg'

const props = withDefaults(
  defineProps<{
    icon: Component
    /** Accessible name, also shown as the tooltip. */
    label: string
    variant?: Variant
    size?: Size
    to?: RouteLocationRaw
    loading?: boolean
    disabled?: boolean
    /** Highlight a toggle that is currently on. */
    pressed?: boolean
    tooltip?: boolean
    shortcut?: string
  }>(),
  { variant: 'ghost', size: 'md', to: undefined, pressed: undefined, tooltip: true, shortcut: undefined },
)

const variants: Record<Variant, string> = {
  ghost:
    'bg-transparent text-muted hover:bg-hover hover:text-ink aria-pressed:bg-selected aria-pressed:text-primary',
  secondary: 'border border-line-strong bg-surface text-ink hover:bg-hover',
  primary: 'bg-primary text-on-primary hover:bg-primary-hover',
  'danger-ghost': 'bg-transparent text-muted hover:bg-error-bg hover:text-error',
}
const sizes: Record<Size, string> = { sm: 'size-7', md: 'size-8', lg: 'size-10' }
const iconSize = computed(() => ({ sm: 15, md: 17, lg: 19 })[props.size])
const inactive = computed(() => props.disabled || props.loading)
const classes = computed(() => [
  'inline-flex shrink-0 cursor-pointer items-center justify-center rounded-md transition-[background-color,color,transform] duration-150 ease-out',
  'focus-visible:focus-ring active:scale-95 pointer-coarse:size-11',
  'aria-disabled:pointer-events-none aria-disabled:opacity-40',
  variants[props.variant],
  sizes[props.size],
])
</script>

<template>
  <Tooltip :text="label" :shortcut="shortcut" :disabled="!tooltip">
    <RouterLink
      v-if="to !== undefined && !inactive"
      v-bind="$attrs"
      :to="to"
      :class="classes"
      :aria-label="label"
    >
      <component :is="icon" :size="iconSize" aria-hidden="true" />
    </RouterLink>
    <button
      v-else
      v-bind="$attrs"
      type="button"
      :class="classes"
      :aria-label="label"
      :aria-pressed="pressed"
      :disabled="inactive"
      :aria-disabled="inactive || undefined"
      :aria-busy="loading || undefined"
    >
      <Spinner v-if="loading" :size="iconSize" />
      <component :is="icon" v-else :size="iconSize" aria-hidden="true" />
    </button>
  </Tooltip>
</template>
