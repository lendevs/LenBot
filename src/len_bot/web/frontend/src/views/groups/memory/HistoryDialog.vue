<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ChevronRight } from '@lucide/vue'
import { memoryApi } from '../../../api/memory'
import { keys } from '../../../api/query'
import { formatDateTime } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'

const props = defineProps<{ scene: string; path: string; timeZone: string }>()
const open = defineModel<boolean>('open', { default: false })

const { t, te } = useI18n()
const history = useQuery({
  queryKey: computed(() => keys.memory.history(props.scene, props.path)),
  queryFn: ({ signal }) => memoryApi.history(props.scene, props.path, signal),
  enabled: open,
})
const action = (value: string) =>
  te(`groups.memory.history.actions.${value}`) ? t(`groups.memory.history.actions.${value}`) : value
const tones: Record<string, Tone> = { write: 'neutral', delete: 'warning', forget: 'error' }
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.memory.history.title', { path })" size="lg">
    <Skeleton v-if="history.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="history.isError.value"
      :title="t('groups.memory.readFailed')"
      :error="history.error.value"
      :retry="history.refetch"
    />
    <p v-else-if="!history.data.value?.changes.length" class="text-sm text-muted">
      {{ t('groups.memory.history.none') }}
    </p>
    <ol v-else class="flex list-none flex-col divide-y divide-line">
      <li
        v-for="(change, index) in history.data.value.changes"
        :key="index"
        class="flex flex-col gap-1.5 py-3.5 first:pt-0 last:pb-0"
      >
        <div class="flex flex-wrap items-center gap-2">
          <Badge :tone="tones[change.action] ?? 'neutral'">{{ action(change.action) }}</Badge>
          <span class="text-xs text-subtle tabular">
            {{ formatDateTime(change.changed_at, { timeZone }) }}
          </span>
        </div>
        <p class="text-sm break-words text-ink-2">{{ change.reason }}</p>
        <details class="group">
          <summary
            class="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
          >
            <ChevronRight
              :size="13"
              class="shrink-0 transition-transform duration-150 group-open:rotate-90"
              aria-hidden="true"
            />
            {{ t('groups.memory.history.diff') }}
          </summary>
          <div class="mt-2 grid gap-2 sm:grid-cols-2">
            <CodeBlock
              :code="change.before ?? t('common.none')"
              :max-lines="12"
              :label="t('groups.memory.history.before')"
            />
            <CodeBlock
              :code="change.after ?? t('common.none')"
              :max-lines="12"
              :label="t('groups.memory.history.after')"
            />
          </div>
        </details>
      </li>
    </ol>
  </Dialog>
</template>
