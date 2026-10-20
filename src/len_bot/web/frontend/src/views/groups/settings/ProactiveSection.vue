<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import Switch from '../../../ui/Switch.vue'
import { useForm } from './form'

const { t } = useI18n()
const form = useForm()
const proactive = computed(() => form.draft.scene.proactive)
const enabled = computed({
  get: () => proactive.value !== null,
  set: (value: boolean) =>
    (form.draft.scene.proactive = value ? { idle_seconds: 10800, start: '10:00', end: '22:00' } : null),
})
/** Edited in hours, saved in seconds. */
const hours = computed({
  get: () => (proactive.value ? proactive.value.idle_seconds / 3600 : null),
  set: (value: number | null) => {
    const target = form.draft.scene.proactive
    if (target) target.idle_seconds = value === null ? Number.NaN : Math.round(value * 3600)
  },
})
</script>

<template>
  <FormSection :title="t('groups.settings.proactive.section')">
    <template #actions>
      <Switch v-model="enabled" :aria-label="t('groups.settings.proactive.section')" />
    </template>
    <template v-if="proactive">
      <Field :label="t('groups.settings.proactive.idle')" :error="form.errors['proactive.idle']" wide>
        <NumberInput
          v-model="hours"
          :min="0.5"
          :step="0.5"
          :unit="t('groups.settings.hours')"
          class="sm:max-w-60"
        />
      </Field>
      <Field :label="t('groups.settings.proactive.start')" :error="form.errors['proactive.start']">
        <Input v-model="proactive.start" placeholder="10:00" mono />
      </Field>
      <Field :label="t('groups.settings.proactive.end')" :error="form.errors['proactive.end']">
        <Input v-model="proactive.end" placeholder="22:00" mono />
      </Field>
    </template>
  </FormSection>
</template>
