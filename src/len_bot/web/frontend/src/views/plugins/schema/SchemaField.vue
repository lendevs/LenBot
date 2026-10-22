<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Eye, EyeOff } from '@lucide/vue'
import type { ConfigField } from '../../../api/plugins'
import Badge from '../../../ui/Badge.vue'
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
import { fieldLabel, rangeText, segmented, wideField, type DraftValue } from './config'

const model = defineModel<DraftValue>({ required: true })
const props = defineProps<{
  field: ConfigField
  sceneChoices: string[]
  configured?: boolean
  error?: string | null
}>()

const { t } = useI18n()
const reveal = ref(false)
const kept = computed(() => props.field.type === 'secret' && props.configured)
const options = computed(() => props.field.options ?? [])
// SegmentedControl takes text values; number choices stay in a dropdown.
const asSegments = computed(
  () => segmented(props.field) && options.value.every((option) => typeof option.value === 'string'),
)
const placeholder = computed(() =>
  kept.value ? t('plugins.form.secretKept') : (props.field.placeholder ?? undefined),
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
    :required="field.required && field.type !== 'boolean' && !kept"
    :error="error"
    :wide="wideField(field)"
    :inline="field.type === 'boolean'"
  >
    <template #label-end>
      <Badge v-if="kept" tone="success" class="ml-auto">{{ t('plugins.form.saved') }}</Badge>
    </template>
    <Switch v-if="field.type === 'boolean'" v-model="flag" />
    <div v-else-if="field.options && asSegments">
      <SegmentedControl v-model="segment" :options="segments" :label="fieldLabel(field)" />
    </div>
    <Select v-else-if="field.options" v-model="choice" :options="options" />
    <ScenePicker v-else-if="field.type === 'scene'" v-model="scenes" :choices="sceneChoices" single />
    <ScenePicker v-else-if="field.type === 'scene_list'" v-model="scenes" :choices="sceneChoices" />
    <TagInput
      v-else-if="field.type === 'string_list'"
      v-model="list"
      :delimiter="/\n/"
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
      v-model="text"
      :type="reveal ? 'text' : 'password'"
      mono
      autocomplete="new-password"
      :placeholder="placeholder"
    >
      <template #suffix>
        <IconButton
          :icon="reveal ? EyeOff : Eye"
          :label="reveal ? t('plugins.form.hide') : t('plugins.form.show')"
          variant="ghost"
          size="sm"
          class="-mr-2"
          @click="reveal = !reveal"
        />
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
