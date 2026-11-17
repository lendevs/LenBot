<script setup lang="ts">
import { computed, type Component } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import Spinner from './Spinner.vue'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost'
export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg'

const props = withDefaults(
  defineProps<{
    variant?: ButtonVariant
    size?: ButtonSize
    type?: 'button' | 'submit' | 'reset'
    /** Renders a RouterLink. */
    to?: RouteLocationRaw
    /** Renders a plain link, for downloads and external pages. */
    href?: string
    loading?: boolean
    disabled?: boolean
    block?: boolean
    icon?: Component
    iconRight?: Component
  }>(),
  {
    variant: 'secondary',
    size: 'md',
    type: 'button',
    to: undefined,
    href: undefined,
    icon: undefined,
    iconRight: undefined,
  },
)

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-on-primary shadow-card hover:bg-primary-hover',
  secondary: 'border border-line-strong bg-surface text-ink hover:border-subtle hover:bg-hover',
  ghost: 'bg-transparent text-ink-2 hover:bg-hover hover:text-ink',
  danger: 'bg-error text-on-error shadow-card hover:bg-error-hover',
  'danger-ghost': 'bg-transparent text-error hover:bg-error-bg',
}
const disabledVariants: Record<ButtonVariant, string> = {
  primary: 'bg-fill text-subtle',
  secondary: 'border border-line bg-fill text-subtle',
  ghost: 'bg-transparent text-subtle',
  danger: 'bg-fill text-subtle',
  'danger-ghost': 'bg-transparent text-subtle',
}
const sizes: Record<ButtonSize, string> = {
  xs: 'h-7 gap-1 px-2.5 text-xs',
  sm: 'h-8 gap-1.5 px-3 text-sm',
  md: 'h-9 gap-2 px-3.5 text-sm',
  lg: 'h-10 gap-2 px-4 text-base',
}
const iconSize = computed(() => ({ xs: 14, sm: 16, md: 16, lg: 18 })[props.size])
const inactive = computed(() => props.disabled || props.loading)
const classes = computed(() => [
  'link-plain relative inline-flex shrink-0 cursor-pointer items-center justify-center rounded-md font-semibold whitespace-nowrap select-none',
  'transition-[background-color,border-color,color,box-shadow,opacity,transform] duration-150 ease-out',
  'focus-visible:focus-ring pointer-coarse:min-h-11',
  !inactive.value && 'active:translate-y-px',
  props.loading && 'pointer-events-none opacity-80',
  props.disabled && !props.loading && 'pointer-events-none cursor-not-allowed',
  props.disabled && !props.loading ? disabledVariants[props.variant] : variants[props.variant],
  sizes[props.size],
  props.block && 'w-full',
])
</script>

<template>
  <RouterLink v-if="to !== undefined && !inactive" :to="to" :class="classes">
    <component :is="icon" v-if="icon" :size="iconSize" class="shrink-0" aria-hidden="true" />
    <slot />
    <component :is="iconRight" v-if="iconRight" :size="iconSize" class="shrink-0" aria-hidden="true" />
  </RouterLink>
  <a v-else-if="href !== undefined && !inactive" :href="href" :class="classes">
    <component :is="icon" v-if="icon" :size="iconSize" class="shrink-0" aria-hidden="true" />
    <slot />
    <component :is="iconRight" v-if="iconRight" :size="iconSize" class="shrink-0" aria-hidden="true" />
  </a>
  <button
    v-else
    :type="type"
    :class="classes"
    :disabled="inactive"
    :aria-disabled="inactive || undefined"
    :aria-busy="loading || undefined"
  >
    <Spinner v-if="loading && (icon || !iconRight)" :size="iconSize" />
    <component :is="icon" v-else-if="icon" :size="iconSize" class="shrink-0" aria-hidden="true" />
    <slot />
    <Spinner v-if="loading && !icon && iconRight" :size="iconSize" />
    <component :is="iconRight" v-else-if="iconRight" :size="iconSize" class="shrink-0" aria-hidden="true" />
  </button>
</template>
