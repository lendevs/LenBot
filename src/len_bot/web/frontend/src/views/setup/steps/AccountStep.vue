<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import { useStepErrors, useWizard } from '../wizard'

const { t } = useI18n()
const { draft, container } = useWizard()
const error = useStepErrors('account')
</script>

<template>
  <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
    <Field :label="t('setup.account.username')" :error="error('username')" required wide>
      <Input v-model="draft.username" autocomplete="username" maxlength="64" />
    </Field>
    <Field :label="t('setup.account.password')" :error="error('password')" required>
      <Input
        v-model="draft.password"
        type="password"
        autocomplete="new-password"
        :placeholder="t('setup.account.passwordRule')"
      />
    </Field>
    <Field :label="t('setup.account.passwordAgain')" :error="error('passwordAgain')" required>
      <Input v-model="draft.passwordAgain" type="password" autocomplete="new-password" />
    </Field>
    <Field :label="t('setup.account.port')" :error="error('port')" required>
      <NumberInput
        v-model="draft.port"
        :min="1"
        :max="65535"
        :steppers="false"
        :format-options="{ useGrouping: false }"
        :disabled="container"
      />
    </Field>
  </div>
</template>
