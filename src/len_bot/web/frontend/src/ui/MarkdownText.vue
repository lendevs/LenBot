<script setup lang="ts">
import { computed } from 'vue'
import { blocks } from './markdown'
import MarkdownSpans from './MarkdownSpans.vue'

/** Model-written Markdown as plain elements; see `markdown.ts` for the subset. */
const props = withDefaults(defineProps<{ text: string; size?: 'sm' | 'md' }>(), {
  size: undefined,
})

const sizes = {
  sm: 'text-sm leading-6',
  md: 'text-base leading-relaxed',
} as const
const parsed = computed(() => blocks(props.text))
const headingClass = (level: number) => {
  if (level === 1) return 'mt-2 text-lg font-semibold tracking-tight text-ink first:mt-0'
  if (level === 2) return 'mt-1.5 text-base font-semibold tracking-tight text-ink first:mt-0'
  if (level === 3) return 'mt-1 text-sm font-semibold text-ink first:mt-0'
  return 'mt-0.5 text-xs font-semibold tracking-wide text-ink-2 first:mt-0'
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-2.5 break-words" :class="size && sizes[size]">
    <template v-for="(block, index) in parsed" :key="index">
      <p v-if="block.kind === 'heading'" :class="headingClass(block.level)">
        <MarkdownSpans :spans="block.spans" />
      </p>
      <blockquote
        v-else-if="block.kind === 'quote'"
        class="border-l-2 border-line-strong bg-fill/50 py-1.5 pr-3 pl-3.5 text-ink-2"
      >
        <template v-for="(line, row) in block.lines" :key="row">
          <br v-if="row" />
          <MarkdownSpans :spans="line" />
        </template>
      </blockquote>
      <hr v-else-if="block.kind === 'rule'" class="border-line" />
      <pre
        v-else-if="block.kind === 'code'"
        class="overflow-x-auto rounded-md border border-line bg-code px-3 py-2.5 font-mono text-xs leading-5 text-ink-2 scrollbar-thin"
      ><code>{{ block.text }}</code></pre>
      <div v-else-if="block.kind === 'table'" class="overflow-x-auto scrollbar-thin">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-line text-left text-xs text-muted">
              <th
                v-for="(cell, at) in block.head"
                :key="at"
                scope="col"
                class="py-2 pr-3 font-medium last:pr-0"
              >
                <MarkdownSpans :spans="cell" />
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="(row, at) in block.rows" :key="at">
              <td v-for="(cell, column) in row" :key="column" class="py-2 pr-3 align-top tabular last:pr-0">
                <MarkdownSpans :spans="cell" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <ul v-else-if="block.kind === 'list'" class="flex flex-col gap-1">
        <li
          v-for="(item, at) in block.items"
          :key="at"
          class="flex gap-2"
          :style="{ paddingLeft: `${item.depth * 1.25}rem` }"
        >
          <span class="shrink-0 text-muted tabular select-none" aria-hidden="true">{{ item.marker }}</span>
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
