<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { Zap } from '@lucide/vue'
import { modelsApi, type ChatBinding } from '../../api/models'
import { developerDetails } from '../../composables/useDeveloperMode'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import RawRecord from '../groups/tasks/RawRecord.vue'
import ModelName from './ModelName.vue'
import { candidateOf, chatRoles, hasKey, newBinding, useForm, type ProviderRow } from './form'

/** Read a provider's models and send a test request; with `binding`, the test uses that role's settings. */
const props = defineProps<{ row: ProviderRow; binding?: ChatBinding }>()

const { t } = useI18n()
const form = useForm()
const ready = computed(() => hasKey(props.row) && Boolean(props.row.base_url.trim()))
const chat = computed(() => form.supports(props.row, 'mind'))
const embedding = computed(() => !chat.value && form.supports(props.row, 'embedding'))
const models = computed(() => form.catalog.value[props.row.id] ?? [])
const catalogLoading = computed(() => Boolean(form.catalogLoading.value[props.row.id]))
const catalogError = computed(() => form.catalogError.value[props.row.id])

const testModel = ref('')
// Start from a model this provider already serves, so the test can run without typing one.
const boundModel = computed(() => {
  const value = form.draft.value
  if (!value) return ''
  const bindings = embedding.value
    ? [value.memory_embedding, ...Object.values(value.learning_embeddings)]
    : chatRoles.map((role) => value.roles[role])
  return bindings.find((item) => item?.provider === props.row.id && item.model)?.model ?? ''
})
watch(
  boundModel,
  (value) => {
    if (!testModel.value) testModel.value = value
  },
  { immediate: true },
)
const kind = ref<'text' | 'tools'>('text')
const kinds = computed(() => [
  { value: 'text' as const, label: t('models.probe.text') },
  { value: 'tools' as const, label: t('models.probe.tools') },
])
const model = computed(() => (props.binding ? props.binding.model : testModel.value).trim())
const bindingValid = computed(() => {
  const b = props.binding
  if (!b) return true
  return (
    b.context_window_tokens !== null &&
    b.context_window_tokens > 0 &&
    b.max_output_tokens !== null &&
    b.max_output_tokens > 0 &&
    b.max_output_tokens < b.context_window_tokens &&
    b.timeout_seconds !== null &&
    b.timeout_seconds > 0 &&
    !(b.reasoning_effort !== null && b.thinking_budget_tokens !== null)
  )
})

const probe = useMutation({
  mutationFn: () => {
    const providerAlias = props.row.alias.trim() || 'probe'
    return embedding.value
      ? modelsApi.probe(
          candidateOf(props.row),
          { provider: providerAlias, model: model.value, dimensions: null },
          'embedding',
        )
      : modelsApi.probe(
          candidateOf(props.row),
          props.binding
            ? { ...props.binding, provider: providerAlias }
            : {
                ...newBinding(providerAlias),
                model: model.value,
                context_window_tokens: 8192,
                temperature: null,
              },
          kind.value,
        )
  },
})
// A result belongs to the provider, model and settings it was asked with.
watch(
  () => JSON.stringify([candidateOf(props.row), props.binding, testModel.value, kind.value]),
  () => probe.reset(),
)
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-if="!binding && (chat || embedding)" class="grid gap-4 sm:grid-cols-2">
      <Field :label="t('models.probe.model')">
        <ModelName
          v-model="testModel"
          :models="models"
          can-refresh
          :refresh-disabled="!ready"
          :refreshing="catalogLoading"
          @refresh="form.loadCatalog(row.id)"
        />
      </Field>
      <Field v-if="chat" :label="t('models.probe.kind')">
        <SegmentedControl v-model="kind" :options="kinds" block :label="t('models.probe.kind')" />
      </Field>
    </div>
    <div v-if="chat || embedding" class="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        :icon="Zap"
        :loading="probe.isPending.value"
        :disabled="!ready || !model || !bindingValid"
        @click="probe.mutate()"
      >
        {{ binding ? t(`models.probe.run.${kind}`) : t('models.probe.run.any') }}
      </Button>
      <SegmentedControl
        v-if="binding"
        v-model="kind"
        :options="kinds"
        size="sm"
        :label="t('models.probe.kind')"
      />
    </div>
    <ErrorNote v-if="catalogError" :title="t('models.probe.listFailed')" :error="catalogError" />
    <ErrorNote v-if="probe.isError.value" :title="t('models.probe.failed')" :error="probe.error.value" />
    <div
      v-if="probe.data.value"
      role="status"
      class="flex animate-fade flex-col gap-1 rounded-lg bg-success-bg px-3.5 py-2.5 text-sm text-success"
    >
      <span class="font-medium">
        {{ t(`models.probe.passed.${probe.data.value.kind}`, { model: probe.data.value.model ?? model }) }}
      </span>
      <span class="min-w-0 break-words whitespace-pre-wrap text-ink-2">{{ probe.data.value.text }}</span>
    </div>
    <RawRecord
      v-if="developerDetails && probe.data.value?.usage"
      :label="t('models.probe.usage')"
      :code="JSON.stringify(probe.data.value.usage, null, 2)"
    />
  </div>
</template>
