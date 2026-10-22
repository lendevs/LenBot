<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { List, Zap } from '@lucide/vue'
import { setupApi } from '../../../api/setup'
import Button from '../../../ui/Button.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Switch from '../../../ui/Switch.vue'
import VectorStep from './VectorStep.vue'
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
const presets = computed(() => [
  { value: 'deepseek' as const, label: 'DeepSeek' },
  { value: 'compatible' as const, label: t('setup.model.compatible') },
  { value: 'other' as const, label: t('setup.model.other') },
])
const searchOptions = computed(() => [
  { value: 'deepseek' as const, label: t('capabilities.web.deepseek') },
  { value: 'yahoo' as const, label: 'Yahoo' },
  { value: 'off' as const, label: t('setup.model.searchOff') },
])
/** Replies right after new messages use a low effort; tool results keep the full one. */
const quickReply = computed({
  get: () => draft.quickEffort.trim() !== '',
  set: (on: boolean) => (draft.quickEffort = on ? 'low' : ''),
})
const connectionOptions = computed(() => [
  {
    value: 'primary' as const,
    label: t('setup.model.sameConnection'),
    disabled: !['openai-chat', 'openai-responses'].includes(draft.api),
  },
  { value: 'separate' as const, label: t('setup.model.separateConnection') },
])
const vectorsOpen = ref(false)
watch(
  () => Object.keys(wizard.shown('vectors')).length,
  (n) => {
    if (n) vectorsOpen.value = true
  },
)
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

const advancedFields = [
  'baseUrl',
  'proxy',
  'contextWindow',
  'inputBudget',
  'maxOutput',
  'thinkingBudget',
  'maxSteps',
]
const more = ref(false)
watch(
  () => advancedFields.some((field) => error(field)),
  (wrong) => wrong && (more.value = true),
  { immediate: true },
)

const chatFields = [
  'api',
  'baseUrl',
  'apiKey',
  'proxy',
  'model',
  'contextWindow',
  'maxOutput',
  'inputBudget',
  'thinkingBudget',
]

const providerSignature = computed(() => JSON.stringify(wizard.provider()))
/** Requests go out only for settings that pass the checks; otherwise the step shows what is wrong. */
function checked(fields: string[], run: () => void) {
  const found = wizard.problems('model')
  if (fields.some((field) => found[field])) wizard.tried.add('model')
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
      <Field :label="t('setup.model.preset')" wide>
        <Select
          :model-value="draft.preset"
          :options="presets"
          @update:model-value="(value) => value && wizard.choosePreset(value)"
        />
      </Field>
      <Field
        v-if="draft.preset === 'other'"
        :label="t('models.providers.api')"
        :error="error('api')"
        required
        wide
      >
        <Select v-model="protocol" :options="protocolOptions" />
      </Field>
      <Field
        v-if="draft.preset === 'compatible'"
        :label="t('models.providers.url')"
        :error="error('baseUrl')"
        required
        wide
      >
        <Input v-model="draft.baseUrl" type="url" mono placeholder="https://api.example.com/v1" />
      </Field>
      <Field :label="t('models.providers.key')" :error="error('apiKey')" required>
        <Input v-model="draft.apiKey" type="password" mono autocomplete="off" />
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
      <Field :label="t('models.roles.quickReply')" inline wide><Switch v-model="quickReply" /></Field>
    </div>
    <div class="grid gap-5 border-t border-line pt-5 sm:grid-cols-2">
      <Field :label="t('capabilities.web.provider')">
        <Select v-model="draft.search" :options="searchOptions" />
      </Field>
      <Field
        v-if="draft.search === 'deepseek'"
        :label="t('capabilities.web.connection')"
        :error="error('searchConnection')"
      >
        <Select v-model="draft.searchConnection" :options="connectionOptions" />
      </Field>
      <template v-if="draft.search === 'deepseek' && draft.searchConnection === 'separate'">
        <Field :label="t('models.providers.url')" :error="error('searchBaseUrl')" required wide>
          <Input v-model="draft.searchBaseUrl" type="url" mono />
        </Field>
        <Field :label="t('models.providers.key')" :error="error('searchKey')" required>
          <Input v-model="draft.searchKey" type="password" mono autocomplete="off" />
        </Field>
        <Field :label="t('models.providers.proxy')" :error="error('searchProxy')">
          <Input v-model="draft.searchProxy" type="url" mono placeholder="http://127.0.0.1:7890" />
        </Field>
      </template>
      <Field :label="t('capabilities.web.readOn')" inline wide><Switch v-model="draft.readWeb" /></Field>
    </div>
    <MoreFields v-model="more" :title="t('models.roles.advanced')">
      <Field
        v-if="draft.preset !== 'compatible'"
        :label="t('models.providers.url')"
        :error="error('baseUrl')"
        required
        wide
      >
        <Input v-model="draft.baseUrl" type="url" mono placeholder="https://api.example.com/v1" />
      </Field>
      <Field :label="t('models.providers.proxy')" :error="error('proxy')">
        <Input v-model="draft.proxy" type="url" mono placeholder="http://127.0.0.1:7890" />
      </Field>
      <Field :label="t('models.roles.context')" :error="error('contextWindow')" required>
        <NumberInput v-model="draft.contextWindow" :min="2048" :steppers="false" unit="tokens" />
      </Field>
      <Field :label="t('setup.model.maxSteps')" :error="error('maxSteps')">
        <NumberInput v-model="draft.maxSteps" :min="1" />
      </Field>
      <Field :label="t('setup.model.imageInput')" inline><Switch v-model="draft.imageInput" /></Field>
      <Field :label="t('setup.model.inputBudget')" :error="error('inputBudget')" required>
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
    <MoreFields v-model="vectorsOpen" :title="t('setup.steps.vectors')">
      <div class="sm:col-span-2"><VectorStep /></div>
    </MoreFields>
    <div class="flex flex-col gap-3 border-t border-line pt-5">
      <div class="flex flex-wrap items-center gap-3">
        <SegmentedControl
          v-model="draft.probeKind"
          :options="kinds"
          size="sm"
          :label="t('models.probe.kind')"
        />
        <Button
          :icon="Zap"
          :loading="probe.isPending.value"
          @click="checked(chatFields, () => probe.mutate())"
        >
          {{ t('setup.model.test') }}
        </Button>
      </div>
      <TestResult :passed="passed" :error="probe.error.value" :failed-title="t('models.probe.failed')" />
    </div>
  </div>
</template>
