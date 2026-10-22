<script setup lang="ts">
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import { floatingPanel } from './styles'

const open = defineModel<boolean>('open', { default: false })
withDefaults(
  defineProps<{
    side?: 'top' | 'right' | 'bottom' | 'left'
    align?: 'start' | 'center' | 'end'
    /** Tailwind width class of the panel. */
    width?: string
  }>(),
  { side: 'bottom', align: 'start', width: 'w-72' },
)
</script>

<template>
  <PopoverRoot v-model:open="open">
    <PopoverTrigger as-child><slot name="trigger" /></PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        :side="side"
        :align="align"
        :side-offset="6"
        :collision-padding="12"
        :class="[floatingPanel, width, 'max-w-[calc(100vw-24px)] p-4 outline-none']"
      >
        <slot />
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
