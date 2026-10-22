<script setup lang="ts" generic="T extends string | number">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxPortal,
  ComboboxRoot,
  ComboboxTrigger,
  ComboboxViewport,
} from 'reka-ui'
import { Check, ChevronsUpDown, X } from '@lucide/vue'
import { useFieldControl } from './field'
import { controlFrame, floatingPanel, menuItem } from './styles'

export interface ComboboxOption<V> {
  value: V
  label: string
  /** Secondary text matched by the search too, such as a group number. */
  meta?: string
  disabled?: boolean
}

/** One value, or several when `multiple` is set; selected values show as removable chips. */
const model = defineModel<T | T[] | undefined>()
const props = withDefaults(
  defineProps<{
    options: ComboboxOption<T>[]
    multiple?: boolean
    placeholder?: string
    id?: string
    invalid?: boolean
    disabled?: boolean
  }>(),
  { placeholder: undefined, id: undefined },
)

const { t } = useI18n()
const field = useFieldControl(props)
const search = ref('')
const byValue = computed(() => new Map(props.options.map((option) => [option.value, option])))
const chosen = computed<T[]>(() =>
  props.multiple
    ? ((model.value as T[] | undefined) ?? [])
    : model.value === undefined
      ? []
      : [model.value as T],
)

function labelOf(value: unknown): string {
  return byValue.value.get(value as T)?.label ?? (value === undefined || value === null ? '' : String(value))
}
function remove(value: T) {
  model.value = chosen.value.filter((item) => item !== value)
}
</script>

<template>
  <ComboboxRoot
    v-model="model"
    v-model:search-term="search"
    :multiple="multiple"
    :disabled="field.disabled.value"
    open-on-click
  >
    <ComboboxAnchor
      :class="[
        controlFrame,
        'min-h-9 flex-wrap gap-1.5 py-1 pr-1.5 pointer-coarse:min-h-11',
        multiple && 'pl-1.5',
      ]"
      :data-invalid="field.invalid.value || undefined"
      :data-disabled="field.disabled.value || undefined"
    >
      <template v-if="multiple">
        <span
          v-for="value in chosen"
          :key="value"
          class="inline-flex h-6 max-w-full animate-fade items-center gap-1 rounded-sm bg-fill pr-0.5 pl-2 text-sm text-ink-2"
        >
          <span class="truncate">{{ labelOf(value) }}</span>
          <button
            type="button"
            class="inline-flex size-5 cursor-pointer items-center justify-center rounded-sm text-subtle hover:bg-hover hover:text-ink focus-visible:focus-ring"
            :aria-label="t('ui.combobox.remove', { name: labelOf(value) })"
            :disabled="field.disabled.value"
            @click.stop="remove(value)"
          >
            <X :size="12" aria-hidden="true" />
          </button>
        </span>
      </template>
      <ComboboxInput
        :id="field.id.value"
        :placeholder="chosen.length && multiple ? undefined : (placeholder ?? t('ui.combobox.placeholder'))"
        :display-value="multiple ? undefined : labelOf"
        :aria-invalid="field.invalid.value || undefined"
        :aria-describedby="field.describedBy.value"
        class="h-7 min-w-24 flex-1 bg-transparent px-1 outline-none placeholder:text-subtle focus-visible:outline-none"
        :class="!multiple && 'px-1.5'"
      />
      <ComboboxTrigger
        class="inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-sm text-subtle hover:text-ink"
      >
        <ChevronsUpDown :size="15" aria-hidden="true" />
      </ComboboxTrigger>
    </ComboboxAnchor>
    <ComboboxPortal>
      <ComboboxContent
        position="popper"
        :side-offset="4"
        :class="[floatingPanel, 'max-h-72 min-w-(--reka-combobox-trigger-width)']"
      >
        <ComboboxViewport class="p-1">
          <ComboboxEmpty class="px-2 py-3 text-center text-sm text-subtle">
            {{ t('ui.combobox.empty') }}
          </ComboboxEmpty>
          <ComboboxItem
            v-for="option in options"
            :key="option.value"
            :value="option.value"
            :text-value="option.meta ? `${option.label} ${option.meta}` : option.label"
            :disabled="option.disabled"
            :class="[menuItem, 'pr-8']"
          >
            <span class="truncate">{{ option.label }}</span>
            <span v-if="option.meta" class="ml-auto shrink-0 text-xs text-subtle tabular">
              {{ option.meta }}
            </span>
            <ComboboxItemIndicator class="absolute right-2 inline-flex text-primary">
              <Check :size="15" aria-hidden="true" />
            </ComboboxItemIndicator>
          </ComboboxItem>
        </ComboboxViewport>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
</template>
