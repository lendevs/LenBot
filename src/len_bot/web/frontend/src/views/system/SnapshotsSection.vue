<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Trash2 } from '@lucide/vue'
import { keys } from '../../api/query'
import { systemApi, type UpdateSnapshot } from '../../api/system'
import { formatBytes, formatDateTime } from '../../i18n/format'
import Badge from '../../ui/Badge.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import IconButton from '../../ui/IconButton.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

/** The deployment's update snapshots under backups/, read from the update controller. */
const { t } = useI18n()
const queryClient = useQueryClient()
const snapshots = useQuery({
  queryKey: keys.system.snapshots(),
  queryFn: ({ signal }) => systemApi.snapshots(signal),
})
const items = computed(() => snapshots.data.value ?? [])
const total = computed(() => items.value.reduce((sum, item) => sum + item.bytes, 0))

const remove = useMutation({
  mutationFn: (name: string) => systemApi.deleteSnapshot(name),
  onSuccess: (left) => {
    queryClient.setQueryData(keys.system.snapshots(), left)
    // Deleting the restorable snapshot also removes the restore action from the controller status.
    void queryClient.invalidateQueries({ queryKey: keys.system.updates(), exact: true })
    toast.success(t('system.updates.snapshots.deleted'))
  },
  onError: (error) =>
    toast.error(t('system.updates.snapshots.deleteFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
async function ask(item: UpdateSnapshot) {
  const sure = await confirm({
    title: t('system.updates.snapshots.deleteTitle', { time: formatDateTime(item.created) }),
    message: item.restore
      ? t('system.updates.snapshots.deleteRestore')
      : t('system.updates.snapshots.deleteMessage'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) remove.mutate(item.name)
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
    <Skeleton v-if="snapshots.isPending.value" :lines="3" />
    <ErrorNote
      v-else-if="snapshots.isError.value"
      :title="t('system.updates.snapshots.readFailed')"
      :error="snapshots.error.value"
      :retry="snapshots.refetch"
    />
    <p v-else-if="!items.length" class="text-sm text-muted">{{ t('system.updates.snapshots.none') }}</p>
    <ol v-else class="flex list-none flex-col divide-y divide-line">
      <li
        v-for="item in items"
        :key="item.name"
        class="flex items-center justify-between gap-3 py-3 first:pt-1 last:pb-0"
      >
        <div class="flex min-w-0 flex-col gap-0.5">
          <span class="flex flex-wrap items-center gap-2 text-sm font-medium text-ink tabular">
            {{ formatDateTime(item.created) }}
            <Badge v-if="item.restore" tone="brand">{{ t('system.updates.snapshots.restore') }}</Badge>
            <Badge v-if="!item.complete" tone="warning">
              {{ t('system.updates.snapshots.incomplete') }}
            </Badge>
          </span>
          <span class="truncate text-xs text-muted tabular">
            {{ formatBytes(item.bytes) }} ·
            <span class="font-mono">{{ item.name }}</span>
          </span>
        </div>
        <IconButton
          :icon="Trash2"
          :label="t('common.delete')"
          variant="danger-ghost"
          :loading="remove.isPending.value && remove.variables.value === item.name"
          :disabled="remove.isPending.value"
          @click="ask(item)"
        />
      </li>
    </ol>
  </section>
</template>
