<script setup lang="ts">
import { computed, ref, useAttrs, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from '@lucide/vue'
import { useFieldControl } from './field'
import { controlFrame, controlHeight, controlInput } from './styles'

defineOptions({ inheritAttrs: false })

const model = defineModel<string>({ default: '' })
const props = withDefaults(
  defineProps<{
    type?: 'text' | 'password' | 'email' | 'url' | 'search' | 'tel' | 'date' | 'time'
    placeholder?: string
    icon?: Component
    clearable?: boolean
    mono?: boolean
    size?: 'sm' | 'md'
    id?: string
    invalid?: boolean
    disabled?: boolean
    readonly?: boolean
  }>(),
  { type: 'text', placeholder: undefined, icon: undefined, size: 'md', id: undefined },
)

const { t } = useI18n()
const attrs = useAttrs()
const field = useFieldControl(props)
const input = ref<HTMLInputElement>()
const frameAttrs = computed(() => ({ class: attrs.class, style: attrs.style }))
const inputAttrs = computed(() => {
  const { class: _class, style: _style, ...rest } = attrs
  return rest
})

function clear() {
  model.value = ''
  input.value?.focus()
}

defineExpose({ focus: () => input.value?.focus(), select: () => input.value?.select() })
</script>

<template>
  <div
    v-bind="frameAttrs"
    :class="[controlFrame, controlHeight[size]]"
    :data-invalid="field.invalid.value || undefined"
    :data-disabled="field.disabled.value || undefined"
  >
    <component :is="icon" v-if="icon" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
    <slot name="prefix" />
    <input
      :id="field.id.value"
      ref="input"
      v-bind="inputAttrs"
      v-model="model"
      :type="type"
      :placeholder="placeholder"
      :disabled="field.disabled.value"
      :readonly="readonly"
      :aria-invalid="field.invalid.value || undefined"
      :aria-describedby="field.describedBy.value"
      :class="[controlInput, mono && 'font-mono text-sm']"
    />
    <button
      v-if="clearable && model && !field.disabled.value && !readonly"
      type="button"
      class="-mr-1 inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-sm text-subtle transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
      :aria-label="t('ui.input.clear')"
      @click="clear"
    >
      <X :size="14" aria-hidden="true" />
    </button>
    <slot name="suffix" />
  </div>
</template>
