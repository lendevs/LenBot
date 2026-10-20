<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { memoryApi } from '../../../api/memory'
import { keys } from '../../../api/query'
import { formatDateTime } from '../../../i18n/format'
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
    <p v-else-if="!history.data.value?.changes.length" class="text-sm text-muted">{{ t('groups.memory.history.none') }}</p>
    <ol v-else class="flex list-none flex-col divide-y divide-line">
      <li v-for="(change, index) in history.data.value.changes" :key="index" class="flex flex-col gap-1.5 py-3 first:pt-0">
        <p class="text-sm font-medium text-ink">
          {{ action(change.action) }}
          <span class="ml-1 text-xs font-normal text-subtle tabular">{{ formatDateTime(change.changed_at, { timeZone }) }}</span>
        </p>
        <p class="text-sm break-words text-ink-2">{{ change.reason }}</p>
        <details>
          <summary class="cursor-pointer text-xs font-medium text-muted hover:text-ink">
            {{ t('groups.memory.history.diff') }}
          </summary>
          <div class="mt-2 grid gap-2 sm:grid-cols-2">
            <CodeBlock :code="change.before ?? t('common.none')" :max-lines="12" :label="t('groups.memory.history.before')" />
            <CodeBlock :code="change.after ?? t('common.none')" :max-lines="12" :label="t('groups.memory.history.after')" />
          </div>
        </details>
      </li>
    </ol>
  </Dialog>
</template>
