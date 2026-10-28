<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { MessageCirclePlus, Square } from '@lucide/vue'
import { keys } from '../../api/query'
import { trialSource, trialsApi, type TrialInfo } from '../../api/trials'
import { developerDetails } from '../../composables/useDeveloperMode'
import { formatDateTime } from '../../i18n/format'
import type { HostScene } from '../../api/host'
import { host } from '../../api/hostStore'
import { groupLabel } from '../../layouts/shell/scenes'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import RawRecord from '../groups/tasks/RawRecord.vue'
import StartForm from './StartForm.vue'
import ChatPanel from './chat/ChatPanel.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const trials = useQuery({ queryKey: keys.trials(), queryFn: ({ signal }) => trialsApi.list(signal) })
const items = computed(() => [...(trials.data.value?.items ?? [])].sort((a, b) => b.created - a.created))
const active = computed(() => items.value.find((item) => item.active) ?? null)
const selected = computed(
  () => items.value.find((item) => item.id === route.query.trial) ?? active.value ?? items.value[0] ?? null,
)
const pick = (id: string) => void router.replace({ query: { ...route.query, trial: id } })
/** Times follow the group's clock, as the chat window does. */
const zone = (scene: string) =>
  ((host.state?.scenes ?? []) as HostScene[]).find((item) => item.scene === scene)?.timezone
const records = computed(() =>
  items.value.map((item) => ({
    value: item.id,
    label: `${groupLabel(item.scene)} · ${formatDateTime(item.created, { timeZone: zone(item.scene) })}${item.active ? ` · ${t('playground.running')}` : ''}`,
  })),
)
const text = (key: string) =>
  typeof route.query[key] === 'string' ? (route.query[key] as string) : undefined

/** A new test is offered while none runs; the form opens on its own when there is nothing to show. */
const starting = ref(false)
watch(active, (value) => {
  if (value) starting.value = false
})
const showForm = computed(
  () => !active.value && (starting.value || !selected.value || Boolean(text('scene') || text('persona'))),
)

async function started(trial: TrialInfo) {
  starting.value = false
  await client.invalidateQueries({ queryKey: keys.trials() })
  void router.replace({ query: { trial: trial.id } })
}
const stop = useMutation({
  mutationFn: (id: string) => trialsApi.stop(id),
  onSuccess: () => {
    toast.success(t('playground.stopped'))
    void client.invalidateQueries({ queryKey: keys.trials() })
  },
  onError: (error) =>
    toast.error(t('playground.stopFailed'), { detail: describeError(error, t('ui.error.network')).message }),
})
async function end() {
  const sure = await confirm({
    title: t('playground.stopTitle'),
    message: t('playground.stopMessage'),
    confirmLabel: t('playground.stop'),
  })
  if (sure && active.value) stop.mutate(active.value.id)
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <Skeleton v-if="trials.isPending.value" :lines="6" />
    <ErrorNote
      v-else-if="trials.isError.value"
      :title="t('playground.listFailed')"
      :error="trials.error.value"
      :retry="trials.refetch"
    />
    <template v-else>
      <div v-if="items.length" class="flex flex-wrap items-center gap-3">
        <div class="w-full sm:w-80">
          <Select
            :model-value="selected?.id"
            :options="records"
            :aria-label="t('playground.records')"
            @update:model-value="(value) => value && pick(value)"
          />
        </div>
        <div class="ml-auto flex items-center gap-2">
          <Button v-if="active" :icon="Square" :loading="stop.isPending.value" @click="end">
            {{ t('playground.stop') }}
          </Button>
          <Button v-else-if="!showForm" variant="primary" :icon="MessageCirclePlus" @click="starting = true">
            {{ t('playground.new') }}
          </Button>
        </div>
      </div>
      <StartForm v-if="showForm" :scene="text('scene')" :persona="text('persona')" @started="started" />
      <template v-if="selected && !(showForm && !selected.active)">
        <div class="flex flex-wrap items-center gap-2 text-sm text-ink-2">
          <span>{{ t('playground.persona', { name: selected.persona }) }}</span>
          <Badge v-if="selected.persona_source === 'draft'" tone="info">{{ t('playground.draft') }}</Badge>
          <Badge v-if="selected.memory_plugin">
            {{ t('playground.nativeMemory', { name: selected.memory_plugin }) }}
          </Badge>
          <Badge v-if="!selected.active">{{ t('playground.ended') }}</Badge>
        </div>
        <details v-if="selected.context.length" class="text-sm">
          <summary class="cursor-pointer text-muted hover:text-ink">
            {{ t('playground.context', { n: selected.context.length }, selected.context.length) }}
          </summary>
          <CodeBlock :code="selected.context.join('\n\n')" :max-lines="12" class="mt-2" />
        </details>
        <ChatPanel :key="selected.id" :source="trialSource(selected.id)" />
        <RawRecord
          v-if="developerDetails"
          :label="t('playground.scope')"
          :code="{
            memory: selected.memory,
            models: selected.models,
            excluded_tools: selected.excluded_tools,
            root: selected.root,
            draft_path: selected.draft_path,
          }"
        />
      </template>
    </template>
  </div>
</template>
