<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { PlugZap } from '@lucide/vue'
import { setupApi } from '../../../api/setup'
import Button from '../../../ui/Button.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'
import MoreFields from '../MoreFields.vue'
import TestResult from '../TestResult.vue'
import { useStepErrors, useWizard } from '../wizard'

const { t } = useI18n()
const wizard = useWizard()
const { draft } = wizard
const error = useStepErrors('platform')

const modes = computed(() =>
  (['forward_ws', 'reverse_ws'] as const).map((value) => ({
    value,
    label: t(`system.connection.modes.${value}`),
  })),
)
const connects = computed(() => [
  { value: 'now' as const, label: t('setup.platform.now') },
  { value: 'later' as const, label: t('setup.platform.later') },
])
const deliveries = computed(() => [
  { value: 'simulated' as const, label: t('setup.platform.simulated') },
  { value: 'onebot' as const, label: t('setup.platform.real') },
])
const more = ref(Boolean(error('onebotTimeout')))
watch(
  () => error('onebotTimeout'),
  (problem) => problem && (more.value = true),
)

const connect = useMutation({
  mutationFn: async () => {
    const signature = wizard.platformSignature.value
    const result = await setupApi.platform(wizard.onebot())
    return { signature, botId: result.bot_id, groups: result.groups }
  },
  onSuccess: (result) => (wizard.platform.value = result),
})
// A result belongs to the settings it was asked with.
watch(wizard.platformSignature, () => connect.reset())

const passed = computed(() =>
  wizard.platformReady.value
    ? t('setup.platform.connected', { id: wizard.platform.value!.botId.replace(/^onebot:/, '') })
    : null,
)
/** Tests only settings that pass the checks; otherwise the step shows what is wrong. */
function test() {
  const found = wizard.problems('platform')
  if (Object.keys(found).some((key) => key !== 'connect')) wizard.tried.add('platform')
  else connect.mutate()
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <Field :label="t('setup.platform.connect')">
      <div>
        <SegmentedControl v-model="draft.connect" :options="connects" :label="t('setup.platform.connect')" />
      </div>
    </Field>
    <Field
      v-if="wizard.connectLater.value"
      :label="t('setup.platform.botAccount')"
      :error="error('botAccount')"
      required
    >
      <Input v-model="draft.botAccount" mono inputmode="numeric" placeholder="10001" />
    </Field>
    <div v-if="!wizard.connectLater.value" class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('system.connection.mode')" wide>
        <Select v-model="draft.transport" :options="modes" />
      </Field>
      <Field
        v-if="draft.transport === 'forward_ws'"
        :label="t('system.connection.wsUrl')"
        :error="error('wsUrl')"
        required
        wide
      >
        <Input v-model="draft.wsUrl" type="url" mono />
      </Field>
      <template v-else>
        <Field :label="t('system.connection.listenHost')" :error="error('listenHost')" required>
          <Input v-model="draft.listenHost" mono placeholder="127.0.0.1" />
        </Field>
        <Field :label="t('system.connection.listenPort')" :error="error('listenPort')" required>
          <NumberInput
            v-model="draft.listenPort"
            :min="1"
            :max="65535"
            :steppers="false"
            :format-options="{ useGrouping: false }"
          />
        </Field>
      </template>
      <Field :label="t('system.connection.token')" wide>
        <Input
          v-model="draft.accessToken"
          type="password"
          autocomplete="off"
          :placeholder="t('setup.platform.tokenPlaceholder')"
        />
      </Field>
    </div>
    <MoreFields v-if="!wizard.connectLater.value" v-model="more" :title="t('system.connection.advanced')">
      <Field
        :label="t('system.connection.fields.request_timeout_seconds')"
        :error="error('onebotTimeout')"
        required
      >
        <NumberInput v-model="draft.onebotTimeout" :min="1" :steppers="false" :unit="t('system.seconds')" />
      </Field>
    </MoreFields>
    <div v-if="!wizard.connectLater.value" class="flex flex-col gap-3 border-t border-line pt-5">
      <div>
        <Button :icon="PlugZap" :loading="connect.isPending.value" @click="test">
          {{ t('setup.platform.test') }}
        </Button>
      </div>
      <TestResult :passed="passed" :error="connect.error.value" :failed-title="t('setup.platform.failed')" />
      <p v-if="!passed && !connect.error.value && error('connect')" class="text-sm text-error" role="alert">
        {{ error('connect') }}
      </p>
    </div>
    <Field v-if="!wizard.connectLater.value" :label="t('system.connection.delivery')">
      <div>
        <SegmentedControl
          v-model="draft.delivery"
          :options="deliveries"
          :label="t('system.connection.delivery')"
        />
      </div>
    </Field>
  </div>
</template>
