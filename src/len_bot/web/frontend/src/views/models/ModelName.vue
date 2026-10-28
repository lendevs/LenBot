<script setup lang="ts">
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
import { Check, ChevronsUpDown } from '@lucide/vue'
import type { ListedModel } from '../../api/models'
import { useFieldControl } from '../../ui/field'
import { controlFrame, controlHeight, controlInput, floatingPanel } from '../../ui/styles'

/** A model ID can be typed freely or selected from the provider's searchable catalog. */
const model = defineModel<string>({ required: true })
const props = defineProps<{
  models?: ListedModel[]
  placeholder?: string
  id?: string
  invalid?: boolean
  disabled?: boolean
}>()
const { t } = useI18n()
const field = useFieldControl(props)
</script>

<template>
  <ComboboxRoot
    v-model="model"
    :disabled="field.disabled.value"
    :reset-search-term-on-blur="false"
    :reset-search-term-on-select="false"
    open-on-click
  >
    <ComboboxAnchor
      :class="[controlFrame, controlHeight.md]"
      :data-invalid="field.invalid.value || undefined"
      :data-disabled="field.disabled.value || undefined"
    >
      <ComboboxInput
        :id="field.id.value"
        v-model="model"
        :placeholder="placeholder"
        :aria-invalid="field.invalid.value || undefined"
        :aria-describedby="field.describedBy.value"
        :class="[controlInput, 'font-mono text-sm']"
      />
      <ComboboxTrigger
        v-if="models?.length"
        class="inline-flex size-6 shrink-0 cursor-pointer items-center justify-center text-subtle hover:text-ink"
        :aria-label="t('ui.combobox.options')"
      >
        <ChevronsUpDown :size="15" aria-hidden="true" />
      </ComboboxTrigger>
    </ComboboxAnchor>
    <ComboboxPortal v-if="models?.length">
      <ComboboxContent
        position="popper"
        :side-offset="4"
        :class="[floatingPanel, 'w-(--reka-combobox-trigger-width) max-w-[calc(100vw-16px)]']"
      >
        <ComboboxViewport class="max-h-[min(20rem,var(--reka-combobox-content-available-height))] p-1">
          <ComboboxEmpty class="px-2 py-3 text-center text-sm text-subtle">
            {{ t('ui.combobox.empty') }}
          </ComboboxEmpty>
          <ComboboxItem
            v-for="item in models"
            :key="item.id"
            :value="item.id"
            :text-value="`${item.id} ${item.name}`"
            class="relative flex cursor-default flex-col gap-1 rounded-sm py-2 pr-8 pl-2 text-sm outline-none select-none data-highlighted:bg-hover"
          >
            <span class="w-full font-mono wrap-anywhere">{{ item.id }}</span>
            <span v-if="item.name !== item.id" class="w-full text-xs text-muted wrap-anywhere">
              {{ item.name }}
            </span>
            <ComboboxItemIndicator class="absolute top-2.5 right-2 inline-flex text-primary">
              <Check :size="15" aria-hidden="true" />
            </ComboboxItemIndicator>
          </ComboboxItem>
        </ComboboxViewport>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
</template>
