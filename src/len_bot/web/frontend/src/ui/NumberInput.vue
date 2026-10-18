<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { NumberFieldDecrement, NumberFieldIncrement, NumberFieldInput, NumberFieldRoot } from 'reka-ui'
import { Minus, Plus } from '@lucide/vue'
import { currentLocale } from '../i18n'
import { useFieldControl } from './field'
import { controlFrame, controlHeight } from './styles'

const model = defineModel<number | null>({ default: null })
const props = withDefaults(
  defineProps<{
    min?: number
    max?: number
    step?: number
    /** Shown after the number, such as 秒 or tokens. */
    unit?: string
    placeholder?: string
    size?: 'sm' | 'md'
    /** Hide the − and + buttons for wide ranges where stepping is pointless. */
    steppers?: boolean
    formatOptions?: Intl.NumberFormatOptions
    id?: string
    invalid?: boolean
    disabled?: boolean
  }>(),
  {
    min: undefined,
    max: undefined,
    step: 1,
    unit: undefined,
    placeholder: undefined,
    size: 'md',
    steppers: true,
    formatOptions: () => ({ useGrouping: false, maximumFractionDigits: 6 }),
    id: undefined,
  },
)

const { t } = useI18n()
const field = useFieldControl(props)
const value = computed({
  get: () => model.value ?? undefined,
  set: (next: number | undefined) => (model.value = next === undefined || Number.isNaN(next) ? null : next),
})
const stepper =
  'inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-sm text-muted transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring disabled:pointer-events-none disabled:opacity-35 pointer-coarse:size-8'
</script>

<template>
  <NumberFieldRoot
    v-model="value"
    :min="min"
    :max="max"
    :step="step"
    :locale="currentLocale"
    :format-options="formatOptions"
    :disabled="field.disabled.value"
    :class="[controlFrame, controlHeight[size], 'pr-1.5']"
    :data-invalid="field.invalid.value || undefined"
    :data-disabled="field.disabled.value || undefined"
  >
    <NumberFieldInput
      :id="field.id.value"
      :placeholder="placeholder"
      :aria-invalid="field.invalid.value || undefined"
      :aria-describedby="field.describedBy.value"
      class="h-full w-full min-w-0 flex-1 bg-transparent tabular outline-none placeholder:text-subtle focus-visible:outline-none"
    />
    <span v-if="unit" class="shrink-0 text-sm text-subtle">{{ unit }}</span>
    <template v-if="steppers">
      <NumberFieldDecrement :class="stepper" :aria-label="t('ui.number.decrease')">
        <Minus :size="14" aria-hidden="true" />
      </NumberFieldDecrement>
      <NumberFieldIncrement :class="stepper" :aria-label="t('ui.number.increase')">
        <Plus :size="14" aria-hidden="true" />
      </NumberFieldIncrement>
    </template>
  </NumberFieldRoot>
</template>
