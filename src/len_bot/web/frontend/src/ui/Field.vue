<script setup lang="ts">
import { computed, provide, toRef, useId } from 'vue'
import { Info } from '@lucide/vue'
import Tooltip from './Tooltip.vue'
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
    /** What the field means, shown from an icon next to the label. */
    info?: string
  }>(),
  { label: undefined, error: null, info: undefined },
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
      <span v-if="label && info" class="flex min-w-0 items-center gap-1">
        <label
          :for="id"
          class="min-w-0 truncate text-sm font-medium text-ink-2"
          :class="disabled && 'opacity-60'"
        >
          {{ label }}
          <span v-if="required" class="ml-0.5 text-error" aria-hidden="true">*</span>
        </label>
        <Tooltip :text="info">
          <button
            type="button"
            class="inline-flex shrink-0 cursor-help rounded-sm text-subtle hover:text-ink-2 focus-visible:focus-ring"
            :aria-label="info"
          >
            <Info :size="14" aria-hidden="true" />
          </button>
        </Tooltip>
        <slot name="label-end" />
      </span>
      <label
        v-else-if="label"
        :for="id"
        class="text-sm font-medium text-ink-2"
        :class="disabled && 'opacity-60'"
      >
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
