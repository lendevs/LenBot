<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import Select from '../../ui/Select.vue'
import Switch from '../../ui/Switch.vue'
import ModelName from './ModelName.vue'
import RoleCard from './RoleCard.vue'
import { chatRoles, useForm } from './form'

const { t } = useI18n()
const form = useForm()
const asr = computed(() => form.draft.value!.roles.asr)
const asrErrors = computed(() => form.problems.value.filter((item) => item.place === 'roles.asr'))
const asrOn = computed({ get: () => asr.value !== null, set: (on: boolean) => form.toggleAsr(on) })
const language = computed({
  get: () => asr.value?.language ?? '',
  set: (value: string) => asr.value && (asr.value.language = value.trim().toLowerCase() || null),
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <RoleCard v-for="role in chatRoles" :key="role" :role="role" />
    <section class="flex min-w-0 flex-col gap-4 rounded-xl border border-line bg-surface p-5">
      <header class="flex min-h-8 items-center justify-between gap-3">
        <h3 class="text-base font-semibold text-ink">{{ form.roleTitle('asr') }}</h3>
        <Switch v-model="asrOn" :aria-label="form.roleTitle('asr')" />
      </header>
      <div v-if="asr" class="grid gap-x-5 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
        <Field :label="t('models.roles.provider')">
          <Select v-model="asr.provider" :options="form.optionsFor('asr')" :placeholder="t('models.roles.noProvider')" />
        </Field>
        <Field :label="t('models.roles.model')">
          <ModelName v-model="asr.model" :models="form.catalog.value[asr.provider]" placeholder="whisper-1" />
        </Field>
        <Field :label="t('models.roles.language')">
          <Input v-model="language" mono :placeholder="t('models.roles.autoLanguage')" />
        </Field>
        <Field :label="t('models.roles.timeout')">
          <NumberInput v-model="asr.timeout_seconds" :min="1" :steppers="false" :unit="t('groups.settings.seconds')" />
        </Field>
      </div>
      <ul v-if="asrErrors.length" class="flex list-none flex-col gap-1 text-sm text-error">
        <li v-for="item in asrErrors" :key="item.text">{{ item.text }}</li>
      </ul>
    </section>
  </div>
</template>
