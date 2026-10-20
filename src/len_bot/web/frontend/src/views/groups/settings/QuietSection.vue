<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QuietHours } from '../../../api/settings'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import Select from '../../../ui/Select.vue'
import Switch from '../../../ui/Switch.vue'
import { useForm } from './form'

const { t } = useI18n()
const form = useForm()
const quiet = computed(() => form.draft.scene.attention.quiet_hours)
const enabled = computed({
  get: () => quiet.value !== null,
  set: (value: boolean) =>
    (form.draft.scene.attention.quiet_hours = value
      ? { start: '23:00', end: '07:00', direct: 'defer', notice_text: null }
      : null),
})
const directOptions = computed(() =>
  (['allow', 'notice', 'defer'] as const).map((value) => ({ value, label: t(`groups.settings.quiet.direct.${value}`) })),
)
const direct = computed({
  get: () => quiet.value?.direct,
  set: (value: QuietHours['direct'] | undefined) => {
    const target = form.draft.scene.attention.quiet_hours
    if (!target || !value) return
    target.direct = value
    if (value !== 'notice') target.notice_text = null
  },
})
const notice = computed({
  get: () => quiet.value?.notice_text ?? '',
  set: (value: string) => {
    const target = form.draft.scene.attention.quiet_hours
    if (target) target.notice_text = value || null
  },
})
</script>

<template>
  <FormSection :title="t('groups.settings.quiet.section')">
    <template #actions>
      <Switch v-model="enabled" :aria-label="t('groups.settings.quiet.section')" />
    </template>
    <template v-if="quiet">
      <Field :label="t('groups.settings.quiet.start')" :error="form.errors['quiet.start']">
        <Input v-model="quiet.start" placeholder="23:00" mono />
      </Field>
      <Field :label="t('groups.settings.quiet.end')" :error="form.errors['quiet.end']">
        <Input v-model="quiet.end" placeholder="07:00" mono />
      </Field>
      <Field :label="t('groups.settings.quiet.directLabel')">
        <Select v-model="direct" :options="directOptions" />
      </Field>
      <Field v-if="quiet.direct === 'notice'" :label="t('groups.settings.quiet.notice')" :error="form.errors['quiet.notice']">
        <Input v-model="notice" />
      </Field>
    </template>
  </FormSection>
</template>
