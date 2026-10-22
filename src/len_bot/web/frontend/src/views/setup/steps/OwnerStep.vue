<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Combobox from '../../../ui/Combobox.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import { useStepErrors, useWizard } from '../wizard'

const { t } = useI18n()
const { draft } = useWizard()
const error = useStepErrors('owner')

const zones = (() => {
  try {
    return Intl.supportedValuesOf('timeZone').map((zone) => ({ value: zone, label: zone }))
  } catch {
    return []
  }
})()
const zoneOptions = computed(() =>
  draft.timezone && !zones.some((zone) => zone.value === draft.timezone)
    ? [{ value: draft.timezone, label: draft.timezone }, ...zones]
    : zones,
)
const timezone = computed({
  get: () => draft.timezone || undefined,
  set: (value: string | string[] | undefined) => (draft.timezone = typeof value === 'string' ? value : ''),
})
</script>

<template>
  <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
    <Field :label="t('setup.owner.owner')" :error="error('owner')" required>
      <Input v-model="draft.owner" mono inputmode="numeric" placeholder="10001" />
    </Field>
    <Field :label="t('system.connection.timezone')" :error="error('timezone')" required>
      <Combobox v-model="timezone" :options="zoneOptions" placeholder="Asia/Shanghai" />
    </Field>
  </div>
</template>
