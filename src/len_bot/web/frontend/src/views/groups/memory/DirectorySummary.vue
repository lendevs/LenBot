<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RefreshCw } from '@lucide/vue'
import { memoryApi, type MemoryScope } from '../../../api/memory'
import { keys } from '../../../api/query'
import { formatDateTime } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import MarkdownText from '../../../ui/MarkdownText.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string; scope: MemoryScope; path: string; timeZone: string }>()

const { t } = useI18n()
const client = useQueryClient()
const queryKey = computed(() => keys.memory.summary(props.scene, props.scope, props.path))
const summary = useQuery({
  queryKey,
  queryFn: ({ signal }) => memoryApi.summary(props.scene, props.scope, props.path, signal),
})
const data = computed(() => summary.data.value)
const latestFailedRun = computed(() => {
  const runs = data.value?.runs ?? []
  if (!runs.length || runs[0]?.status === 'complete') return null
  return runs.find((run) => run.error) ?? null
})
const portrait = computed(() => props.path === '' && props.scope === 'scene')
const generate = useMutation({
  mutationFn: () => memoryApi.summarize(props.scene, props.scope, props.path),
  onSuccess: (result) => {
    if (result.skipped) toast.info(result.skipped)
    else if (result.complete === false) toast.error(t('groups.memory.summary.partial'))
    else toast.success(t('groups.memory.summary.done'))
  },
  onError: (error) =>
    toast.error(t('groups.memory.summary.failed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => client.invalidateQueries({ queryKey: queryKey.value }),
})
</script>

<template>
  <Skeleton v-if="summary.isPending.value" :lines="4" />
  <ErrorNote
    v-else-if="summary.isError.value"
    :title="t('groups.memory.readFailed')"
    :error="summary.error.value"
    :retry="summary.refetch"
  />
  <section
    v-else-if="data && (data.enabled || data.summary.abstract !== null || latestFailedRun)"
    class="flex max-w-3xl flex-col gap-3"
  >
    <header class="flex min-h-8 flex-wrap items-center gap-3 border-b border-line pb-3">
      <h3 class="min-w-0 flex-1 text-base font-semibold text-ink">
        {{ portrait ? t('groups.memory.summary.portrait') : t('groups.memory.summary.directory') }}
      </h3>
      <Button
        v-if="data.enabled"
        size="sm"
        variant="ghost"
        :icon="RefreshCw"
        :loading="generate.isPending.value"
        @click="generate.mutate()"
      >
        {{ t('groups.memory.summary.regenerate') }}
      </Button>
    </header>
    <ErrorNote
      v-if="latestFailedRun"
      :title="
        t('groups.memory.summary.runFailed', {
          time: formatDateTime(latestFailedRun.started, { timeZone }),
        })
      "
      :error="latestFailedRun.error"
    />
    <p v-if="data.summary.abstract === null" class="text-sm text-muted">
      {{ t('groups.memory.summary.none') }}
    </p>
    <template v-else>
      <p class="text-base leading-6 font-medium break-words text-ink">{{ data.summary.abstract }}</p>
      <MarkdownText
        v-if="data.summary.overview"
        :text="data.summary.overview"
        class="text-sm leading-6 text-ink-2"
      />
      <p v-if="data.summary.generated_at" class="text-xs text-subtle tabular">
        {{
          t('groups.memory.summary.generated', {
            time: formatDateTime(data.summary.generated_at, { timeZone }),
          })
        }}
        <template v-if="data.summary.changed_after !== null">{{ t('groups.memory.summary.stale') }}</template>
      </p>
    </template>
  </section>
  <p v-else class="text-sm text-muted">{{ t('groups.memory.pick') }}</p>
</template>
