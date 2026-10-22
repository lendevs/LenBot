<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { HardDrive } from '@lucide/vue'
import { keys } from '../../../api/query'
import { storageApi, type CleanupOperation } from '../../../api/resources'
import { tasksApi } from '../../../api/tasks'
import { formatBytes, formatDateTime } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { toast } from '../../../ui/toast'
import CleanupDialog from './CleanupDialog.vue'
import { finished } from './labels'

/** Disk use of one task. Reading it scans the task's directories, so it waits for a click. */
const props = defineProps<{ scene: string; taskId: number; timeZone: string }>()
const emit = defineEmits<{ changed: [] }>()

const { t } = useI18n()
const client = useQueryClient()
const asked = ref(false)
const storage = useQuery({
  queryKey: computed(() => keys.tasks.storage(props.scene, props.taskId)),
  queryFn: ({ signal }) => storageApi.task(props.scene, props.taskId, signal),
  enabled: asked,
})
const value = computed(() => storage.data.value)
const temporaryBytes = computed(
  () => value.value?.temporary.reduce((sum, item) => sum + item.file_bytes, 0) ?? 0,
)
const leftover = computed(
  () =>
    value.value &&
    finished(value.value.task.status) &&
    (value.value.task.container || value.value.task.browser_active),
)

const cleaning = ref<CleanupOperation | null>(null)
function changed() {
  void client.invalidateQueries({ queryKey: keys.tasks.space() })
  emit('changed')
}
const close = useMutation({
  mutationFn: () => tasksApi.closeEnvironment(props.scene, props.taskId),
  onSuccess: () => {
    toast.success(t('groups.tasks.browser.closed'))
    changed()
  },
})
async function closeEnvironment() {
  const sure = await confirm({
    title: t('groups.tasks.space.closeTitle'),
    message: t('groups.tasks.space.closeEffect'),
    confirmLabel: t('groups.tasks.space.close'),
  })
  if (sure) close.mutate()
}
</script>

<template>
  <section class="flex flex-col gap-2">
    <h3 class="flex items-center gap-2 text-sm font-medium text-ink">
      <HardDrive :size="16" class="text-subtle" aria-hidden="true" />
      {{ t('groups.tasks.space.title') }}
      <Button
        size="sm"
        variant="ghost"
        class="ml-auto"
        :loading="storage.isFetching.value"
        @click="asked ? storage.refetch() : (asked = true)"
      >
        {{ t(asked ? 'groups.tasks.space.remeasure' : 'groups.tasks.space.measure') }}
      </Button>
    </h3>
    <Skeleton v-if="asked && storage.isPending.value" :lines="3" />
    <ErrorNote
      v-else-if="storage.isError.value"
      :title="t('groups.tasks.space.storageFailed')"
      :error="storage.error.value"
    />
    <template v-else-if="value">
      <p class="text-sm text-ink-2">{{ t(`groups.tasks.space.continuation.${value.continuation}`) }}</p>
      <dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-1 text-sm">
        <template v-for="root in value.roots" :key="root.kind">
          <dt class="text-muted">{{ t(`groups.tasks.space.roots.${root.kind}`) }}</dt>
          <dd class="tabular text-ink">
            {{
              root.usage
                ? t('groups.tasks.space.usage', {
                    files: root.usage.files,
                    size: formatBytes(root.usage.file_bytes),
                    allocated: formatBytes(root.usage.allocated_bytes),
                  })
                : t('groups.tasks.space.noRoot')
            }}
          </dd>
        </template>
        <dt class="text-muted">{{ t('groups.tasks.space.temporary') }}</dt>
        <dd class="tabular text-ink">{{ formatBytes(temporaryBytes) }}</dd>
        <template v-if="value.hard_disk_quota">
          <dt class="text-muted">{{ t('groups.tasks.space.pool') }}</dt>
          <dd class="tabular text-ink">
            {{
              t('groups.tasks.space.poolLeft', {
                available: formatBytes(value.hard_disk_quota.available_bytes),
                limit: formatBytes(value.hard_disk_quota.limit_bytes),
              })
            }}
          </dd>
        </template>
        <template v-if="value.last_cleanup">
          <dt class="text-muted">{{ t('groups.tasks.space.lastCleanup') }}</dt>
          <dd class="text-ink">
            {{ formatDateTime(value.last_cleanup.created, { timeZone }) }} ·
            {{
              t(
                value.last_cleanup.complete === false
                  ? 'groups.tasks.space.incomplete'
                  : 'groups.tasks.space.complete',
              )
            }}
          </dd>
        </template>
      </dl>
      <ErrorNote
        v-if="value.last_cleanup?.error"
        :title="t('groups.tasks.space.lastCleanupFailed')"
        :error="String(value.last_cleanup.error)"
      />
      <div v-if="value.cleanable || leftover" class="flex flex-wrap gap-2">
        <template v-if="value.cleanable">
          <Button size="sm" @click="cleaning = 'temporary'">
            {{ t('groups.tasks.space.cleanup.temporary') }}
          </Button>
          <Button size="sm" variant="danger-ghost" @click="cleaning = 'environment'">
            {{ t('groups.tasks.space.cleanup.environment') }}
          </Button>
        </template>
        <Button v-if="leftover" size="sm" :loading="close.isPending.value" @click="closeEnvironment">
          {{ t('groups.tasks.space.close') }}
        </Button>
      </div>
      <ErrorNote
        v-if="close.isError.value"
        :title="t('groups.tasks.browser.closeFailed')"
        :error="close.error.value"
      />
    </template>
    <CleanupDialog
      v-if="cleaning"
      :scene="scene"
      :ids="[taskId]"
      :operation="cleaning"
      :time-zone="timeZone"
      @done="changed"
      @close="cleaning = null"
    />
  </section>
</template>
