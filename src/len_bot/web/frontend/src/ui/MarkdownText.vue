<script setup lang="ts">
import { computed } from 'vue'
import { blocks } from './markdown'
import MarkdownSpans from './MarkdownSpans.vue'

/** Model-written Markdown as plain elements; see `markdown.ts` for the subset. */
const props = defineProps<{ text: string }>()

const parsed = computed(() => blocks(props.text))
</script>

<template>
  <div class="flex min-w-0 flex-col gap-2 break-words">
    <template v-for="(block, index) in parsed" :key="index">
      <p v-if="block.kind === 'heading'" class="font-semibold text-ink">
        <MarkdownSpans :spans="block.spans" />
      </p>
      <hr v-else-if="block.kind === 'rule'" class="border-line" />
      <pre
        v-else-if="block.kind === 'code'"
        class="overflow-x-auto rounded-lg border border-line bg-code px-3 py-2 font-mono text-xs leading-5 scrollbar-thin"
        >{{ block.text }}</pre>
      <ul v-else-if="block.kind === 'list'" class="flex flex-col gap-1">
        <li
          v-for="(item, at) in block.items"
          :key="at"
          class="flex gap-2"
          :style="{ paddingLeft: `${item.depth * 1.25}rem` }"
        >
          <span class="shrink-0 text-muted" aria-hidden="true">{{ item.marker }}</span>
          <span class="min-w-0"><MarkdownSpans :spans="item.spans" /></span>
        </li>
      </ul>
      <p v-else>
        <template v-for="(line, row) in block.lines" :key="row">
          <br v-if="row" />
          <MarkdownSpans :spans="line" />
        </template>
      </p>
    </template>
  </div>
</template>
