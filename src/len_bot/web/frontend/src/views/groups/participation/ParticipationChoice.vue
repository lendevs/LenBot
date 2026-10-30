<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatNumber } from '../../../i18n/format'
import Field from '../../../ui/Field.vue'
import RadioGroup from '../../../ui/RadioGroup.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import {
  ACTIVITY_LEVELS,
  activityLevel,
  type ActivityLevel,
  type Participation,
} from '../../../api/participation'

const model = defineModel<Participation>({ required: true })
const { t } = useI18n()

const mode = computed({
  get: () => (model.value.only_direct ? 'direct' : 'join'),
  set: (value: 'direct' | 'join') => (model.value = { ...model.value, only_direct: value === 'direct' }),
})
const modes = computed(() =>
  (['direct', 'join'] as const).map((value) => ({ value, label: t(`participation.modes.${value}`) })),
)
const level = computed({
  get: (): ActivityLevel | 'custom' => activityLevel(model.value.activity) ?? 'custom',
  set: (value: ActivityLevel | 'custom') => {
    if (value !== 'custom') model.value = { ...model.value, activity: ACTIVITY_LEVELS[value] }
  },
})
const levels = computed(() => [
  ...(['low', 'medium', 'high'] as const).map((value) => ({
    value,
    label: t(`participation.levels.${value}`),
  })),
  ...(level.value === 'custom'
    ? [
        {
          value: 'custom' as const,
          label: t('participation.custom', {
            value: formatNumber(model.value.activity, { maximumFractionDigits: 2 }),
          }),
        },
      ]
    : []),
])
</script>

<template>
  <Field :label="t('participation.mode')" wide>
    <RadioGroup v-model="mode" :options="modes" />
  </Field>
  <Field v-if="!model.only_direct" :label="t('participation.frequency')">
    <div>
      <SegmentedControl v-model="level" :options="levels" :label="t('participation.frequency')" />
    </div>
  </Field>
</template>
