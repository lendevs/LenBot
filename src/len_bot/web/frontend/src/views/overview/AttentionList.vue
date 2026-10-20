<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ChevronDown, CircleCheck } from '@lucide/vue'
import Button from '../../ui/Button.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import Skeleton from '../../ui/Skeleton.vue'
import StatusDot from '../../ui/StatusDot.vue'
import type { Attention } from './attention'

defineProps<{ items: Attention[]; loading: boolean }>()

const { t } = useI18n()
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <h2 class="flex items-center gap-2 text-base font-semibold">
      {{ t('overview.todo.title') }}
      <span
        v-if="items.length"
        class="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-error-bg px-1.5 text-xs font-semibold text-error tabular"
      >
        {{ items.length }}
      </span>
    </h2>
    <Skeleton v-if="loading" :lines="3" />
    <p v-else-if="!items.length" class="flex items-center gap-2 text-sm font-medium text-success">
      <CircleCheck :size="18" aria-hidden="true" />
      {{ t('overview.todo.none') }}
    </p>
    <ul v-else class="flex list-none flex-col divide-y divide-line rounded-lg border border-line bg-surface">
      <li v-for="item in items" :key="item.key" class="px-4 py-3">
        <details v-if="item.children" class="group">
          <summary class="flex cursor-pointer list-none items-center gap-3 [&::-webkit-details-marker]:hidden">
            <StatusDot :tone="item.tone" />
            <span class="min-w-0 flex-1 text-sm text-ink">{{ item.text }}</span>
            <span class="shrink-0 text-xs text-muted">{{ t('overview.todo.groups', { n: item.children.length }) }}</span>
            <ChevronDown :size="16" class="shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <ul class="mt-2 flex list-none flex-col gap-1 border-l-2 border-line pl-3">
            <li v-for="child in item.children" :key="child.key" class="flex min-w-0 flex-col gap-1.5 py-1">
              <div class="flex min-w-0 items-center gap-3">
                <span class="min-w-0 flex-1 text-sm text-ink-2">{{ child.text }}</span>
                <Button v-if="child.to" size="sm" variant="ghost" :to="child.to">{{ child.action }}</Button>
              </div>
              <details v-if="child.error">
                <summary class="cursor-pointer text-xs text-muted hover:text-ink">{{ t('common.rawError') }}</summary>
                <CodeBlock :code="child.error" :max-lines="8" class="mt-1.5" />
              </details>
            </li>
          </ul>
        </details>
        <div v-else class="flex min-w-0 flex-col gap-1.5">
          <div class="flex min-w-0 items-center gap-3">
            <StatusDot :tone="item.tone" />
            <span class="min-w-0 flex-1 text-sm text-ink">{{ item.text }}</span>
            <Button v-if="item.to" size="sm" :to="item.to">{{ item.action }}</Button>
          </div>
          <details v-if="item.error" class="pl-5">
            <summary class="cursor-pointer text-xs text-muted hover:text-ink">{{ t('common.rawError') }}</summary>
            <CodeBlock :code="item.error" :max-lines="8" class="mt-1.5" />
          </details>
        </div>
      </li>
    </ul>
  </section>
</template>
