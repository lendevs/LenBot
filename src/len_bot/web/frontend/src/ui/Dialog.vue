<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { DialogClose, DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import { X } from '@lucide/vue'

const open = defineModel<boolean>('open', { default: false })
withDefaults(
  defineProps<{
    title: string
    size?: 'sm' | 'md' | 'lg' | 'xl'
    /** While busy the dialog cannot be dismissed, so a running save is not abandoned half way. */
    busy?: boolean
  }>(),
  { size: 'md' },
)

const { t } = useI18n()
const widths = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' }
</script>

<template>
  <DialogRoot v-model:open="open">
    <slot name="trigger" />
    <DialogPortal>
      <DialogOverlay class="ui-overlay fixed inset-0 z-(--z-dialog) bg-overlay backdrop-blur-[2px]" />
      <DialogContent
        :aria-describedby="undefined"
        class="ui-dialog fixed top-1/2 left-1/2 z-(--z-dialog) flex max-h-[min(88dvh,860px)] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl bg-surface-raised text-ink shadow-dialog outline-none"
        :class="widths[size]"
        @escape-key-down="(event) => busy && event.preventDefault()"
        @pointer-down-outside="(event) => busy && event.preventDefault()"
        @interact-outside="(event) => busy && event.preventDefault()"
      >
        <header class="flex shrink-0 items-start justify-between gap-4 px-6 pt-5 pb-3">
          <DialogTitle class="pt-0.5 text-lg font-semibold">{{ title }}</DialogTitle>
          <slot name="header" />
          <DialogClose
            :disabled="busy"
            class="-mr-2 inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring disabled:opacity-40"
            :aria-label="t('ui.dialog.close')"
          >
            <X :size="18" aria-hidden="true" />
          </DialogClose>
        </header>
        <div class="min-h-0 flex-1 overflow-y-auto px-6 pb-5 scrollbar-thin">
          <slot />
        </div>
        <footer
          v-if="$slots.footer"
          class="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-line px-6 py-3.5"
        >
          <slot name="footer" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
