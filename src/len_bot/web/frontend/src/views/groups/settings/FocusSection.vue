<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ArrowUpRight, X } from '@lucide/vue'
import { hostApi } from '../../../api/host'
import { keys } from '../../../api/query'
import type { Declarations, Disposition } from '../../../api/settings'
import Button from '../../../ui/Button.vue'
import Collapsible from '../../../ui/Collapsible.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import Select from '../../../ui/Select.vue'
import Switch from '../../../ui/Switch.vue'
import { cloneValue, useForm } from './form'

const props = defineProps<{ scene: string }>()
const { t } = useI18n()
const form = useForm()
const attention = computed(() => form.draft.scene.attention)

/** Same defaults as `configuration/chat.py`. */
const DECLARATIONS: Declarations = {
  mode: 'enforce',
  max_minutes: 240,
  max_intents: 5,
  max_conditions: 4,
  max_people: 5,
  max_keywords: 5,
}
const DISPOSITION: Disposition = { mode: 'enforce', max_minutes: 30, max_people: 5 }

const intents = computed({
  get: () => attention.value.declarations != null,
  set: (value: boolean) => {
    if (!value) {
      attention.value.declarations = null
      return
    }
    const saved = form.saved?.scene.attention.declarations
    attention.value.declarations = saved ? cloneValue(saved) : { ...DECLARATIONS }
  },
})
const wrapUp = computed({
  get: () => attention.value.disposition != null,
  set: (value: boolean) => {
    if (!value) {
      attention.value.disposition = null
      return
    }
    const saved = form.saved?.scene.attention.disposition
    attention.value.disposition = saved ? cloneValue(saved) : { ...DISPOSITION }
  },
})

const focus = useQuery({
  queryKey: computed(() => keys.host.focus(props.scene)),
  queryFn: ({ signal }) => hostApi.focus(props.scene, signal),
})
const blocked = computed(() => intents.value && focus.data.value?.persona_allows === false)

const intentModes = computed(() =>
  (['enforce', 'record', 'context'] as const).map((value) => ({
    value,
    label: t(`groups.settings.focus.modes.${value}`),
  })),
)
const wrapModes = computed(() =>
  (['enforce', 'record'] as const).map((value) => ({
    value,
    label: t(`groups.settings.focus.modes.${value}`),
  })),
)
const intentLimits = ['max_intents', 'max_conditions', 'max_people', 'max_keywords', 'max_minutes'] as const
const wrapLimits = ['max_minutes', 'max_people'] as const
const hasDetailsError = computed(
  () =>
    intentLimits.some((key) => Boolean(form.errors[`attention.declarations.${key}`])) ||
    wrapLimits.some((key) => Boolean(form.errors[`attention.disposition.${key}`])),
)
</script>

<template>
  <FormSection id="focus" :title="t('groups.settings.focus.section')">
    <Field :label="t('groups.settings.focus.intents')" inline wide>
      <Switch v-model="intents" />
    </Field>
    <div
      v-if="blocked"
      class="flex flex-wrap items-center justify-between gap-2 rounded-md bg-error-bg px-3 py-2 text-sm text-error sm:col-span-2"
    >
      <span class="flex min-w-0 items-center gap-2">
        <X :size="16" class="shrink-0" aria-hidden="true" />
        <span>{{ t('groups.settings.focus.blocked') }}</span>
      </span>
      <Button
        size="sm"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="{ name: 'host-persona', query: { persona: focus.data.value?.persona } }"
      >
        {{ t('groups.settings.focus.toPersona') }}
      </Button>
    </div>
    <Field :label="t('groups.settings.focus.wrapUp')" inline wide>
      <Switch v-model="wrapUp" />
    </Field>

    <Collapsible
      v-if="attention.declarations || attention.disposition"
      v-model:open="form.expanded.focusDetails"
      :title="t('groups.settings.focus.details')"
      :dot="hasDetailsError ? 'error' : false"
      class="sm:col-span-2"
      content-class="flex flex-col gap-5"
    >
      <div v-if="attention.declarations" class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
        <Field :label="t('groups.settings.focus.intentMode')">
          <Select v-model="attention.declarations.mode" :options="intentModes" />
        </Field>
        <Field
          v-for="key in intentLimits"
          :key="`intent-${key}`"
          :label="t(`groups.settings.focus.intentLimits.${key}`)"
          :error="form.errors[`attention.declarations.${key}`]"
        >
          <NumberInput
            v-model="attention.declarations[key]"
            :min="1"
            :unit="key === 'max_minutes' ? t('groups.settings.minutes') : undefined"
          />
        </Field>
      </div>
      <div
        v-if="attention.disposition"
        class="grid gap-x-5 gap-y-5 sm:grid-cols-2"
        :class="attention.declarations && 'border-t border-line pt-5'"
      >
        <Field :label="t('groups.settings.focus.wrapMode')">
          <Select v-model="attention.disposition.mode" :options="wrapModes" />
        </Field>
        <Field
          v-for="key in wrapLimits"
          :key="`wrap-${key}`"
          :label="t(`groups.settings.focus.wrapLimits.${key}`)"
          :error="form.errors[`attention.disposition.${key}`]"
        >
          <NumberInput
            v-model="attention.disposition[key]"
            :min="1"
            :unit="key === 'max_minutes' ? t('groups.settings.minutes') : undefined"
          />
        </Field>
      </div>
    </Collapsible>
  </FormSection>
</template>
