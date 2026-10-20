<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import { settingsApi, type SpeechMode } from '../../../api/settings'
import { readHostState } from '../../../host/store.js'
import { formatDateTime } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useForm } from './form'

const props = defineProps<{ scene: string; timeZone: string }>()

const { t } = useI18n()
const client = useQueryClient()
const form = useForm()
const global = computed(() => form.settings.data?.saved.limits.messages_per_hour ?? null)
const modes = computed(() =>
  (['global', 'custom', 'unlimited'] as const).map((value) => ({
    value,
    label:
      value === 'global'
        ? t('groups.settings.speech.global', {
            limit: global.value === null ? t('groups.settings.speech.none') : global.value,
          })
        : t(`groups.settings.speech.${value}`),
  })),
)
const mode = computed({
  get: () => form.draft.speech.mode,
  set: (value: SpeechMode) =>
    (form.draft.speech = { mode: value, value: value === 'custom' ? (form.draft.speech.value ?? global.value ?? 60) : null }),
})

const limits = useQuery({ queryKey: keys.host.limits(), queryFn: ({ signal }) => settingsApi.limits(signal) })
const state = computed(() => limits.data.value?.scenes.find((item) => item.scene === props.scene)?.speech ?? null)
const usage = computed(() => {
  const value = state.value
  if (!value) return ''
  const parts = [
    value.limit === null
      ? t('groups.settings.speech.used', { used: value.used })
      : t('groups.settings.speech.usedOf', { used: value.used, limit: value.limit }),
  ]
  if (value.held_until) {
    parts.push(t('groups.settings.speech.held', { time: formatDateTime(value.held_until, { timeZone: props.timeZone }) }))
    parts.push(
      value.reserve_left
        ? t('groups.settings.speech.reserve', { n: value.reserve_left })
        : t('groups.settings.speech.reserveUsed'),
    )
  }
  return parts.join(' · ')
})
const reset = useMutation({
  mutationFn: () => settingsApi.resetSpeech(props.scene),
  onSuccess: () => toast.success(t('groups.settings.speech.released')),
  onError: (error) =>
    toast.error(t('groups.settings.speech.releaseFailed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => {
    void client.invalidateQueries({ queryKey: keys.host.limits() })
    void readHostState()
  },
})
</script>

<template>
  <FormSection :title="t('groups.settings.speech.section')">
    <Field :label="t('groups.settings.speech.mode')" wide>
      <SegmentedControl v-model="mode" :options="modes" :label="t('groups.settings.speech.mode')" />
    </Field>
    <Field v-if="form.draft.speech.mode === 'custom'" :label="t('groups.settings.speech.value')" :error="form.errors.speech">
      <NumberInput v-model="form.draft.speech.value" :min="1" :unit="t('groups.settings.speech.unit')" />
    </Field>
    <div v-if="state" class="flex flex-wrap items-center gap-3 text-sm sm:col-span-2">
      <span :class="state.held_until ? 'text-warning' : 'text-muted'">{{ usage }}</span>
      <Button v-if="state.held_until" size="sm" :loading="reset.isPending.value" @click="reset.mutate()">
        {{ t('groups.settings.speech.release') }}
      </Button>
    </div>
  </FormSection>
</template>
