<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { systemApi, systemOf, type Processing } from '../../api/system'
import { developerMode } from '../../composables/useDeveloperMode.js'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import { useSettingsDraft } from './draft'

const { t } = useI18n()
const form = useSettingsDraft<Processing>({
  pick: (snapshot) => systemOf(snapshot).processing,
  section: 'processing',
  save: (value) => systemApi.saveProcessing(value),
})
const { settings, draft } = form

type Group = 'compaction' | 'images' | 'audio'
interface NumberField {
  group: Group
  key: string
  min: number
  max?: number
  unit?: string
  decimals?: boolean
}
const groups = computed<{ group: Group; fields: NumberField[] }[]>(() => {
  const seconds = t('system.seconds')
  return [
    {
      group: 'compaction',
      fields: [
        { group: 'compaction', key: 'input_tokens', min: 1, unit: 'tokens' },
        { group: 'compaction', key: 'keep_recent_tokens', min: 1, unit: 'tokens' },
        { group: 'compaction', key: 'max_output_tokens', min: 1, unit: 'tokens' },
      ],
    },
    {
      group: 'images',
      fields: [
        { group: 'images', key: 'max_bytes', min: 1, unit: 'B' },
        { group: 'images', key: 'max_pixels', min: 1 },
        { group: 'images', key: 'max_dimension', min: 1, unit: 'px' },
        { group: 'images', key: 'timeout_seconds', min: 0.1, unit: seconds, decimals: true },
      ],
    },
    {
      group: 'audio',
      fields: [
        { group: 'audio', key: 'max_bytes', min: 1, max: 26214400, unit: 'B' },
        { group: 'audio', key: 'max_seconds', min: 1, max: 3600, unit: seconds, decimals: true },
        { group: 'audio', key: 'timeout_seconds', min: 0.1, unit: seconds, decimals: true },
        { group: 'audio', key: 'wait_seconds', min: 0, max: 30, unit: seconds, decimals: true },
      ],
    },
  ]
})
const fieldsOf = (group: Group) => draft.value![group] as Record<string, number | null>
const levels = [
  { value: 'INFO', label: 'INFO' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' },
]

const errors = computed(() => {
  const result: Record<string, string> = {}
  const value = draft.value
  if (!value) return result
  for (const { group, fields } of groups.value)
    for (const { key } of fields) if (fieldsOf(group)[key] === null) result[`${group}.${key}`] = t('system.required')
  if (!value.logging.directory.trim()) result['logging.directory'] = t('system.required')
  if (value.logging.retention_days === null) result['logging.retention_days'] = t('system.required')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <Field :label="t('system.advanced.developer')" inline>
        <Switch v-model="developerMode" />
      </Field>
    </div>
    <Skeleton v-if="settings.isPending.value" :lines="6" />
    <ErrorNote v-else-if="settings.isError.value" :title="t('system.readFailed')" :error="settings.error.value" :retry="settings.refetch" />
    <template v-else-if="draft">
      <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
        <FormSection v-for="{ group, fields } in groups" :key="group" :title="t(`system.advanced.groups.${group}`)">
          <Field
            v-for="item in fields"
            :key="item.key"
            :label="t(`system.advanced.fields.${group}.${item.key}`)"
            :error="errors[`${group}.${item.key}`]"
          >
            <NumberInput
              v-model="fieldsOf(group)[item.key]"
              :min="item.min"
              :max="item.max"
              :snap="!item.decimals"
              :steppers="false"
              :unit="item.unit"
            />
          </Field>
        </FormSection>
        <FormSection :title="t('system.advanced.groups.logging')">
          <Field :label="t('system.advanced.fields.logging.directory')" :error="errors['logging.directory']">
            <Input v-model="draft.logging.directory" mono placeholder="logs" />
          </Field>
          <Field :label="t('system.advanced.fields.logging.retention_days')" :error="errors['logging.retention_days']">
            <NumberInput v-model="draft.logging.retention_days" :min="1" :max="3650" :unit="t('system.retention.days')" />
          </Field>
          <Field :label="t('system.advanced.fields.logging.level')">
            <div>
              <SegmentedControl v-model="draft.logging.level" :options="levels" :label="t('system.advanced.fields.logging.level')" />
            </div>
          </Field>
        </FormSection>
      </div>
      <SaveBar :dirty="form.dirty.value" :saving="form.saving.value" :error="form.saveError.value" :invalid="invalid" @save="form.submit" @discard="form.discard" />
    </template>
  </div>
</template>
