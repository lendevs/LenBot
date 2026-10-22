<script setup lang="ts">
import { computed, type Component } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import Spinner from './Spinner.vue'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

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
  ghost: 'bg-transparent text-ink hover:bg-hover',
  danger: 'bg-error text-page shadow-card hover:brightness-95',
  'danger-ghost': 'bg-transparent text-error hover:bg-error-bg',
}
const sizes: Record<ButtonSize, string> = {
  sm: 'h-8 gap-1.5 px-3 text-sm',
  md: 'h-9 gap-2 px-3.5 text-sm',
  lg: 'h-10 gap-2 px-4 text-base',
}
const iconSize = computed(() => (props.size === 'lg' ? 18 : 16))
const inactive = computed(() => props.disabled || props.loading)
const classes = computed(() => [
  'link-plain relative inline-flex shrink-0 cursor-pointer items-center justify-center rounded-md font-semibold whitespace-nowrap select-none',
  'transition-[background-color,border-color,color,box-shadow,filter,transform] duration-150 ease-out',
  'focus-visible:focus-ring active:translate-y-px pointer-coarse:min-h-11',
  'aria-disabled:pointer-events-none aria-disabled:opacity-50',
  variants[props.variant],
  sizes[props.size],
  props.block && 'w-full',
])
</script>

<template>
  <RouterLink v-if="to !== undefined && !inactive" :to="to" :class="classes">
    <component :is="icon" v-if="icon" :size="iconSize" aria-hidden="true" />
    <slot />
    <component :is="iconRight" v-if="iconRight" :size="iconSize" aria-hidden="true" />
  </RouterLink>
  <a v-else-if="href !== undefined && !inactive" :href="href" :class="classes">
    <component :is="icon" v-if="icon" :size="iconSize" aria-hidden="true" />
    <slot />
    <component :is="iconRight" v-if="iconRight" :size="iconSize" aria-hidden="true" />
  </a>
  <button
    v-else
    :type="type"
    :class="classes"
    :disabled="inactive"
    :aria-disabled="inactive || undefined"
    :aria-busy="loading || undefined"
  >
    <Spinner v-if="loading" :size="iconSize" />
    <component :is="icon" v-else-if="icon" :size="iconSize" aria-hidden="true" />
    <slot />
    <component :is="iconRight" v-if="iconRight && !loading" :size="iconSize" aria-hidden="true" />
  </button>
</template>
