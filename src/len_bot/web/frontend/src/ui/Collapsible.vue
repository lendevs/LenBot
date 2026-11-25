<script setup lang="ts">
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from 'reka-ui'
import { ChevronRight } from '@lucide/vue'

/** Animated disclosure built on Reka Collapsible, for folded sections, inline toggles and custom triggers. */
const open = defineModel<boolean>('open', { default: false })
withDefaults(
  defineProps<{
    title?: string
    variant?: 'section' | 'inline' | 'bare'
    /** Optional item count shown after the title. */
    count?: number
    /** Optional status dot shown after the title (`'error'` uses error tone; others use warning). */
    dot?: 'warning' | 'error' | boolean
    disabled?: boolean
    /** Extra classes applied to the inner content wrapper. */
    contentClass?: string
  }>(),
  {
    title: undefined,
    variant: 'section',
    count: undefined,
    dot: false,
    contentClass: undefined,
  },
)
</script>

<template>
  <CollapsibleRoot
    v-model:open="open"
    :disabled="disabled"
    class="min-w-0"
    :class="variant === 'section' && 'border-t border-line pt-4'"
  >
    <template v-if="variant === 'bare' && $slots.trigger">
      <div v-if="$slots.end" class="flex min-w-0 items-center gap-2">
        <CollapsibleTrigger as-child>
          <slot name="trigger" :open="open" />
        </CollapsibleTrigger>
        <div class="ml-auto flex shrink-0 items-center gap-2">
          <slot name="end" />
        </div>
      </div>
      <CollapsibleTrigger v-else as-child>
        <slot name="trigger" :open="open" />
      </CollapsibleTrigger>
    </template>
    <div v-else class="flex min-w-0 items-center gap-2" :class="variant === 'section' && 'w-full'">
      <CollapsibleTrigger
        type="button"
        class="group inline-flex min-w-0 cursor-pointer items-center text-left transition-colors outline-none focus-visible:focus-ring disabled:cursor-not-allowed disabled:opacity-45 pointer-coarse:min-h-9"
        :class="
          variant === 'section'
            ? 'flex-1 gap-1.5 rounded-md py-0.5 text-sm font-medium text-ink-2 hover:text-ink'
            : 'max-w-full gap-1 rounded-sm py-0.5 text-xs font-medium text-muted hover:text-ink'
        "
      >
        <ChevronRight
          :size="variant === 'section' ? 15 : 14"
          class="shrink-0 text-subtle transition-transform duration-(--dur-2) ease-out group-hover:text-ink-2"
          :class="open && 'rotate-90'"
          aria-hidden="true"
        />
        <slot name="trigger" :open="open">
          <span class="truncate">{{ title }}</span>
        </slot>
        <span
          v-if="count !== undefined"
          class="inline-flex h-4.5 min-w-4.5 shrink-0 items-center justify-center rounded-full bg-fill px-1.5 text-2xs font-medium text-muted tabular"
        >
          {{ count }}
        </span>
        <span
          v-if="dot"
          class="size-1.5 shrink-0 rounded-full"
          :class="dot === 'error' ? 'bg-error' : 'bg-warning'"
          aria-hidden="true"
        />
      </CollapsibleTrigger>
      <div v-if="$slots.end" class="ml-auto flex shrink-0 items-center gap-2">
        <slot name="end" />
      </div>
    </div>
    <CollapsibleContent class="ui-collapse">
      <div
        :class="[variant === 'section' ? 'pt-4' : variant === 'inline' ? 'pt-2' : undefined, contentClass]"
      >
        <slot />
      </div>
    </CollapsibleContent>
  </CollapsibleRoot>
</template>
