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
import { floatingPanel, menuItem } from './styles'

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
        :class="[floatingPanel, 'min-w-44 p-1']"
      >
        <template v-for="(entry, index) in items" :key="index">
          <DropdownMenuSeparator v-if="entry.type === 'separator'" class="-mx-1 my-1 h-px bg-line" />
          <DropdownMenuLabel v-else-if="entry.type === 'label'" class="px-2 pt-1.5 pb-1 text-xs text-subtle">
            {{ entry.label }}
          </DropdownMenuLabel>
          <DropdownMenuItem
            v-else
            :disabled="entry.disabled"
            :class="[menuItem, entry.danger && 'text-error data-highlighted:bg-error-bg']"
            @select="entry.select"
          >
            <component
              :is="entry.icon"
              v-if="entry.icon"
              :size="15"
              :class="entry.danger ? 'text-error' : 'text-muted'"
              aria-hidden="true"
            />
            <span class="truncate">{{ entry.label }}</span>
            <span v-if="entry.shortcut" class="ml-auto pl-4 text-xs text-subtle">{{ entry.shortcut }}</span>
          </DropdownMenuItem>
        </template>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
