<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
} from 'reka-ui'
import Button from './Button.vue'

const open = defineModel<boolean>('open', { default: false })
withDefaults(
  defineProps<{
    title: string
    /** What cannot be undone; the panel only explains consequences here. */
    message?: string
    confirmLabel?: string
    cancelLabel?: string
    tone?: 'danger' | 'primary'
    busy?: boolean
  }>(),
  { message: undefined, confirmLabel: undefined, cancelLabel: undefined, tone: 'danger' },
)
const emit = defineEmits<{ confirm: [] }>()
const { t } = useI18n()
</script>

<template>
  <AlertDialogRoot v-model:open="open">
    <AlertDialogPortal>
      <AlertDialogOverlay class="ui-overlay fixed inset-0 z-(--z-dialog) bg-overlay backdrop-blur-[2px]" />
      <AlertDialogContent
        class="ui-dialog fixed top-1/2 left-1/2 z-(--z-dialog) w-[calc(100vw-32px)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl bg-surface-raised p-6 text-ink shadow-dialog outline-none"
        @escape-key-down="(event) => busy && event.preventDefault()"
      >
        <AlertDialogTitle class="text-lg font-semibold">{{ title }}</AlertDialogTitle>
        <AlertDialogDescription v-if="message" class="mt-2 text-base text-muted">
          {{ message }}
        </AlertDialogDescription>
        <div class="mt-6 flex justify-end gap-2">
          <AlertDialogCancel as-child>
            <Button :disabled="busy">{{ cancelLabel ?? t('common.cancel') }}</Button>
          </AlertDialogCancel>
          <Button :variant="tone" :loading="busy" @click="emit('confirm')">
            {{ confirmLabel ?? t('common.confirm') }}
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
