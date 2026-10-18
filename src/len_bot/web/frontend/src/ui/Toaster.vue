<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  ToastAction,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastRoot,
  ToastTitle,
  ToastViewport,
} from 'reka-ui'
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from '@lucide/vue'
import { removeToast, toasts, type ToastTone } from './toast'

/** Rendered once by the app shell. */
const { t } = useI18n()
const icons = { success: CircleCheck, error: CircleAlert, info: Info, warning: TriangleAlert }
const tones: Record<ToastTone, string> = {
  success: 'text-success',
  error: 'text-error',
  info: 'text-info',
  warning: 'text-warning',
}

function closed(id: number, open: boolean) {
  if (open) return
  const item = toasts.value.find((entry) => entry.id === id)
  if (item) item.open = false
  setTimeout(() => removeToast(id), 240)
}
</script>

<template>
  <ToastProvider swipe-direction="right" :label="t('ui.toast.region')">
    <ToastRoot
      v-for="item in toasts"
      :key="item.id"
      :open="item.open"
      :duration="item.duration"
      :type="item.tone === 'error' ? 'foreground' : 'background'"
      class="ui-toast flex items-start gap-3 rounded-lg border border-line bg-surface-raised py-3 pr-2 pl-3.5 text-ink shadow-float"
      @update:open="(open) => closed(item.id, open)"
    >
      <component
        :is="icons[item.tone]"
        :size="18"
        class="mt-px shrink-0"
        :class="tones[item.tone]"
        aria-hidden="true"
      />
      <div class="min-w-0 flex-1">
        <ToastTitle class="text-sm font-semibold">{{ item.title }}</ToastTitle>
        <ToastDescription
          v-if="item.detail"
          class="mt-0.5 text-sm break-words whitespace-pre-line text-muted"
        >
          {{ item.detail }}
        </ToastDescription>
      </div>
      <ToastAction
        v-if="item.action"
        :alt-text="item.action.label"
        class="h-7 shrink-0 cursor-pointer rounded-md px-2 text-sm font-semibold text-primary hover:bg-primary-bg focus-visible:focus-ring"
        @click="item.action.run()"
      >
        {{ item.action.label }}
      </ToastAction>
      <ToastClose
        class="inline-flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-subtle hover:bg-hover hover:text-ink focus-visible:focus-ring"
        :aria-label="t('ui.toast.dismiss')"
      >
        <X :size="15" aria-hidden="true" />
      </ToastClose>
    </ToastRoot>
    <ToastViewport
      class="fixed right-0 bottom-0 z-(--z-toast) m-0 flex w-full max-w-[400px] list-none flex-col gap-2 p-4 outline-none max-sm:max-w-none"
    />
  </ToastProvider>
</template>
