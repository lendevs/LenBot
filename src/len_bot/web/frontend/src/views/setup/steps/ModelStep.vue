<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { List, Zap } from '@lucide/vue'
import { setupApi } from '../../../api/setup'
import Button from '../../../ui/Button.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'
import ModelName from '../../models/ModelName.vue'
import { useProtocolTitle } from '../../models/protocols'
import MoreFields from '../MoreFields.vue'
import TestResult from '../TestResult.vue'
import { useStepErrors, useWizard } from '../wizard'

const { t } = useI18n()
const wizard = useWizard()
const { draft } = wizard
const error = useStepErrors('model')
const protocolTitle = useProtocolTitle()

const protocolOptions = computed(() =>
  wizard.protocols.value.map((item) => ({ value: item.api, label: protocolTitle(item) })),
)
const protocol = computed({
  get: () => draft.api || undefined,
  set: (api: string | undefined) => api && wizard.chooseProtocol(api),
})
const thinking = computed(() => ['anthropic', 'gemini'].includes(draft.api))
const outputFields = [
  { value: 'max_completion_tokens' as const, label: 'max_completion_tokens' },
  { value: 'max_tokens' as const, label: 'max_tokens' },
]
const kinds = computed(() => [
  { value: 'text' as const, label: t('models.probe.text') },
  { value: 'tools' as const, label: t('models.probe.tools') },
])

const advancedFields = ['inputBudget', 'maxOutput', 'thinkingBudget']
const more = ref(false)
watch(
  () => advancedFields.some((field) => error(field)),
  (wrong) => wrong && (more.value = true),
  { immediate: true },
)

const providerSignature = computed(() => JSON.stringify(wizard.provider()))
/** Requests go out only for settings that pass the checks; otherwise the step shows what is wrong. */
function checked(fields: string[] | null, run: () => void) {
  const found = wizard.problems('model')
  const wrong = fields
    ? fields.some((field) => found[field])
    : Object.keys(found).some((key) => key !== 'probe')
  if (wrong) wizard.tried.add('model')
  else run()
}

const list = useMutation({
  mutationFn: () => setupApi.models(wizard.provider()),
  onSuccess: (result) => (wizard.catalog.value = result.models),
})
watch(providerSignature, () => {
  list.reset()
  wizard.catalog.value = []
})

// A listed model that reports its window fills the context length.
watch(
  () => draft.model,
  (name) => {
    const listed = wizard.catalog.value.find((item) => item.id === name)
    if (listed?.context_window_tokens) draft.contextWindow = listed.context_window_tokens
  },
)

const probe = useMutation({
  mutationFn: async () => {
    const signature = wizard.modelSignature.value
    const result = await setupApi.model(wizard.provider(), wizard.binding(), draft.probeKind)
    return { signature, result }
  },
  onSuccess: ({ signature }) => (wizard.modelPassed.value = signature),
})
watch(wizard.modelSignature, () => probe.reset())

const passed = computed(() => {
  const answer = probe.data.value
  if (wizard.modelReady.value && answer) {
    return t('setup.model.passed', { model: answer.result.model, text: answer.result.text })
  }
  return wizard.modelReady.value ? t('setup.model.passedBefore') : null
})
</script>

<template>
  <div class="flex flex-col gap-5">
    <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('models.providers.api')" :error="error('api')" required wide>
        <Select v-model="protocol" :options="protocolOptions" />
      </Field>
      <Field :label="t('models.providers.url')" :error="error('baseUrl')" required wide>
        <Input v-model="draft.baseUrl" type="url" mono placeholder="https://api.example.com/v1" />
      </Field>
      <Field :label="t('models.providers.key')" :error="error('apiKey')" required>
        <Input v-model="draft.apiKey" type="password" mono autocomplete="off" />
      </Field>
      <Field :label="t('models.providers.proxy')" :error="error('proxy')">
        <Input v-model="draft.proxy" type="url" mono placeholder="http://127.0.0.1:7890" />
      </Field>
      <div class="flex flex-col gap-3 sm:col-span-2">
        <div>
          <Button
            size="sm"
            :icon="List"
            :loading="list.isPending.value"
            @click="checked(['api', 'baseUrl', 'apiKey', 'proxy'], () => list.mutate())"
          >
            {{ t('models.probe.list') }}
          </Button>
        </div>
        <TestResult
          :passed="list.data.value ? t('models.probe.listed', { n: list.data.value.models.length }) : null"
          :error="list.error.value"
          :failed-title="t('models.probe.listFailed')"
        />
      </div>
      <Field :label="t('models.roles.model')" :error="error('model')" required>
        <ModelName
          v-model="draft.model"
          :models="wizard.catalog.value"
          :placeholder="t('setup.model.modelPlaceholder')"
        />
      </Field>
      <Field :label="t('models.roles.context')" :error="error('contextWindow')" required>
        <NumberInput v-model="draft.contextWindow" :min="2048" :steppers="false" unit="tokens" />
      </Field>
    </div>
    <MoreFields v-model="more" :title="t('models.roles.advanced')">
      <Field
        :label="t('setup.model.inputBudget')"
        :error="error('inputBudget')"
        :info="t('setup.model.inputBudgetInfo')"
        required
      >
        <NumberInput v-model="draft.inputBudget" :min="1" :steppers="false" unit="tokens" />
      </Field>
      <Field :label="t('models.roles.maxOutput')" :error="error('maxOutput')" required>
        <NumberInput v-model="draft.maxOutput" :min="1" :steppers="false" unit="tokens" />
      </Field>
      <Field :label="t('models.roles.temperature')">
        <NumberInput
          v-model="draft.temperature"
          :min="0"
          :max="2"
          :step="0.1"
          :snap="false"
          :placeholder="t('models.roles.providerDefault')"
        />
      </Field>
      <Field :label="t('models.roles.effort')">
        <Input v-model="draft.effort" mono :placeholder="t('models.roles.effortDefault')" />
      </Field>
      <Field v-if="thinking" :label="t('models.roles.thinking')" :error="error('thinkingBudget')">
        <NumberInput v-model="draft.thinkingBudget" :min="0" :steppers="false" unit="tokens" />
      </Field>
      <Field v-if="draft.api === 'openai-chat'" :label="t('models.roles.outputField')">
        <Select v-model="draft.outputField" :options="outputFields" />
      </Field>
    </MoreFields>
    <div class="flex flex-col gap-3 border-t border-line pt-5">
      <div class="flex flex-wrap items-center gap-3">
        <SegmentedControl
          v-model="draft.probeKind"
          :options="kinds"
          size="sm"
          :label="t('models.probe.kind')"
        />
        <Button :icon="Zap" :loading="probe.isPending.value" @click="checked(null, () => probe.mutate())">
          {{ t('setup.model.test') }}
        </Button>
      </div>
      <TestResult :passed="passed" :error="probe.error.value" :failed-title="t('models.probe.failed')" />
      <p v-if="!passed && !probe.error.value && error('probe')" class="text-sm text-error" role="alert">
        {{ error('probe') }}
      </p>
    </div>
  </div>
</template>
