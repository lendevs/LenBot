<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { History, Trash2 } from '@lucide/vue'
import { keys } from '../../api/query'
import { systemApi, type UpdateSnapshot, type UpdateState } from '../../api/system'
import { formatBytes, formatDateTime } from '../../i18n/format'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import IconButton from '../../ui/IconButton.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

/** Snapshots the launcher took before each update; restoring one restarts into its version. */
const props = defineProps<{ items: UpdateSnapshot[]; busy: boolean }>()
const emit = defineEmits<{ restarting: [] }>()

const { t } = useI18n()
const queryClient = useQueryClient()
const total = computed(() => props.items.reduce((sum, item) => sum + item.bytes, 0))
const updated = (state: UpdateState) => queryClient.setQueryData(keys.system.updates(), state)
const failed = (title: string) => (error: unknown) =>
  toast.error(title, { detail: describeError(error, t('ui.error.network')).message })

const remove = useMutation({
  mutationFn: (name: string) => systemApi.deleteSnapshot(name),
  onSuccess: (state) => {
    updated(state)
    toast.success(t('system.updates.snapshots.deleted'))
  },
  onError: failed(t('system.updates.snapshots.deleteFailed')),
})
const restore = useMutation({
  mutationFn: (name: string) => systemApi.restoreSnapshot(name),
  onSuccess: (state) => {
    updated(state)
    emit('restarting')
  },
  onError: failed(t('system.updates.snapshots.restoreFailed')),
})

async function askDelete(item: UpdateSnapshot) {
  const sure = await confirm({
    title: t('system.updates.snapshots.deleteTitle', { time: formatDateTime(item.created_at) }),
    message: t('system.updates.snapshots.deleteMessage'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) remove.mutate(item.name)
}
async function askRestore(item: UpdateSnapshot) {
  const sure = await confirm({
    title: t('system.updates.snapshots.restoreTitle', { version: item.version }),
    message: t('system.updates.snapshots.restoreMessage', { time: formatDateTime(item.created_at) }),
    confirmLabel: t('system.updates.snapshots.restore'),
    tone: 'danger',
  })
  if (sure) restore.mutate(item.name)
}
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <h3 class="text-base font-semibold">{{ t('system.updates.snapshots.title') }}</h3>
      <span v-if="items.length" class="text-sm text-muted tabular">
        {{ t('system.updates.snapshots.total', { n: items.length, size: formatBytes(total) }) }}
      </span>
    </header>
    <p v-if="!items.length" class="text-sm text-muted">{{ t('system.updates.snapshots.none') }}</p>
    <ol v-else class="flex list-none flex-col divide-y divide-line">
      <li v-for="item in items" :key="item.name" class="flex items-center gap-3 py-3 first:pt-1 last:pb-0">
        <div class="flex min-w-0 flex-1 flex-col gap-0.5">
          <span class="flex flex-wrap items-center gap-2 text-sm font-medium text-ink tabular">
            {{ formatDateTime(item.created_at) }}
            <Badge>v{{ item.version }}</Badge>
          </span>
          <span class="text-xs text-muted tabular">{{ formatBytes(item.bytes) }}</span>
        </div>
        <Button
          size="sm"
          :icon="History"
          :disabled="busy || !item.restorable || restore.isPending.value"
          :loading="restore.isPending.value && restore.variables.value === item.name"
          :title="
            item.restorable ? undefined : t('system.updates.snapshots.unavailable', { version: item.version })
          "
          @click="askRestore(item)"
        >
          {{ t('system.updates.snapshots.restore') }}
        </Button>
        <IconButton
          :icon="Trash2"
          size="sm"
          :label="t('common.delete')"
          :disabled="busy || remove.isPending.value"
          @click="askDelete(item)"
        />
      </li>
    </ol>
  </section>
</template>
