<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePreferredReducedMotion } from '@vueuse/core'
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
const reducedMotion = usePreferredReducedMotion()
const icons = { success: CircleCheck, error: CircleAlert, info: Info, warning: TriangleAlert }
const tones: Record<ToastTone, string> = {
  success: 'text-success',
  error: 'text-error',
  info: 'text-info',
  warning: 'text-warning',
}
const timers = new Map<number, ReturnType<typeof setTimeout>>()

function scheduleRemove(id: number) {
  if (timers.has(id)) return
  const delay = reducedMotion.value === 'reduce' ? 40 : 240
  const timer = setTimeout(() => {
    timers.delete(id)
    removeToast(id)
  }, delay)
  timers.set(id, timer)
}

function closed(id: number, open: boolean) {
  if (open) return
  const item = toasts.value.find((entry) => entry.id === id)
  if (item) item.open = false
  scheduleRemove(id)
}

watch(
  () => toasts.value.filter((entry) => !entry.open).map((entry) => entry.id),
  (closingIds) => {
    for (const id of closingIds) scheduleRemove(id)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  for (const timer of timers.values()) clearTimeout(timer)
  timers.clear()
})
</script>

<template>
  <ToastProvider swipe-direction="right" :label="t('ui.toast.region')">
    <TransitionGroup name="ui-list">
      <ToastRoot
        v-for="item in toasts"
        :key="item.id"
        :open="item.open"
        :duration="item.duration"
        :type="item.tone === 'error' ? 'foreground' : 'background'"
        class="ui-toast flex items-start gap-3 rounded-lg border border-line-strong bg-surface-raised py-3 pr-2 pl-3.5 text-ink shadow-float"
        @update:open="(open) => closed(item.id, open)"
      >
        <component
          :is="icons[item.tone]"
          :size="18"
          class="mt-0.5 shrink-0"
          :class="tones[item.tone]"
          aria-hidden="true"
        />
        <div class="min-w-0 flex-1">
          <ToastTitle class="text-sm font-semibold text-ink">{{ item.title }}</ToastTitle>
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
          class="h-7 shrink-0 cursor-pointer rounded-md px-2 text-sm font-semibold text-primary transition-colors hover:bg-primary-bg focus-visible:focus-ring pointer-coarse:min-h-9 pointer-coarse:px-3"
          @click="item.action.run()"
        >
          {{ item.action.label }}
        </ToastAction>
        <ToastClose
          class="inline-flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-subtle transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring pointer-coarse:size-9"
          :aria-label="t('ui.toast.dismiss')"
        >
          <X :size="15" aria-hidden="true" />
        </ToastClose>
      </ToastRoot>
    </TransitionGroup>
    <ToastViewport
      class="fixed right-0 bottom-0 z-(--z-toast) m-0 flex w-full max-w-md list-none flex-col gap-2 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] outline-none sm:p-4 sm:pb-[max(1rem,env(safe-area-inset-bottom))] max-sm:max-w-none"
    />
  </ToastProvider>
</template>
