<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ChevronDown, CircleCheck, X } from '@lucide/vue'
import Button from '../../ui/Button.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import IconButton from '../../ui/IconButton.vue'
import Skeleton from '../../ui/Skeleton.vue'
import StatusDot from '../../ui/StatusDot.vue'
import type { Attention } from './attention'

defineProps<{ items: Attention[]; loading: boolean }>()
const emit = defineEmits<{ dismiss: [item: Attention] }>()

const { t } = useI18n()
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <h2 class="flex items-center gap-2 text-base font-semibold text-ink">
      {{ t('overview.todo.title') }}
      <span
        v-if="items.length"
        class="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-error-bg px-1.5 text-xs font-semibold text-error tabular"
      >
        {{ items.length }}
      </span>
    </h2>
    <div v-if="loading" class="flex flex-col divide-y divide-line border-y border-line" aria-hidden="true">
      <div v-for="n in 2" :key="n" class="flex items-center gap-3 py-3">
        <Skeleton width="8px" height="8px" rounded="rounded-full" />
        <Skeleton width="68%" height="15px" />
      </div>
    </div>
    <p
      v-else-if="!items.length"
      class="flex items-center gap-2 border-t border-line pt-3.5 text-sm text-ink-2"
    >
      <CircleCheck :size="16" class="shrink-0 text-success" aria-hidden="true" />
      <span>{{ t('overview.todo.none') }}</span>
    </p>
    <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
      <li v-for="item in items" :key="item.key" class="py-3">
        <details v-if="item.children" class="group">
          <summary
            class="flex cursor-pointer list-none items-center gap-3 rounded-sm focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
          >
            <StatusDot :tone="item.tone" />
            <span class="min-w-0 flex-1 text-sm text-ink tabular">{{ item.text }}</span>
            <span class="shrink-0 text-xs text-muted tabular">
              {{ t('overview.todo.groups', { n: item.children.length }) }}
            </span>
            <ChevronDown
              :size="16"
              class="shrink-0 text-muted transition-transform duration-200 group-open:rotate-180"
              aria-hidden="true"
            />
            <IconButton
              :icon="X"
              :label="t('overview.todo.dismiss')"
              size="sm"
              @click.stop.prevent="emit('dismiss', item)"
            />
          </summary>
          <ul class="mt-2.5 flex list-none flex-col gap-1.5 border-l-2 border-line pl-3.5">
            <li v-for="child in item.children" :key="child.key" class="flex min-w-0 flex-col gap-1.5 py-1">
              <div class="flex min-w-0 items-center gap-3">
                <span class="min-w-0 flex-1 text-sm text-ink-2 tabular">{{ child.text }}</span>
                <Button v-if="child.to" size="sm" variant="ghost" :to="child.to">{{ child.action }}</Button>
                <IconButton
                  :icon="X"
                  :label="t('overview.todo.dismiss')"
                  size="sm"
                  @click="emit('dismiss', child)"
                />
              </div>
              <details v-if="child.error">
                <summary
                  class="cursor-pointer rounded-sm text-xs text-muted hover:text-ink focus-visible:focus-ring"
                >
                  {{ t('common.rawError') }}
                </summary>
                <div class="mt-1.5">
                  <CodeBlock :code="child.error" :max-lines="8" />
                </div>
              </details>
            </li>
          </ul>
        </details>
        <div v-else class="flex min-w-0 flex-col gap-1.5">
          <div class="flex min-w-0 items-center gap-3">
            <StatusDot :tone="item.tone" />
            <span class="min-w-0 flex-1 text-sm text-ink tabular">{{ item.text }}</span>
            <Button v-if="item.to" size="sm" :to="item.to">{{ item.action }}</Button>
            <IconButton
              :icon="X"
              :label="t('overview.todo.dismiss')"
              size="sm"
              @click="emit('dismiss', item)"
            />
          </div>
          <details v-if="item.error" class="pl-5">
            <summary
              class="cursor-pointer rounded-sm text-xs text-muted hover:text-ink focus-visible:focus-ring"
            >
              {{ t('common.rawError') }}
            </summary>
            <div class="mt-1.5">
              <CodeBlock :code="item.error" :max-lines="8" />
            </div>
          </details>
        </div>
      </li>
    </ul>
  </section>
</template>
