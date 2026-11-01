<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Combobox from '../../../ui/Combobox.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import { useStepErrors, useWizard } from '../wizard'

const { t } = useI18n()
const wizard = useWizard()
const { draft } = wizard
const error = useStepErrors('owner')

const people = computed(() =>
  wizard.knownPeople.value.map((person) => ({ value: person.id, label: person.name, meta: person.id })),
)
const sources = computed(() => [
  { value: 'list' as const, label: t('setup.owner.fromList') },
  { value: 'manual' as const, label: t('setup.persona.manual') },
])
/** Telegram's pending messages can name the owner; otherwise the account is typed. */
const listed = computed(() => people.value.length > 0 && draft.ownerSource === 'list')
const chosen = computed({
  get: () => draft.owner || undefined,
  set: (value: string | string[] | undefined) => (draft.owner = typeof value === 'string' ? value : ''),
})
const label = computed(() => t(`setup.owner.accounts.${wizard.prefix.value}`))

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
    <Field v-if="people.length" :label="t('setup.owner.source')" wide>
      <div>
        <SegmentedControl v-model="draft.ownerSource" :options="sources" :label="label" />
      </div>
    </Field>
    <Field :label="label" :error="error('owner')" required>
      <Combobox v-if="listed" v-model="chosen" :options="people" />
      <Input
        v-else
        v-model="draft.owner"
        mono
        :inputmode="wizard.prefix.value === 'feishu' ? 'text' : 'numeric'"
        :placeholder="wizard.prefix.value === 'feishu' ? 'ou_' : '10001'"
      />
    </Field>
    <Field :label="t('system.connection.timezone')" :error="error('timezone')" required>
      <Combobox v-model="timezone" :options="zoneOptions" placeholder="Asia/Shanghai" />
    </Field>
  </div>
</template>
