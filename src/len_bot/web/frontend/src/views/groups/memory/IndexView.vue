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
  <div class="flex max-w-3xl flex-col gap-5">
    <p class="flex flex-wrap items-center gap-2 text-sm text-ink">
      {{ t('groups.memory.index.retrieval') }}
      <Badge :tone="index.retrieval === 'hybrid' ? 'success' : 'neutral'">
        {{ index.retrieval === 'hybrid' ? t('groups.memory.index.hybrid') : t('groups.memory.index.fulltext') }}
      </Badge>
      <Badge v-if="index.needs_rebuild" tone="warning">{{ t('groups.memory.index.mismatch') }}</Badge>
    </p>
    <div class="overflow-x-auto scrollbar-thin">
      <table class="w-full min-w-[480px] text-sm">
        <thead>
          <tr class="text-left text-xs text-muted">
            <th scope="col" class="py-2 pr-3 font-medium">{{ t('groups.memory.index.which') }}</th>
            <th scope="col" class="py-2 pr-3 font-medium">{{ t('groups.memory.index.baseUrl') }}</th>
            <th scope="col" class="py-2 pr-3 font-medium">{{ t('groups.memory.index.model') }}</th>
            <th scope="col" class="py-2 font-medium">{{ t('groups.memory.index.dimensions') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line border-t border-line">
          <tr v-for="row in rows" :key="row">
            <th scope="row" class="py-2 pr-3 text-left font-normal text-ink">{{ t(`groups.memory.index.rows.${row}`) }}</th>
            <td class="py-2 pr-3 font-mono text-xs break-all text-ink-2">{{ index[row]?.base_url ?? '—' }}</td>
            <td class="py-2 pr-3 text-ink-2">{{ index[row]?.model ?? t('groups.memory.index.noVector') }}</td>
            <td class="py-2 text-ink-2 tabular">{{ index[row]?.dimensions ?? t('groups.memory.index.defaultDimensions') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div>
      <Button :icon="RefreshCw" :loading="rebuild.isPending.value || reindexing" @click="rebuild.mutate()">
        {{ t('groups.memory.index.rebuild') }}
      </Button>
    </div>
    <ErrorNote v-if="rebuild.isError.value" :title="t('groups.memory.index.failed')" :error="rebuild.error.value" />
  </div>
</template>
