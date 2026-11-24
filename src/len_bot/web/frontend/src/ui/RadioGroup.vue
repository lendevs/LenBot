<script setup lang="ts" generic="T extends string">
import { RadioGroupIndicator, RadioGroupItem, RadioGroupRoot } from 'reka-ui'
import { useFieldControl } from './field'

export interface RadioOption<V> {
  value: V
  label: string
  disabled?: boolean
}

const model = defineModel<T>()
const props = withDefaults(
  defineProps<{
    options: RadioOption<T>[]
    orientation?: 'vertical' | 'horizontal'
    id?: string
    invalid?: boolean
    disabled?: boolean
  }>(),
  { orientation: 'vertical', id: undefined },
)

const field = useFieldControl(props)
</script>

<template>
  <RadioGroupRoot
    :id="field.id.value"
    v-model="model"
    :orientation="orientation"
    :disabled="field.disabled.value"
    :aria-invalid="field.invalid.value || undefined"
    :aria-describedby="field.describedBy.value"
    class="flex gap-x-5 gap-y-2.5"
    :class="orientation === 'vertical' ? 'flex-col' : 'flex-wrap items-center'"
  >
    <label
      v-for="option in options"
      :key="option.value"
      class="inline-flex min-w-0 items-center gap-2.5 text-base text-ink pointer-coarse:min-h-9"
      :class="option.disabled || field.disabled.value ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'"
    >
      <RadioGroupItem
        :value="option.value"
        :disabled="option.disabled"
        :data-invalid="field.invalid.value || undefined"
        class="inline-flex size-4.5 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface transition-[border-color,transform] duration-(--dur-1) ease-out hover:border-subtle focus-visible:focus-ring enabled:active:scale-95 data-invalid:border-error data-invalid:hover:border-error data-[state=checked]:border-primary"
      >
        <RadioGroupIndicator
          class="size-2.5 animate-[ui-pop-in_var(--dur-1)_var(--ease-spring)] rounded-full bg-primary"
        />
      </RadioGroupItem>
      <span class="min-w-0">{{ option.label }}</span>
    </label>
  </RadioGroupRoot>
</template>
