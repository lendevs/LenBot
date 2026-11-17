<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import CodeBlock from '../../../ui/CodeBlock.vue'

defineProps<{ label: string; code: unknown }>()
</script>

<template>
  <details class="group">
    <summary
      class="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
    >
      <ChevronRight
        :size="13"
        class="shrink-0 transition-transform duration-150 group-open:rotate-90"
        aria-hidden="true"
      />
      {{ label }}
    </summary>
    <CodeBlock :code="code" :max-lines="12" class="mt-1.5" />
  </details>
</template>
