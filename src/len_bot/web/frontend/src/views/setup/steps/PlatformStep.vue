<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { PlugZap } from '@lucide/vue'
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
const platforms = computed(() => [
  { value: 'onebot' as const, label: t('chatPlatforms.onebot') },
  { value: 'telegram' as const, label: t('chatPlatforms.telegram') },
  { value: 'feishu' as const, label: t('chatPlatforms.feishu') },
  { value: 'later' as const, label: t('setup.platform.later') },
])
const domains = computed(() => [
  { value: 'feishu', label: t('chatPlatforms.feishu') },
  { value: 'lark', label: 'Lark' },
])
const more = ref(Boolean(error('onebotTimeout')))
watch(
  () => error('onebotTimeout'),
  (problem) => problem && (more.value = true),
)

const connect = useMutation({ mutationFn: () => wizard.testPlatform() })
// A result belongs to the settings it was asked with.
watch(wizard.platformSignature, () => connect.reset())

const passed = computed(() =>
  wizard.platformReady.value ? t('setup.platform.connected', { id: wizard.platform.value!.name }) : null,
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
        <SegmentedControl
          v-model="draft.chatPlatform"
          :options="platforms"
          :label="t('setup.platform.connect')"
        />
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
    <div v-else-if="draft.chatPlatform === 'onebot'" class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
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
    <div v-else-if="draft.chatPlatform === 'telegram'" class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('system.connection.telegram.token')" :error="error('telegramToken')" required wide>
        <Input v-model="draft.telegramToken" type="password" autocomplete="off" mono />
      </Field>
      <Field :label="t('system.connection.telegram.proxy')" :error="error('telegramProxy')" wide>
        <Input v-model="draft.telegramProxy" type="url" mono placeholder="http://127.0.0.1:7890" />
      </Field>
    </div>
    <div v-else class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('system.connection.feishu.appId')" :error="error('feishuAppId')" required>
        <Input v-model="draft.feishuAppId" mono placeholder="cli_" />
      </Field>
      <Field :label="t('system.connection.feishu.secret')" :error="error('feishuSecret')" required>
        <Input v-model="draft.feishuSecret" type="password" autocomplete="off" mono />
      </Field>
      <Field :label="t('system.connection.feishu.domain')">
        <Select v-model="draft.feishuDomain" :options="domains" />
      </Field>
    </div>
    <MoreFields
      v-if="draft.chatPlatform === 'onebot'"
      v-model="more"
      :title="t('system.connection.advanced')"
    >
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
  </div>
</template>
