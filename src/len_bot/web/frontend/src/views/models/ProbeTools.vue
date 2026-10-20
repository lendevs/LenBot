<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { List, Zap } from '@lucide/vue'
import { modelsApi, type ChatBinding } from '../../api/models'
import { developerDetails } from '../../composables/useDeveloperMode.js'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import RawRecord from '../groups/tasks/RawRecord.vue'
import ModelName from './ModelName.vue'
import { candidateOf, hasKey, newBinding, useForm, type ProviderRow } from './form'

/** Read a provider's models and send a test request; with `binding`, the test uses that role's settings. */
const props = defineProps<{ row: ProviderRow; binding?: ChatBinding }>()

const { t } = useI18n()
const form = useForm()
const ready = computed(() => hasKey(props.row) && Boolean(props.row.base_url.trim()))
const chat = computed(() => form.supports(props.row, 'mind'))
const embedding = computed(() => !chat.value && form.supports(props.row, 'embedding'))
const models = computed(() => form.catalog.value[props.row.id] ?? [])

const testModel = ref('')
const kind = ref<'text' | 'tools'>('text')
const kinds = computed(() => [
  { value: 'text' as const, label: t('models.probe.text') },
  { value: 'tools' as const, label: t('models.probe.tools') },
])
const model = computed(() => (props.binding ? props.binding.model : testModel.value).trim())

const list = useMutation({
  mutationFn: () => modelsApi.list(candidateOf(props.row)),
  onSuccess: (value) => (form.catalog.value[props.row.id] = value.models),
})
const probe = useMutation({
  mutationFn: () =>
    embedding.value
      ? modelsApi.probe(candidateOf(props.row), { provider: props.row.alias || 'probe', model: model.value, dimensions: null }, 'embedding')
      : modelsApi.probe(
          candidateOf(props.row),
          props.binding
            ? { ...props.binding, provider: props.row.alias || 'probe' }
            : { ...newBinding(props.row.alias || 'probe'), model: model.value, context_window_tokens: 8192, temperature: null },
          kind.value,
        ),
})
// A result belongs to the provider, model and settings it was asked with.
watch(
  () => JSON.stringify([candidateOf(props.row), props.binding, testModel.value, kind.value]),
  () => {
    list.reset()
    probe.reset()
  },
)
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-if="!binding && (chat || embedding)" class="grid gap-4 sm:grid-cols-2">
      <Field :label="t('models.probe.model')">
        <ModelName v-model="testModel" :models="models" />
      </Field>
      <Field v-if="chat" :label="t('models.probe.kind')">
        <SegmentedControl v-model="kind" :options="kinds" block :label="t('models.probe.kind')" />
      </Field>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <Button size="sm" :icon="List" :loading="list.isPending.value" :disabled="!ready" @click="list.mutate()">
        {{ t('models.probe.list') }}
      </Button>
      <Button
        v-if="chat || embedding"
        size="sm"
        :icon="Zap"
        :loading="probe.isPending.value"
        :disabled="!ready || !model"
        @click="probe.mutate()"
      >
        {{ binding ? t(`models.probe.run.${kind}`) : t('models.probe.run.any') }}
      </Button>
      <SegmentedControl v-if="binding" v-model="kind" :options="kinds" size="sm" :label="t('models.probe.kind')" />
      <span v-if="list.isSuccess.value" class="text-xs text-muted">
        {{ t('models.probe.listed', { n: models.length }, models.length) }}
      </span>
    </div>
    <ErrorNote v-if="list.isError.value" :title="t('models.probe.listFailed')" :error="list.error.value" />
    <ErrorNote v-if="probe.isError.value" :title="t('models.probe.failed')" :error="probe.error.value" />
    <div v-if="probe.data.value" role="status" class="flex flex-col gap-1 rounded-md bg-success-bg px-3 py-2 text-sm text-success">
      <span class="font-medium">{{ t(`models.probe.passed.${probe.data.value.kind}`, { model: probe.data.value.model ?? model }) }}</span>
      <span class="whitespace-pre-wrap text-ink-2">{{ probe.data.value.text }}</span>
    </div>
    <RawRecord v-if="developerDetails && probe.data.value?.usage" :label="t('models.probe.usage')" :code="JSON.stringify(probe.data.value.usage, null, 2)" />
  </div>
</template>
