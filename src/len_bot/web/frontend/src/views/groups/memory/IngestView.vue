<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Play, RotateCw } from '@lucide/vue'
import { memoryApi } from '../../../api/memory'
import { keys } from '../../../api/query'
import { developerDetails } from '../../../composables/useDeveloperMode.js'
import { formatDateTime } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import EmbeddingCalls from './EmbeddingCalls.vue'

const props = defineProps<{ scene: string; timeZone: string }>()

const { t, te } = useI18n()
const client = useQueryClient()
const ingest = useQuery({ queryKey: keys.memory.ingest(), queryFn: ({ signal }) => memoryApi.ingest(signal) })
const current = computed(() => ingest.data.value?.scenes.find((item) => item.scene === props.scene) ?? null)
const latest = computed(() => current.value?.latest ?? null)
const tones: Record<string, Tone> = { running: 'info', complete: 'success', failed: 'error', interrupted: 'warning' }
const status = (value: string) =>
  te(`groups.memory.ingest.statuses.${value}`) ? t(`groups.memory.ingest.statuses.${value}`) : value
const canRun = computed(() => current.value && !current.value.worker_error && (!latest.value || latest.value.status === 'complete'))
const canRetry = computed(
  () =>
    current.value &&
    !current.value.worker_error &&
    latest.value?.backend === 'local' &&
    ['failed', 'interrupted'].includes(latest.value.status),
)
const act = useMutation({
  mutationFn: (action: 'run' | 'retry') => memoryApi.ingestAction(props.scene, action),
  onSuccess: (_, action) => toast.success(t(`groups.memory.ingest.${action}Done`)),
  onError: (error) =>
    toast.error(t('groups.memory.ingest.failed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => client.invalidateQueries({ queryKey: keys.memory.ingest() }),
})
</script>

<template>
  <div class="flex max-w-3xl flex-col gap-6">
    <Skeleton v-if="ingest.isPending.value" :lines="3" />
    <ErrorNote
      v-else-if="ingest.isError.value"
      :title="t('groups.memory.readFailed')"
      :error="ingest.error.value"
      :retry="ingest.refetch"
    />
    <p v-else-if="!ingest.data.value?.enabled" class="text-sm text-muted">{{ t('groups.memory.ingest.off') }}</p>
    <p v-else-if="!current" class="text-sm text-muted">{{ t('groups.memory.ingest.notHere') }}</p>
    <section v-else class="flex flex-col gap-4">
      <ErrorNote v-if="current.worker_error" :title="t('groups.memory.ingest.stopped')" :error="current.worker_error" />
      <div v-if="latest" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span class="text-ink-2">{{ t('groups.memory.ingest.latest') }}</span>
        <Badge :tone="tones[latest.status] ?? 'neutral'">{{ status(latest.status) }}</Badge>
        <span class="text-xs text-subtle tabular">
          {{ formatDateTime(latest.started, { timeZone }) }}
          <template v-if="latest.ended"> – {{ formatDateTime(latest.ended, { timeZone }) }}</template>
        </span>
      </div>
      <p v-else class="text-sm text-muted">{{ t('groups.memory.ingest.never') }}</p>
      <ErrorNote v-if="latest?.error" :title="t('groups.memory.ingest.jobFailed')" :error="latest.error" />
      <div v-if="canRun || canRetry" class="flex gap-2">
        <Button v-if="canRun" :icon="Play" :loading="act.isPending.value" @click="act.mutate('run')">
          {{ t('groups.memory.ingest.run') }}
        </Button>
        <Button v-if="canRetry" variant="primary" :icon="RotateCw" :loading="act.isPending.value" @click="act.mutate('retry')">
          {{ t('groups.memory.ingest.retry') }}
        </Button>
      </div>
    </section>
    <EmbeddingCalls v-if="developerDetails" :scene="scene" :time-zone="timeZone" />
  </div>
</template>
