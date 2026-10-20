<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { List, Zap } from '@lucide/vue'
import { setupApi } from '../../../api/setup'
import Button from '../../../ui/Button.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import ModelName from '../../models/ModelName.vue'
import TestResult from '../TestResult.vue'
import { useStepErrors, useWizard } from '../wizard'

const { t } = useI18n()
const wizard = useWizard()
const { draft } = wizard
const error = useStepErrors('vectors')

const modes = computed(() => [
  { value: 'skip' as const, label: t('setup.vectors.skip') },
  { value: 'primary' as const, label: t('setup.vectors.primary'), disabled: !wizard.chatServesVectors.value },
  { value: 'separate' as const, label: t('setup.vectors.separate') },
])

const providerSignature = computed(() => JSON.stringify(wizard.vectorProvider()))
/** Requests go out only for settings that pass the checks; otherwise the step shows what is wrong. */
function checked(fields: string[], run: () => void) {
  const found = wizard.problems('vectors')
  if (fields.some((field) => found[field])) wizard.tried.add('vectors')
  else run()
}
const providerFields = ['vectorBaseUrl', 'vectorKey', 'vectorProxy']
const list = useMutation({
  mutationFn: () => setupApi.models(wizard.vectorProvider()),
  onSuccess: (result) => (wizard.vectorCatalog.value = result.models),
})
watch([providerSignature, () => draft.vectorMode], () => {
  list.reset()
  wizard.vectorCatalog.value = []
})

const probe = useMutation({
  mutationFn: () => setupApi.embedding(wizard.vectorProvider(), wizard.vectorBinding()),
})
watch(
  () => JSON.stringify([wizard.vectorProvider(), wizard.vectorBinding(), draft.vectorMode]),
  () => probe.reset(),
)
const passed = computed(() => {
  const answer = probe.data.value
  return answer ? t('setup.vectors.passed', { model: answer.model, n: answer.dimensions ?? '?' }) : null
})
</script>

<template>
  <div class="flex flex-col gap-5">
    <Field :label="t('setup.vectors.mode')" :info="t('setup.vectors.modeInfo')">
      <div>
        <SegmentedControl v-model="draft.vectorMode" :options="modes" :label="t('setup.vectors.mode')" />
      </div>
    </Field>
    <div v-if="draft.vectorMode === 'separate'" class="grid animate-rise gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('models.providers.url')" :error="error('vectorBaseUrl')" required wide>
        <Input v-model="draft.vectorBaseUrl" type="url" mono placeholder="https://api.example.com/v1" />
      </Field>
      <Field :label="t('models.providers.key')" :error="error('vectorKey')" required>
        <Input v-model="draft.vectorKey" type="password" mono autocomplete="off" />
      </Field>
      <Field :label="t('models.providers.proxy')" :error="error('vectorProxy')">
        <Input v-model="draft.vectorProxy" type="url" mono placeholder="http://127.0.0.1:7890" />
      </Field>
    </div>
    <div v-if="draft.vectorMode !== 'skip'" class="flex animate-rise flex-col gap-5">
      <div class="flex flex-col gap-3">
        <div>
          <Button size="sm" :icon="List" :loading="list.isPending.value" @click="checked(providerFields, () => list.mutate())">
            {{ t('models.probe.list') }}
          </Button>
        </div>
        <TestResult
          :passed="list.data.value ? t('models.probe.listed', { n: list.data.value.models.length }) : null"
          :error="list.error.value"
          :failed-title="t('models.probe.listFailed')"
        />
      </div>
      <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
        <Field :label="t('setup.vectors.model')" :error="error('vectorModel')" required>
          <ModelName v-model="draft.vectorModel" :models="wizard.vectorCatalog.value" />
        </Field>
        <Field :label="t('setup.vectors.dimensions')">
          <NumberInput v-model="draft.vectorDimensions" :min="1" :steppers="false" :placeholder="t('setup.vectors.defaultDimensions')" />
        </Field>
      </div>
      <div class="flex flex-col gap-3 border-t border-line pt-5">
        <div>
          <Button
            :icon="Zap"
            :loading="probe.isPending.value"
            @click="checked([...providerFields, 'vectorModel'], () => probe.mutate())"
          >
            {{ t('setup.vectors.test') }}
          </Button>
        </div>
        <TestResult :passed="passed" :error="probe.error.value" :failed-title="t('models.probe.failed')" />
      </div>
    </div>
  </div>
</template>
