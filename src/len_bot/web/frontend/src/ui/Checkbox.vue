<script setup lang="ts">
import { CheckboxIndicator, CheckboxRoot } from 'reka-ui'
import { Check, Minus } from '@lucide/vue'
import { useFieldControl } from './field'

const model = defineModel<boolean | 'indeterminate'>({ default: false })
const props = withDefaults(defineProps<{ id?: string; disabled?: boolean; invalid?: boolean }>(), {
  id: undefined,
})

const field = useFieldControl(props)
</script>

<template>
  <label
    class="inline-flex min-w-0 items-start gap-2.5"
    :class="field.disabled.value ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'"
  >
    <CheckboxRoot
      :id="field.id.value"
      v-model="model"
      :disabled="field.disabled.value"
      :data-invalid="field.invalid.value || undefined"
      class="mt-0.5 inline-flex size-4.5 shrink-0 items-center justify-center rounded-[5px] border border-line-strong bg-surface text-on-primary transition-[background-color,border-color] duration-150 ease-out hover:border-subtle focus-visible:focus-ring data-invalid:border-error data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=indeterminate]:border-primary data-[state=indeterminate]:bg-primary"
    >
      <CheckboxIndicator class="inline-flex animate-[ui-pop-in_var(--dur-1)_var(--ease-spring)]">
        <Minus v-if="model === 'indeterminate'" :size="13" :stroke-width="3" aria-hidden="true" />
        <Check v-else :size="13" :stroke-width="3" aria-hidden="true" />
      </CheckboxIndicator>
    </CheckboxRoot>
    <span v-if="$slots.default" class="min-w-0 text-base text-ink"><slot /></span>
  </label>
</template>
