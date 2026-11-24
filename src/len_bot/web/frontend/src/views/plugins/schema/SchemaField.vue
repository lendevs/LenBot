<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Eye, EyeOff } from '@lucide/vue'
import type { ConfigField } from '../../../api/plugins'
import Badge from '../../../ui/Badge.vue'
import Combobox from '../../../ui/Combobox.vue'
import Field from '../../../ui/Field.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'
import Switch from '../../../ui/Switch.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'
import ScenePicker from './ScenePicker.vue'
import {
  fieldLabel,
  hasDefault,
  initialField,
  rangeText,
  segmented,
  wideField,
  type DraftValue,
} from './config'

const model = defineModel<DraftValue>({ required: true })
const props = defineProps<{
  field: ConfigField
  sceneChoices: string[]
  enabledScenes?: string[]
  configured?: boolean
  error?: string | null
  onEnablePicked?: (scenes: string[]) => void | Promise<void>
  enablingPicked?: boolean
}>()

const { t } = useI18n()
const reveal = ref(false)
const kept = computed(() => props.field.type === 'secret' && Boolean(props.configured))
const cleared = computed(() => kept.value && model.value === null)
const secretText = computed({
  get: () => (typeof model.value === 'string' ? model.value : ''),
  set: (value: string) => (model.value = value),
})
const options = computed(() => props.field.options ?? [])
const stringOptions = computed(() => options.value.every((option) => typeof option.value === 'string'))
// SegmentedControl takes <=3 short text choices; >8 text choices use searchable Combobox; 4-8 stay Select.
const asSegments = computed(() => segmented(props.field) && stringOptions.value)
const asCombobox = computed(() => options.value.length > 8 && stringOptions.value)
const comboOptions = computed(() =>
  options.value.map((option) => ({ value: String(option.value), label: option.label })),
)
const comboValue = computed<string | string[] | undefined>({
  get: () => {
    if (typeof model.value !== 'string') return undefined
    if (model.value === '' && !options.value.some((option) => option.value === '')) return undefined
    return model.value
  },
  set: (value) => {
    model.value = typeof value === 'string' ? value : ''
  },
})
const canReset = computed(
  () =>
    hasDefault(props.field) &&
    JSON.stringify(model.value) !== JSON.stringify(initialField(props.field, props.field.default)),
)
const resetField = () => (model.value = initialField(props.field, props.field.default))
const placeholder = computed(() =>
  cleared.value
    ? t('ui.secret.willClear')
    : kept.value
      ? t('plugins.form.secretKept')
      : (props.field.placeholder ?? undefined),
)
// Steppers help on a short integer range; for wide or decimal ranges they are noise.
const steppers = computed(
  () =>
    props.field.type === 'integer' &&
    props.field.minimum !== null &&
    props.field.maximum !== null &&
    props.field.maximum - props.field.minimum <= 100,
)
const text = computed({ get: () => model.value as string, set: (value: string) => (model.value = value) })
const number = computed({ get: () => model.value as number | null, set: (value) => (model.value = value) })
const list = computed({ get: () => model.value as string[], set: (value: string[]) => (model.value = value) })
const choice = computed({
  get: () => model.value as string | number,
  set: (value: string | number) => (model.value = value),
})
const flag = computed({ get: () => model.value as boolean, set: (value: boolean) => (model.value = value) })
const segment = computed({ get: () => model.value as string, set: (value: string) => (model.value = value) })
const segments = computed(() =>
  options.value.map((option) => ({ value: String(option.value), label: option.label })),
)
const scenes = computed({
  get: () => model.value as string | string[] | null,
  set: (value) => (model.value = value as DraftValue),
})
</script>

<template>
  <Field
    :label="fieldLabel(field)"
    :info="field.description || undefined"
    :required="field.required && field.type !== 'boolean' && (!kept || cleared)"
    :error="error"
    :wide="wideField(field)"
    :inline="field.type === 'boolean'"
  >
    <template #label-end>
      <span v-if="kept" class="ml-auto inline-flex items-center gap-2">
        <template v-if="cleared">
          <Badge tone="warning">{{ t('ui.secret.willClear') }}</Badge>
          <button
            type="button"
            class="cursor-pointer rounded-sm text-xs font-medium text-primary hover:underline focus-visible:focus-ring"
            @click="model = ''"
          >
            {{ t('ui.secret.keepSaved') }}
          </button>
        </template>
        <template v-else>
          <Badge tone="success">{{ t('plugins.form.saved') }}</Badge>
          <button
            v-if="!secretText"
            type="button"
            class="cursor-pointer rounded-sm text-xs font-medium text-muted transition-colors hover:text-error focus-visible:focus-ring"
            @click="model = null"
          >
            {{ t('ui.secret.clearSaved') }}
          </button>
        </template>
      </span>
      <button
        v-else-if="canReset"
        type="button"
        class="shrink-0 cursor-pointer rounded-sm text-xs font-medium text-muted transition-colors hover:text-ink focus-visible:focus-ring"
        :class="field.type !== 'boolean' && 'ml-auto'"
        @click="resetField"
      >
        {{ t('common.reset') }}
      </button>
    </template>
    <Switch v-if="field.type === 'boolean'" v-model="flag" />
    <div v-else-if="field.options && asSegments">
      <SegmentedControl v-model="segment" :options="segments" :label="fieldLabel(field)" />
    </div>
    <Combobox
      v-else-if="field.options && asCombobox"
      v-model="comboValue"
      :options="comboOptions"
      :placeholder="placeholder"
    />
    <Select v-else-if="field.options" v-model="choice" :options="options" />
    <ScenePicker
      v-else-if="field.type === 'scene'"
      v-model="scenes"
      :choices="sceneChoices"
      :enabled-scenes="enabledScenes"
      :on-enable-picked="onEnablePicked"
      :enabling-picked="enablingPicked"
      single
    />
    <ScenePicker
      v-else-if="field.type === 'scene_list'"
      v-model="scenes"
      :choices="sceneChoices"
      :enabled-scenes="enabledScenes"
      :on-enable-picked="onEnablePicked"
      :enabling-picked="enablingPicked"
    />
    <TagInput
      v-else-if="field.type === 'string_list'"
      v-model="list"
      :placeholder="t('plugins.form.addItem')"
    />
    <Textarea
      v-else-if="field.type === 'string' && field.multiline"
      v-model="text"
      :rows="3"
      :placeholder="placeholder"
    />
    <Textarea v-else-if="field.type === 'object_list'" v-model="text" :rows="5" mono placeholder="[]" />
    <NumberInput
      v-else-if="field.type === 'integer' || field.type === 'number'"
      v-model="number"
      :min="field.minimum ?? undefined"
      :max="field.maximum ?? undefined"
      :snap="field.type === 'integer'"
      :steppers="steppers"
      :unit="rangeText(field)"
      :placeholder="placeholder"
    />
    <Input
      v-else-if="field.type === 'secret'"
      v-model="secretText"
      :type="reveal ? 'text' : 'password'"
      mono
      autocomplete="new-password"
      :placeholder="placeholder"
    >
      <template #suffix>
        <span class="-mr-2 inline-flex">
          <IconButton
            :icon="reveal ? EyeOff : Eye"
            :label="reveal ? t('ui.secret.hide') : t('ui.secret.show')"
            variant="ghost"
            size="sm"
            @click="reveal = !reveal"
          />
        </span>
      </template>
    </Input>
    <Input
      v-else
      v-model="text"
      :type="field.type === 'url' ? 'url' : 'text'"
      :mono="field.type === 'path' || field.type === 'url'"
      :placeholder="placeholder"
    />
  </Field>
</template>
