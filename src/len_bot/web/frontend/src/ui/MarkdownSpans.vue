<script setup lang="ts">
import type { Span } from './markdown'

defineProps<{ spans: Span[] }>()
</script>

<template>
  <template v-for="(span, index) in spans" :key="index">
    <strong v-if="span.kind === 'strong'" class="font-semibold text-ink">
      <MarkdownSpans :spans="span.children" />
    </strong>
    <code
      v-else-if="span.kind === 'code'"
      class="rounded-xs border border-line bg-code px-1 py-px font-mono text-[0.9em] text-ink-2"
    >
      {{ span.text }}
    </code>
    <a
      v-else-if="span.kind === 'link'"
      :href="span.href"
      target="_blank"
      rel="noopener noreferrer"
      class="font-medium text-primary underline-offset-2 hover:underline"
    >
      {{ span.text }}
    </a>
    <template v-else>{{ span.text }}</template>
  </template>
</template>
