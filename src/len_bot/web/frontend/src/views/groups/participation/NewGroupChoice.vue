<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Field from '../../../ui/Field.vue'
import RadioGroup from '../../../ui/RadioGroup.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import {
  WAKE_LEVEL_ORDER,
  type ChatMode,
  type Participation,
  type WakeLevel,
} from '../../../api/participation'

/** A new group joins in at a wake level; with the mode model bound, it can also start in plugin mode. */
const model = defineModel<Participation>({ required: true })
const mode = defineModel<ChatMode>('mode')
const { t } = useI18n()

const modes = computed(() =>
  (['chat', 'plugins'] as const).map((value) => ({ value, label: t(`participation.chatModes.${value}`) })),
)
const level = computed({
  get: (): WakeLevel => model.value.level ?? 'moderate',
  set: (value: WakeLevel) => (model.value = { only_direct: false, level: value }),
})
const levels = computed(() =>
  WAKE_LEVEL_ORDER.map((value) => ({ value, label: t(`participation.levels.${value}`) })),
)
</script>

<template>
  <Field v-if="mode" :label="t('participation.chatMode')" wide>
    <RadioGroup v-model="mode" :options="modes" />
  </Field>
  <Field v-if="mode !== 'plugins'" :label="t('participation.frequency')">
    <div>
      <SegmentedControl v-model="level" :options="levels" :label="t('participation.frequency')" />
    </div>
  </Field>
</template>
