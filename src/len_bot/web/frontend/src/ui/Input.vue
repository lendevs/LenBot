<script setup lang="ts">
import { computed, ref, useAttrs, useSlots, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Eye, EyeOff, X } from '@lucide/vue'
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
    /** Show a visibility toggle for non-empty password inputs when no custom suffix slot is used. */
    revealable?: boolean
    mono?: boolean
    size?: 'sm' | 'md'
    id?: string
    invalid?: boolean
    disabled?: boolean
    readonly?: boolean
  }>(),
  { type: 'text', placeholder: undefined, icon: undefined, revealable: true, size: 'md', id: undefined },
)

const { t } = useI18n()
const attrs = useAttrs()
const slots = useSlots()
const field = useFieldControl(props)
const input = ref<HTMLInputElement>()
const revealed = ref(false)
const frameAttrs = computed(() => ({ class: attrs.class, style: attrs.style }))
const inputAttrs = computed(() => {
  const { class: _class, style: _style, ...rest } = attrs
  return rest
})
const canReveal = computed(
  () =>
    props.type === 'password' &&
    props.revealable &&
    !slots.suffix &&
    model.value.length > 0 &&
    !field.disabled.value &&
    !props.readonly,
)
watch([() => props.type, () => props.revealable, model], ([type, revealable, value]) => {
  if (type !== 'password' || !revealable || value === '') revealed.value = false
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
    :data-readonly="readonly || undefined"
  >
    <component
      :is="icon"
      v-if="icon"
      :size="size === 'sm' ? 15 : 16"
      class="shrink-0 text-subtle"
      aria-hidden="true"
    />
    <slot name="prefix" />
    <input
      :id="field.id.value"
      ref="input"
      v-bind="inputAttrs"
      v-model="model"
      :type="canReveal && revealed ? 'text' : type"
      :placeholder="placeholder"
      :disabled="field.disabled.value"
      :readonly="readonly"
      :aria-invalid="field.invalid.value || undefined"
      :aria-describedby="field.describedBy.value"
      :class="[controlInput, mono && 'font-mono text-sm pointer-coarse:text-lg']"
    />
    <button
      v-if="clearable && model && !field.disabled.value && !readonly"
      type="button"
      class="inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-sm text-subtle transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring pointer-coarse:size-8"
      :class="!canReveal && !$slots.suffix && '-mr-1'"
      :aria-label="t('ui.input.clear')"
      @click="clear"
    >
      <X :size="14" aria-hidden="true" />
    </button>
    <button
      v-if="canReveal"
      type="button"
      class="-mr-1 inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-sm text-subtle transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring pointer-coarse:size-8"
      :aria-label="revealed ? t('ui.secret.hide') : t('ui.secret.show')"
      :aria-pressed="revealed"
      @click="revealed = !revealed"
    >
      <EyeOff v-if="revealed" :size="15" aria-hidden="true" />
      <Eye v-else :size="15" aria-hidden="true" />
    </button>
    <slot name="suffix" />
  </div>
</template>
