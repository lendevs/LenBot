<script setup lang="ts">
import { CircleCheck } from '@lucide/vue'
import ErrorNote from '../../ui/ErrorNote.vue'

/** The answer of a test button: a success line, or the error with its original text. */
defineProps<{ passed?: string | null; error?: unknown; failedTitle: string }>()
</script>

<template>
  <p v-if="passed" role="status" class="flex animate-fade items-start gap-2 text-sm text-success">
    <CircleCheck :size="16" class="mt-0.5 shrink-0" aria-hidden="true" />
    <span class="min-w-0 break-words text-ink-2">{{ passed }}</span>
  </p>
  <ErrorNote v-else-if="error" :title="failedTitle" :error="error" />
</template>
