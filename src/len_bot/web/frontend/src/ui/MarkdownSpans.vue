<script setup lang="ts">
import type { Span } from './markdown'

defineProps<{ spans: Span[] }>()
</script>

<template>
  <template v-for="(span, index) in spans" :key="index">
    <strong v-if="span.kind === 'strong'" class="font-semibold text-ink">
      <MarkdownSpans :spans="span.children" />
    </strong>
    <code v-else-if="span.kind === 'code'" class="rounded-sm bg-code px-1 font-mono text-[0.92em]">
      {{ span.text }}
    </code>
    <a
      v-else-if="span.kind === 'link'"
      :href="span.href"
      target="_blank"
      rel="noopener noreferrer"
      class="text-primary hover:underline"
    >
      {{ span.text }}
    </a>
    <template v-else>{{ span.text }}</template>
  </template>
</template>
