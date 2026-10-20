<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { http } from '../../../api/client'
import { savedCandidate, type EmbeddingBinding, type SavedProvider } from '../../../api/models'
import { keys } from '../../../api/query'
import { settingsApi, type SettingsSnapshot } from '../../../api/settings'
import { readPendingRestart } from '../../../api/hostStore'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import EmbeddingField from './EmbeddingField.vue'

/** `memory/service.py` LocalMemoryConfig; number fields are null while their input is empty. */
interface Ingest {
  idle_seconds: number | null
  min_messages: number | null
  max_age_seconds: number | null
  batch_size: number | null
  max_steps: number | null
  timeout_seconds: number | null
}
interface MemoryConfig {
  backend: 'local'
  auto_recall: boolean
  recall_budget_chars: number | null
  recall_limit: number | null
  ingest: Ingest | null
  summaries: boolean
  local: { directory: string; embedding: EmbeddingBinding | null }
}

const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const settings = useQuery({ queryKey: keys.host.settings(), queryFn: ({ signal }) => settingsApi.read(signal) })
const saved = computed(() => (settings.data.value?.saved.memory ?? null) as MemoryConfig | null)
const models = computed(
  () =>
    settings.data.value?.saved.models as
      | { providers: Record<string, SavedProvider>; roles: Record<string, unknown> }
      | undefined,
)
/** Embeddings go through OpenAI-compatible providers only. */
const providers = computed(() =>
  Object.entries(models.value?.providers ?? {})
    .filter(([, item]) => ['openai-chat', 'openai-embeddings'].includes(item.api))
    .map(([alias, item]) => ({ id: alias, label: alias, candidate: item.api_key_configured ? savedCandidate(alias, item) : null })),
)
const noMemoryModel = computed(() => Boolean(models.value) && !models.value!.roles.memory)

const draft = ref<MemoryConfig | null>(null)
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const adopt = () => (draft.value = saved.value && copy(saved.value))
const dirty = computed(() => Boolean(settings.data.value) && JSON.stringify(draft.value) !== JSON.stringify(saved.value))
// Saved elsewhere meanwhile: an unchanged draft follows, an edited one is kept.
watch(
  saved,
  (_, previous) => {
    if (previous === undefined || JSON.stringify(draft.value) === JSON.stringify(previous)) adopt()
  },
  { immediate: true },
)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const enabled = computed({
  get: () => draft.value !== null,
  set: (on: boolean) => {
    if (!on) draft.value = null
    else if (saved.value) adopt()
    else
      draft.value = {
        backend: 'local',
        auto_recall: true,
        recall_budget_chars: 1500,
        recall_limit: 5,
        ingest: null,
        summaries: false,
        local: { directory: 'data/memory', embedding: null },
      }
  },
})
const ingestOn = computed({
  get: () => Boolean(draft.value?.ingest),
  set: (on: boolean) => {
    if (draft.value)
      draft.value.ingest = on
        ? { idle_seconds: 1800, min_messages: 50, max_age_seconds: 86400, batch_size: 100, max_steps: 8, timeout_seconds: 180 }
        : null
  },
})
const ingestFields = [
  { key: 'idle_seconds', min: 0, seconds: true },
  { key: 'min_messages', min: 1, max: 100 },
  { key: 'max_age_seconds', min: 1, seconds: true },
  { key: 'batch_size', min: 1, max: 100 },
  { key: 'max_steps', min: 1, max: 30 },
  { key: 'timeout_seconds', min: 1, seconds: true },
] as const

const errors = computed<Record<string, string>>(() => {
  const value = draft.value
  const found: Record<string, string> = {}
  if (!value) return found
  const required = t('common.required')
  if (typeof value.recall_budget_chars !== 'number') found.budget = required
  if (typeof value.recall_limit !== 'number') found.limit = required
  if (!value.local.directory.trim()) found.directory = required
  for (const { key } of ingestFields) if (value.ingest && typeof value.ingest[key] !== 'number') found[key] = required
  const embedding = value.local.embedding
  if (embedding && !embedding.provider) found.embedding = t('groups.memory.settings.noProvider')
  if (embedding && !embedding.model.trim()) found.embedding = required
  return found
})
const problem = computed(() => {
  if (Object.values(errors.value)[0]) return Object.values(errors.value)[0]
  if (draft.value && (draft.value.ingest || draft.value.summaries) && noMemoryModel.value)
    return t('groups.memory.settings.noModel')
  return null
})

const save = useMutation({
  mutationFn: () => http.put<SettingsSnapshot>('/api/host/settings/memory', { memory: draft.value }),
  onSuccess: (snapshot) => {
    client.setQueryData(keys.host.settings(), snapshot)
    void client.invalidateQueries({ queryKey: keys.memory.all() })
    void readPendingRestart()
    toast.success(t('common.saved'))
  },
})
const saveError = computed(() =>
  save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : problem.value,
)
</script>

<template>
  <div class="max-w-3xl">
    <Skeleton v-if="settings.isPending.value" :lines="6" />
    <ErrorNote
      v-else-if="settings.isError.value"
      :title="t('groups.memory.readFailed')"
      :error="settings.error.value"
      :retry="settings.refetch"
    />
    <form v-else class="flex flex-col gap-8" @submit.prevent="save.mutate()">
      <FormSection :title="t('groups.memory.settings.section')">
        <Field :label="t('groups.memory.settings.enabled')" inline wide>
          <Switch v-model="enabled" />
        </Field>
        <template v-if="draft">
          <Field :label="t('groups.memory.settings.autoRecall')" inline wide>
            <Switch v-model="draft.auto_recall" />
          </Field>
          <Field :label="t('groups.memory.settings.summaries')" inline wide>
            <Switch v-model="draft.summaries" />
          </Field>
          <Field :label="t('groups.memory.settings.directory')" :error="errors.directory" wide>
            <Input v-model="draft.local.directory" placeholder="data/memory" mono />
          </Field>
          <Field :label="t('groups.memory.settings.budget')" :error="errors.budget">
            <NumberInput v-model="draft.recall_budget_chars" :min="100" :max="12000" :step="100" :unit="t('groups.memory.settings.chars')" />
          </Field>
          <Field :label="t('groups.memory.settings.limit')" :error="errors.limit">
            <NumberInput v-model="draft.recall_limit" :min="1" :max="20" />
          </Field>
        </template>
      </FormSection>
      <FormSection v-if="draft" :title="t('groups.memory.settings.ingest')">
        <template #actions>
          <Switch v-model="ingestOn" :aria-label="t('groups.memory.settings.ingest')" />
        </template>
        <template v-if="draft.ingest">
          <Field
            v-for="item in ingestFields"
            :key="item.key"
            :label="t(`groups.memory.settings.ingestFields.${item.key}`)"
            :error="errors[item.key]"
          >
            <NumberInput
              v-model="draft.ingest[item.key]"
              :min="item.min"
              :max="'max' in item ? item.max : undefined"
              :unit="'seconds' in item ? t('groups.settings.seconds') : undefined"
            />
          </Field>
        </template>
      </FormSection>
      <FormSection v-if="draft" :title="t('groups.memory.settings.vector')" :columns="1">
        <EmbeddingField v-model="draft.local.embedding" :providers="providers" />
        <p v-if="errors.embedding" class="text-xs text-error">{{ errors.embedding }}</p>
      </FormSection>
      <SaveBar
        :dirty="dirty"
        :saving="save.isPending.value"
        :error="saveError"
        :invalid="Object.keys(errors).length > 0"
        @save="save.mutate()"
        @discard="adopt"
      />
    </form>
  </div>
</template>
