<script setup lang="ts">
import type { Component } from 'vue'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from 'reka-ui'
import { floatingPanel, menuItemBase } from './styles'

export type MenuEntry =
  | {
      type?: 'item'
      label: string
      icon?: Component
      shortcut?: string
      danger?: boolean
      disabled?: boolean
      select: () => void
    }
  | { type: 'separator' }
  | { type: 'label'; label: string }

withDefaults(
  defineProps<{ items: MenuEntry[]; align?: 'start' | 'center' | 'end'; side?: 'top' | 'bottom' }>(),
  { align: 'end', side: 'bottom' },
)
// Closing returns focus to the trigger; a listener may preventDefault and move it elsewhere.
const emit = defineEmits<{ closeAutoFocus: [event: Event] }>()
</script>

<template>
  <DropdownMenuRoot :modal="false">
    <DropdownMenuTrigger as-child><slot /></DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent
        :align="align"
        :side="side"
        :side-offset="4"
        :collision-padding="12"
        :class="[
          floatingPanel,
          'max-h-[min(360px,var(--reka-dropdown-menu-content-available-height))] min-w-44 max-w-[calc(100vw-24px)] overflow-y-auto p-1 scrollbar-thin',
        ]"
        @close-auto-focus="emit('closeAutoFocus', $event)"
      >
        <template v-for="(entry, index) in items" :key="index">
          <DropdownMenuSeparator v-if="entry.type === 'separator'" class="-mx-1 my-1 h-px bg-line" />
          <DropdownMenuLabel
            v-else-if="entry.type === 'label'"
            class="truncate px-2.5 pt-1.5 pb-1 text-xs font-medium text-subtle"
          >
            {{ entry.label }}
          </DropdownMenuLabel>
          <DropdownMenuItem
            v-else
            :disabled="entry.disabled"
            :class="[
              menuItemBase,
              'px-2.5',
              entry.danger
                ? 'text-error data-highlighted:bg-error-bg data-highlighted:text-error'
                : 'text-ink-2 data-highlighted:bg-hover data-highlighted:text-ink',
            ]"
            @select="entry.select"
          >
            <component
              :is="entry.icon"
              v-if="entry.icon"
              :size="15"
              class="shrink-0"
              :class="entry.danger ? 'text-error' : 'text-muted'"
              aria-hidden="true"
            />
            <span class="truncate">{{ entry.label }}</span>
            <span v-if="entry.shortcut" class="ml-auto shrink-0 pl-4 text-2xs text-subtle tabular">
              {{ entry.shortcut }}
            </span>
          </DropdownMenuItem>
        </template>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
