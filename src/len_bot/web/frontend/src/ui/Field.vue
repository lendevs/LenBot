<script setup lang="ts">
import { computed, provide, ref, toRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { Info } from '@lucide/vue'
import Popover from './Popover.vue'
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

const { t } = useI18n()
const touch = useMediaQuery('(hover: none), (pointer: coarse)')
const id = useId()
const errorId = `${id}-error`
const infoLabel = computed(() =>
  props.label ? t('ui.field.info', { label: props.label }) : t('common.more'),
)
const shownError = ref(props.error ?? '')
watch(
  () => props.error,
  (value) => {
    if (value) shownError.value = value
  },
)
function onErrorTransitionEnd() {
  if (!props.error) shownError.value = ''
}

provide(fieldKey, {
  id,
  invalid: computed(() => Boolean(props.error)),
  describedBy: computed(() => (props.error ? errorId : undefined)),
  disabled: toRef(props, 'disabled'),
})
</script>

<template>
  <div class="flex min-w-0 flex-col" :class="wide && 'sm:col-span-2'">
    <div
      :class="
        inline
          ? 'flex min-h-9 items-center justify-between gap-4 [&>:last-child]:shrink-0'
          : 'flex min-w-0 flex-col gap-1.5'
      "
    >
      <span v-if="label && (info || $slots['label-end'])" class="flex min-w-0 items-center gap-1.5">
        <label
          :for="id"
          class="min-w-0 truncate text-sm font-medium text-ink-2"
          :class="disabled && 'opacity-60'"
        >
          {{ label }}
          <span v-if="required" class="ml-0.5 text-error" aria-hidden="true">*</span>
        </label>
        <Popover v-if="info && touch" side="top" align="start" width="w-64">
          <template #trigger>
            <button
              type="button"
              class="-m-1.5 inline-flex shrink-0 cursor-pointer items-center justify-center rounded-sm p-1.5 text-subtle transition-colors duration-(--dur-1) hover:text-ink-2 focus-visible:focus-ring"
              :aria-label="infoLabel"
            >
              <Info :size="14" aria-hidden="true" />
            </button>
          </template>
          <p class="text-xs leading-relaxed text-ink-2">{{ info }}</p>
        </Popover>
        <Tooltip v-else-if="info" :text="info">
          <button
            type="button"
            class="-m-1.5 inline-flex shrink-0 cursor-help items-center justify-center rounded-sm p-1.5 text-subtle transition-colors duration-(--dur-1) hover:text-ink-2 focus-visible:focus-ring"
            :aria-label="infoLabel"
          >
            <Info :size="14" aria-hidden="true" />
          </button>
        </Tooltip>
        <slot name="label-end" />
      </span>
      <label
        v-else-if="label"
        :for="id"
        class="min-w-0 text-sm font-medium text-ink-2"
        :class="disabled && 'opacity-60'"
      >
        {{ label }}
        <span v-if="required" class="ml-0.5 text-error" aria-hidden="true">*</span>
      </label>
      <slot :id="id" />
    </div>
    <div
      class="ui-grid-collapse"
      :data-open="error ? 'true' : 'false'"
      :inert="!error"
      :aria-hidden="!error || undefined"
      @transitionend.self="onErrorTransitionEnd"
    >
      <div>
        <p :id="errorId" class="pt-1.5 text-xs font-medium text-error" :role="error ? 'alert' : undefined">
          {{ shownError }}
        </p>
      </div>
    </div>
  </div>
</template>
