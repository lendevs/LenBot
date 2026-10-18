<script setup lang="ts">
import { computed, provide, toRef, useId } from 'vue'
import { fieldKey } from './field'

const props = withDefaults(
  defineProps<{
    label?: string
    error?: string | null
    required?: boolean
    disabled?: boolean
    /** Spans both columns of a FormSection. */
    wide?: boolean
    /** Label on the left and control on the right, for switches. */
    inline?: boolean
  }>(),
  { label: undefined, error: null },
)

const id = useId()
const errorId = `${id}-error`
provide(fieldKey, {
  id,
  invalid: computed(() => Boolean(props.error)),
  describedBy: computed(() => (props.error ? errorId : undefined)),
  disabled: toRef(props, 'disabled'),
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5" :class="wide && 'sm:col-span-2'">
    <div :class="inline ? 'flex min-h-9 items-center justify-between gap-4' : 'contents'">
      <label v-if="label" :for="id" class="text-sm font-medium text-ink-2" :class="disabled && 'opacity-60'">
        {{ label }}
        <span v-if="required" class="ml-0.5 text-error" aria-hidden="true">*</span>
      </label>
      <slot :id="id" />
    </div>
    <Transition name="ui-rise">
      <p v-if="error" :id="errorId" class="text-xs text-error" role="alert">{{ error }}</p>
    </Transition>
  </div>
</template>
