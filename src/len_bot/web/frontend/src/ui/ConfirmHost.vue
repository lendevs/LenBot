<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ConfirmDialog from './ConfirmDialog.vue'
import { answerConfirm, pendingConfirm, type ConfirmRequest } from './confirm'

/** Rendered once by the app shell; shows the questions asked through confirm(). */
const shown = ref<ConfirmRequest>({ title: '' })
watch(pendingConfirm, (value) => {
  if (value) shown.value = value
})
const open = computed({
  get: () => pendingConfirm.value !== null,
  set: (value: boolean) => {
    if (!value) answerConfirm(false)
  },
})
</script>

<template>
  <ConfirmDialog
    v-model:open="open"
    :title="shown.title"
    :message="shown.message"
    :confirm-label="shown.confirmLabel"
    :tone="shown.tone"
    @confirm="answerConfirm(true)"
  />
</template>
