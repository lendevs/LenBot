<script setup lang="ts" generic="T extends string | number">
import { computed, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  SelectContent,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'
import { Check, ChevronDown } from '@lucide/vue'
import { useFieldControl } from './field'
import { controlFrame, controlHeight, floatingPanel, menuItem } from './styles'

export interface SelectOption<V> {
  value: V
  label: string
  icon?: Component
  disabled?: boolean
}

const model = defineModel<T | undefined>()
const props = withDefaults(
  defineProps<{
    options: SelectOption<T>[]
    placeholder?: string
    size?: 'sm' | 'md'
    id?: string
    invalid?: boolean
    disabled?: boolean
  }>(),
  { placeholder: undefined, size: 'md', id: undefined },
)

const { t } = useI18n()
const field = useFieldControl(props)
const selected = computed(() => props.options.find((option) => option.value === model.value))
</script>

<template>
  <SelectRoot v-model="model" :disabled="field.disabled.value">
    <SelectTrigger
      :id="field.id.value"
      :aria-invalid="field.invalid.value || undefined"
      :aria-describedby="field.describedBy.value"
      :data-invalid="field.invalid.value || undefined"
      :class="[
        controlFrame,
        controlHeight[size],
        'cursor-pointer justify-between pr-2 text-left focus-visible:outline-none data-placeholder:text-subtle',
      ]"
    >
      <span class="flex min-w-0 items-center gap-2">
        <component :is="selected.icon" v-if="selected?.icon" :size="16" class="shrink-0 text-muted" />
        <!-- Rendered from the options so a label that changes after selection, such as a group name read later, updates. -->
        <SelectValue :placeholder="placeholder ?? t('ui.select.placeholder')" class="truncate">
          {{ selected ? selected.label : (placeholder ?? t('ui.select.placeholder')) }}
        </SelectValue>
      </span>
      <ChevronDown :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
    </SelectTrigger>
    <SelectPortal>
      <SelectContent
        position="popper"
        :side-offset="4"
        :class="[
          floatingPanel,
          'max-h-(--reka-select-content-available-height) min-w-(--reka-select-trigger-width)',
        ]"
      >
        <SelectViewport class="p-1">
          <SelectItem
            v-for="option in options"
            :key="option.value"
            :value="option.value"
            :disabled="option.disabled"
            :class="[menuItem, 'pr-8']"
          >
            <component :is="option.icon" v-if="option.icon" :size="16" class="shrink-0 text-muted" />
            <SelectItemText class="truncate">{{ option.label }}</SelectItemText>
            <SelectItemIndicator class="absolute right-2 inline-flex text-primary">
              <Check :size="15" aria-hidden="true" />
            </SelectItemIndicator>
          </SelectItem>
        </SelectViewport>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
