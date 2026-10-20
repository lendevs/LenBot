<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown } from '@lucide/vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import RadioGroup from '../../../ui/RadioGroup.vue'
import Switch from '../../../ui/Switch.vue'
import TagInput from '../../../ui/TagInput.vue'
import { useForm } from './form'

type NumberKey =
  | 'direct_idle_seconds'
  | 'direct_max_seconds'
  | 'named_idle_seconds'
  | 'named_max_seconds'
  | 'focus_seconds'
  | 'focus_idle_seconds'
  | 'focus_max_seconds'
  | 'keyword_cooldown_seconds'
  | 'ambient_threshold'
  | 'ambient_min_interval_seconds'
  | 'ambient_max_interval_seconds'
  | 'explore_probability'
  | 'max_extensions'

const { t } = useI18n()
const form = useForm()
const details = ref(false)

const mode = computed({
  get: () => (form.draft.scene.attention.only_direct ? 'direct' : 'join'),
  set: (value: 'direct' | 'join') => (form.draft.scene.attention.only_direct = value === 'direct'),
})
const modes = computed(() =>
  (['direct', 'join'] as const).map((value) => ({ value, label: t(`groups.settings.participation.modes.${value}`) })),
)
const timezone = computed({
  get: () => form.draft.scene.timezone ?? '',
  set: (value: string) => (form.draft.scene.timezone = value || null),
})

/** Waiting and joining details; seconds unless marked otherwise. */
const timing: { key: NumberKey; seconds?: boolean; step?: number; max?: number }[] = [
  { key: 'direct_idle_seconds', seconds: true, step: 0.5 },
  { key: 'direct_max_seconds', seconds: true, step: 0.5 },
  { key: 'named_idle_seconds', seconds: true, step: 0.5 },
  { key: 'named_max_seconds', seconds: true, step: 0.5 },
  { key: 'focus_seconds', seconds: true, step: 10 },
  { key: 'focus_idle_seconds', seconds: true, step: 0.5 },
  { key: 'focus_max_seconds', seconds: true, step: 0.5 },
  { key: 'keyword_cooldown_seconds', seconds: true, step: 10 },
  { key: 'ambient_threshold', step: 0.05 },
  { key: 'ambient_min_interval_seconds', seconds: true, step: 10 },
  { key: 'ambient_max_interval_seconds', seconds: true, step: 10 },
  { key: 'explore_probability', step: 0.01, max: 1 },
  { key: 'max_extensions' },
]
</script>

<template>
  <FormSection :title="t('groups.settings.participation.section')">
    <Field :label="t('groups.settings.participation.mode')" wide>
      <RadioGroup v-model="mode" :options="modes" />
    </Field>
    <template v-if="!form.draft.scene.attention.only_direct">
      <Field :label="t('groups.settings.participation.activity')" :error="form.errors['attention.activity']">
        <NumberInput v-model="form.draft.scene.attention.activity" :min="0" :max="1" :step="0.05" />
      </Field>
      <Field :label="t('groups.settings.participation.keywords')" wide>
        <TagInput v-model="form.draft.scene.attention.keywords" />
      </Field>
    </template>
    <Field :label="t('groups.settings.participation.otherBots')" :error="form.errors.otherBots" wide>
      <TagInput v-model="form.draft.scene.attention.other_bot_ids" placeholder="onebot:10001" />
    </Field>
    <Field :label="t('groups.settings.participation.timezone')">
      <Input v-model="timezone" placeholder="Asia/Shanghai" mono />
    </Field>
    <Field :label="t('groups.settings.participation.transcribe')" inline wide>
      <Switch v-model="form.draft.scene.transcribe_audio" />
    </Field>

    <div class="sm:col-span-2">
      <button
        type="button"
        class="inline-flex cursor-pointer items-center gap-1.5 rounded-md text-sm font-medium text-muted hover:text-ink focus-visible:focus-ring"
        :aria-expanded="details"
        @click="details = !details"
      >
        <ChevronDown :size="15" class="transition-transform" :class="details && 'rotate-180'" aria-hidden="true" />
        {{ t('groups.settings.participation.details') }}
      </button>
    </div>
    <template v-if="details">
      <Field :label="t('groups.settings.participation.closeFocus')" inline wide>
        <Switch v-model="form.draft.scene.attention.close_focus_on_silence" />
      </Field>
      <Field
        v-for="item in timing"
        :key="item.key"
        :label="t(`groups.settings.participation.timing.${item.key}`)"
        :error="form.errors[`attention.${item.key}`]"
      >
        <NumberInput
          :model-value="form.draft.scene.attention[item.key]"
          :min="0"
          :max="item.max"
          :step="item.step ?? 1"
          :unit="item.seconds ? t('groups.settings.seconds') : undefined"
          @update:model-value="(value) => ((form.draft.scene.attention[item.key] = value as number))"
        />
      </Field>
    </template>
  </FormSection>
</template>
