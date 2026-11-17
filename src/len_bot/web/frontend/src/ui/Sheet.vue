<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { DialogClose, DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import { X } from '@lucide/vue'

const open = defineModel<boolean>('open', { default: false })
withDefaults(
  defineProps<{
    title: string
    side?: 'right' | 'left' | 'bottom'
    size?: 'sm' | 'md' | 'lg'
    /** The title is kept for screen readers but not drawn, for navigation drawers. */
    hideHeader?: boolean
    busy?: boolean
  }>(),
  { side: 'right', size: 'md' },
)

const { t } = useI18n()
const placement = {
  right: 'inset-y-0 right-0 h-dvh w-full border-l',
  left: 'inset-y-0 left-0 h-dvh w-full border-r',
  bottom: 'inset-x-0 bottom-0 max-h-[88dvh] w-full rounded-t-xl border-t',
}
const widths = { sm: 'sm:max-w-sm', md: 'sm:max-w-md', lg: 'sm:max-w-2xl' }
</script>

<template>
  <DialogRoot v-model:open="open">
    <slot name="trigger" />
    <DialogPortal>
      <DialogOverlay class="ui-overlay fixed inset-0 z-(--z-dialog) bg-overlay backdrop-blur-[2px]" />
      <DialogContent
        :aria-describedby="undefined"
        :data-side="side"
        class="ui-sheet fixed z-(--z-dialog) flex flex-col border-line bg-surface-raised text-ink shadow-dialog outline-none"
        :class="[placement[side], side !== 'bottom' && widths[size]]"
        @escape-key-down="(event) => busy && event.preventDefault()"
        @pointer-down-outside="(event) => busy && event.preventDefault()"
        @interact-outside="(event) => busy && event.preventDefault()"
      >
        <header
          class="flex shrink-0 items-center justify-between gap-4 border-b border-line px-5 py-3.5"
          :class="hideHeader && 'sr-only'"
        >
          <DialogTitle class="min-w-0 truncate text-lg font-semibold text-ink">{{ title }}</DialogTitle>
          <DialogClose
            :disabled="busy"
            class="-mr-1.5 inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring disabled:pointer-events-none disabled:opacity-40"
            :aria-label="t('ui.dialog.close')"
          >
            <X :size="18" aria-hidden="true" />
          </DialogClose>
        </header>
        <div class="min-h-0 flex-1 overflow-y-auto scrollbar-thin" :class="!hideHeader && 'px-5 pt-4 pb-5'">
          <slot />
        </div>
        <footer
          v-if="$slots.footer"
          class="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3"
        >
          <slot name="footer" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
