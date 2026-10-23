<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown } from '@lucide/vue'
import type { ChatRole } from '../../api/models'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import Select from '../../ui/Select.vue'
import Switch from '../../ui/Switch.vue'
import ModelName from './ModelName.vue'
import ProbeTools from './ProbeTools.vue'
import { useForm } from './form'

const props = defineProps<{ role: ChatRole }>()

const { t } = useI18n()
const form = useForm()
const binding = computed(() => form.draft.value!.roles[props.role])
const row = computed(() => form.providerFor(binding.value?.provider))
const api = computed(() => row.value?.api)
const title = computed(() => form.roleTitle(props.role))
const errors = computed(() => form.problems.value.filter((item) => item.place === `roles.${props.role}`))

const enabled = computed({
  get: () => binding.value !== null,
  set: (on: boolean) => props.role !== 'mind' && form.toggleRole(props.role, on),
})
/** Select options cannot be empty; this stands for leaving the effort to the provider. */
const UNSET = '*'
const effortOptions = (current: string | null | undefined, unset: string) => {
  const known = ['minimal', 'low', 'medium', 'high']
  return [
    { value: UNSET, label: unset },
    ...[...known, ...(current && !known.includes(current) ? [current] : [])].map((value) => ({
      value,
      label: value,
    })),
  ]
}
const efforts = computed(() =>
  effortOptions(binding.value?.reasoning_effort, t('models.roles.effortDefault')),
)
const quickEfforts = computed(() =>
  effortOptions(binding.value?.quick_reasoning_effort, t('models.roles.quickEffortSame')),
)
/** On means a low effort for replies right after new messages; the select below keeps other levels. */
const quickReply = computed({
  get: () => binding.value?.quick_reasoning_effort != null,
  set: (on: boolean) => {
    if (binding.value)
      binding.value.quick_reasoning_effort = on ? (binding.value.quick_reasoning_effort ?? 'low') : null
  },
})
const thinkingOptions = computed(() => [
  { value: UNSET, label: t('models.roles.effortDefault') },
  { value: 'enabled', label: t('models.roles.thinkingEnabled') },
  { value: 'disabled', label: t('models.roles.thinkingDisabled') },
])
const histories = computed(() => [
  { value: 'native' as const, label: t('models.roles.history.native') },
  { value: 'omit-reasoning' as const, label: t('models.roles.history.omit') },
])
const outputFields = [
  { value: 'max_completion_tokens' as const, label: 'max_completion_tokens' },
  { value: 'max_tokens' as const, label: 'max_tokens' },
]
/** Waits before each retry, typed as numbers separated by commas or spaces. */
const parse = (text: string) =>
  text
    .split(/[,，\s]+/)
    .filter(Boolean)
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > 0)
    .slice(0, 20)
const retries = ref('')
watch(
  () => binding.value?.retry_delays_seconds.join(', ') ?? '',
  (saved) => {
    if (parse(retries.value).join(', ') !== saved) retries.value = saved
  },
  { immediate: true },
)
watch(retries, (text) => {
  if (binding.value) binding.value.retry_delays_seconds = parse(text)
})
</script>

<template>
  <section class="flex min-w-0 flex-col gap-4 rounded-xl border border-line bg-surface p-5">
    <header class="flex min-h-8 items-center justify-between gap-3">
      <h3 class="text-base font-semibold text-ink">{{ title }}</h3>
      <Switch v-if="role !== 'mind'" v-model="enabled" :aria-label="title" />
    </header>
    <p v-if="!binding" class="text-sm text-muted">
      {{ role === 'vision' ? t('models.roles.mindSees') : t('models.roles.followsMind') }}
    </p>
    <template v-if="binding">
      <div class="grid gap-x-5 gap-y-5 sm:grid-cols-3">
        <Field :label="t('models.roles.provider')">
          <Select
            :model-value="binding.provider"
            :options="form.optionsFor(role)"
            :placeholder="t('models.roles.noProvider')"
            :invalid="!row"
            @update:model-value="(id) => id && form.chooseRoleProvider(role, id)"
          />
        </Field>
        <Field :label="t('models.roles.model')">
          <ModelName v-model="binding.model" :models="form.catalog.value[binding.provider]" />
        </Field>
        <Field :label="t('models.roles.context')">
          <NumberInput v-model="binding.context_window_tokens" :min="1" :steppers="false" unit="tokens" />
        </Field>
        <Field v-if="role === 'mind' || role === 'vision'" :label="t('models.roles.imageInput')">
          <Switch v-model="binding.image_input" :aria-label="t('models.roles.imageInput')" />
        </Field>
        <Field v-if="role === 'mind'" :label="t('models.roles.quickReply')">
          <Switch v-model="quickReply" :aria-label="t('models.roles.quickReply')" />
        </Field>
      </div>
      <details class="group">
        <summary
          class="flex w-fit cursor-pointer list-none items-center gap-1 text-sm text-muted hover:text-ink [&::-webkit-details-marker]:hidden"
        >
          {{ t('models.roles.advanced') }}
          <ChevronDown :size="16" class="transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
        <div class="mt-4 grid gap-x-5 gap-y-5 sm:grid-cols-3">
          <Field :label="t('models.roles.maxOutput')">
            <NumberInput v-model="binding.max_output_tokens" :min="1" :steppers="false" unit="tokens" />
          </Field>
          <Field :label="t('models.roles.timeout')">
            <NumberInput
              v-model="binding.timeout_seconds"
              :min="1"
              :steppers="false"
              :unit="t('groups.settings.seconds')"
            />
          </Field>
          <Field :label="t('models.roles.effort')">
            <Select
              :model-value="binding.reasoning_effort ?? UNSET"
              :options="efforts"
              @update:model-value="
                (value) => (binding!.reasoning_effort = !value || value === UNSET ? null : value)
              "
            />
          </Field>
          <Field v-if="role === 'mind'" :label="t('models.roles.quickEffort')">
            <Select
              :model-value="binding.quick_reasoning_effort ?? UNSET"
              :options="quickEfforts"
              @update:model-value="
                (value) => (binding!.quick_reasoning_effort = !value || value === UNSET ? null : value)
              "
            />
          </Field>
          <Field v-if="api === 'anthropic' || api === 'gemini'" :label="t('models.roles.thinking')">
            <NumberInput
              v-model="binding.thinking_budget_tokens"
              :min="0"
              :steppers="false"
              unit="tokens"
              :placeholder="t('common.none')"
            />
          </Field>
          <Field :label="t('models.roles.retries')">
            <Input v-model="retries" mono :placeholder="t('models.roles.noRetry')" />
          </Field>
          <template v-if="api === 'openai-chat'">
            <Field :label="t('models.roles.thinkingSwitch')">
              <Select
                :model-value="binding.thinking ?? UNSET"
                :options="thinkingOptions"
                @update:model-value="
                  (value) => (binding!.thinking = value === 'enabled' || value === 'disabled' ? value : null)
                "
              />
            </Field>
            <Field :label="t('models.roles.history.label')">
              <Select v-model="binding.history_policy" :options="histories" />
            </Field>
            <Field :label="t('models.roles.outputField')">
              <Select v-model="binding.output_token_field" :options="outputFields" />
            </Field>
          </template>
        </div>
      </details>
      <ul v-if="errors.length" class="flex list-none flex-col gap-1 text-sm text-error">
        <li v-for="item in errors" :key="item.text">{{ item.text }}</li>
      </ul>
      <ProbeTools v-if="row" :row="row" :binding="binding" />
    </template>
  </section>
</template>
