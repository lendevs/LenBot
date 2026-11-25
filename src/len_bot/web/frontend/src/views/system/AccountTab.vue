<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { systemApi, systemOf, type PanelAccount } from '../../api/system'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import { useSettingsDraft } from './draft'

const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const password = ref('')
const passwordAgain = ref('')
const passwordAgainTouched = ref(false)
const form = useSettingsDraft<PanelAccount | null>({
  pick: (snapshot) => systemOf(snapshot).panel,
  section: 'panel',
  extra: () => password.value !== '' || passwordAgain.value !== '',
  reset: () => {
    password.value = ''
    passwordAgain.value = ''
    passwordAgainTouched.value = false
  },
  save: (value) => systemApi.savePanel({ ...value!, password: password.value || null }),
})
const { settings, draft } = form
watch(form.dirty, (dirty) => emit('dirty', dirty), { immediate: true })
watch([password, passwordAgain], ([next, again]) => {
  form.clearError()
  if (!next && !again) passwordAgainTouched.value = false
})

const passwordMismatch = computed(
  () => Boolean(password.value || passwordAgain.value) && password.value !== passwordAgain.value,
)
const errors = computed(() => {
  const result: Record<string, string> = {}
  const value = draft.value
  if (!value) return result
  if (!value.username.trim()) result.username = t('system.required')
  else if (value.username !== value.username.trim()) result.username = t('system.account.usernameSpace')
  if (password.value && (password.value.length < 8 || !password.value.trim()))
    result.password = t('system.account.passwordRule')
  if (passwordMismatch.value && (passwordAgain.value !== '' || passwordAgainTouched.value))
    result.passwordAgain = t('system.account.passwordMismatch')
  if (!value.host.trim()) result.host = t('system.required')
  if (value.port === null) result.port = t('system.required')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0 || passwordMismatch.value)
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="5" />
  <ErrorNote
    v-else-if="settings.isError.value"
    :title="t('system.readFailed')"
    :error="settings.error.value"
    :retry="settings.refetch"
  />
  <div v-else-if="draft" class="flex min-w-0 max-w-3xl flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6">
      <FormSection :title="t('system.account.login')">
        <Field :label="t('system.account.username')" :error="errors.username" required wide>
          <Input v-model="draft.username" autocomplete="username" />
        </Field>
        <Field :label="t('system.account.password')" :error="errors.password">
          <Input
            v-model="password"
            type="password"
            autocomplete="new-password"
            :placeholder="t('system.account.passwordKept')"
          />
        </Field>
        <Field
          :label="t('system.account.passwordAgain')"
          :error="errors.passwordAgain"
          :required="Boolean(password)"
        >
          <Input
            v-model="passwordAgain"
            type="password"
            autocomplete="new-password"
            :placeholder="t('system.account.passwordKept')"
            @blur="passwordAgainTouched = true"
          />
        </Field>
      </FormSection>
      <FormSection :title="t('system.account.address')">
        <Field :label="t('system.account.host')" :error="errors.host" required>
          <Input v-model="draft.host" mono placeholder="127.0.0.1" />
        </Field>
        <Field :label="t('system.account.port')" :error="errors.port" required>
          <NumberInput
            v-model="draft.port"
            :min="1"
            :max="65535"
            :steppers="false"
            :format-options="{ useGrouping: false }"
          />
        </Field>
        <Field :label="t('system.account.https')" inline wide>
          <Switch v-model="draft.cookie_secure" />
        </Field>
      </FormSection>
    </div>
    <SaveBar
      :dirty="form.dirty.value"
      :saving="form.saving.value"
      :error="form.saveError.value"
      :invalid="invalid"
      @save="form.submit"
      @discard="form.discard"
    />
  </div>
</template>
