<script setup lang="ts">
import CodeBlock from '../../../ui/CodeBlock.vue'

defineProps<{ label: string; code: unknown }>()
</script>

<template>
  <details>
    <summary class="cursor-pointer text-xs font-medium text-muted hover:text-ink">{{ label }}</summary>
    <CodeBlock :code="code" :max-lines="12" class="mt-1.5" />
  </details>
</template>
