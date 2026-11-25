<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { RefreshCw } from '@lucide/vue'
import { memoryApi, type MemoryIndex } from '../../../api/memory'
import { keys } from '../../../api/query'
import { readOverview } from '../../../api/hostStore'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import { toast } from '../../../ui/toast'

defineProps<{ index: MemoryIndex; reindexing: boolean }>()

const { t } = useI18n()
const client = useQueryClient()
const rebuild = useMutation({
  mutationFn: () => memoryApi.reindex(),
  onSuccess: (result) => {
    toast.success(t('groups.memory.index.done', { n: result.files }))
    void readOverview()
  },
  onSettled: () => client.invalidateQueries({ queryKey: keys.memory.all() }),
})
const rows = ['stored', 'configured'] as const
</script>

<template>
  <div class="flex max-w-3xl min-w-0 flex-col gap-5">
    <p class="flex flex-wrap items-center gap-2 text-sm text-ink">
      {{ t('groups.memory.index.retrieval') }}
      <Badge :tone="index.retrieval === 'hybrid' ? 'success' : 'neutral'">
        {{
          index.retrieval === 'hybrid' ? t('groups.memory.index.hybrid') : t('groups.memory.index.fulltext')
        }}
      </Badge>
      <Badge v-if="index.needs_rebuild" tone="warning">{{ t('groups.memory.index.mismatch') }}</Badge>
    </p>
    <div class="flex flex-col gap-3 sm:hidden">
      <div
        v-for="row in rows"
        :key="row"
        class="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3.5 text-sm"
      >
        <div class="font-medium text-ink">{{ t(`groups.memory.index.rows.${row}`) }}</div>
        <dl class="grid gap-1.5 text-xs">
          <div class="flex flex-col gap-0.5">
            <dt class="text-muted">{{ t('groups.memory.index.baseUrl') }}</dt>
            <dd class="font-mono break-all text-ink-2">{{ index[row]?.base_url ?? '—' }}</dd>
          </div>
          <div class="flex flex-col gap-0.5">
            <dt class="text-muted">{{ t('groups.memory.index.model') }}</dt>
            <dd class="font-mono break-all text-ink-2">
              {{ index[row]?.model ?? t('groups.memory.index.noVector') }}
            </dd>
          </div>
          <div class="flex flex-col gap-0.5">
            <dt class="text-muted">{{ t('groups.memory.index.dimensions') }}</dt>
            <dd class="text-ink-2 tabular">
              {{ index[row]?.dimensions ?? t('groups.memory.index.defaultDimensions') }}
            </dd>
          </div>
        </dl>
      </div>
    </div>
    <div class="hidden overflow-x-auto scrollbar-thin sm:block">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs text-muted">
            <th scope="col" class="py-2 pr-4 font-medium">{{ t('groups.memory.index.which') }}</th>
            <th scope="col" class="py-2 pr-4 font-medium">{{ t('groups.memory.index.baseUrl') }}</th>
            <th scope="col" class="py-2 pr-4 font-medium">{{ t('groups.memory.index.model') }}</th>
            <th scope="col" class="py-2 font-medium">{{ t('groups.memory.index.dimensions') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line border-y border-line">
          <tr v-for="row in rows" :key="row">
            <th scope="row" class="py-2.5 pr-4 text-left font-medium text-ink whitespace-nowrap">
              {{ t(`groups.memory.index.rows.${row}`) }}
            </th>
            <td class="py-2.5 pr-4 font-mono text-xs break-all text-ink-2">
              {{ index[row]?.base_url ?? '—' }}
            </td>
            <td class="py-2.5 pr-4 font-mono text-xs text-ink-2">
              {{ index[row]?.model ?? t('groups.memory.index.noVector') }}
            </td>
            <td class="py-2.5 text-ink-2 tabular">
              {{ index[row]?.dimensions ?? t('groups.memory.index.defaultDimensions') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div>
      <Button :icon="RefreshCw" :loading="rebuild.isPending.value || reindexing" @click="rebuild.mutate()">
        {{ t('groups.memory.index.rebuild') }}
      </Button>
    </div>
    <ErrorNote
      v-if="rebuild.isError.value"
      :title="t('groups.memory.index.failed')"
      :error="rebuild.error.value"
    />
  </div>
</template>
