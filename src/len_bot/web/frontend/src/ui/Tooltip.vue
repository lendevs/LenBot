<script setup lang="ts">
import { TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger } from 'reka-ui'

withDefaults(
  defineProps<{
    text: string
    side?: 'top' | 'right' | 'bottom' | 'left'
    /** Keyboard shortcut shown after the text. */
    shortcut?: string
    disabled?: boolean
  }>(),
  { side: 'top', shortcut: undefined },
)
</script>

<template>
  <slot v-if="disabled" />
  <TooltipRoot v-else>
    <TooltipTrigger as-child><slot /></TooltipTrigger>
    <TooltipPortal>
      <TooltipContent
        :side="side"
        :side-offset="6"
        class="ui-pop z-(--z-popover) flex max-w-72 items-center gap-2 rounded-sm bg-ink px-2 py-1 text-xs font-medium text-page shadow-float"
      >
        {{ text }}
        <kbd v-if="shortcut" class="font-sans text-[11px] opacity-70">{{ shortcut }}</kbd>
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
