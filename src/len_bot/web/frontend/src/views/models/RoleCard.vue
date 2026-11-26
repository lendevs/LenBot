<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatRole } from '../../api/models'
import Button from '../../ui/Button.vue'
import Collapsible from '../../ui/Collapsible.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import Select from '../../ui/Select.vue'
import Switch from '../../ui/Switch.vue'
import ModelName from './ModelName.vue'
import DeepSeekAntiBaguCard from './DeepSeekAntiBaguCard.vue'
import ProbeTools from './ProbeTools.vue'
import { hasKey, isDeepSeekModel, useForm, type ProblemField } from './form'

const props = defineProps<{ role: ChatRole }>()

const { t } = useI18n()
const form = useForm()
const binding = computed(() => form.draft.value!.roles[props.role])
const row = computed(() => form.providerFor(binding.value?.provider))
const api = computed(() => row.value?.api)
const title = computed(() => form.roleTitle(props.role))
const errors = computed(() => form.problems.value.filter((item) => item.place === `roles.${props.role}`))
const fieldError = (field: ProblemField) => errors.value.find((item) => item.field === field)?.text ?? null
const mappedFields = new Set<ProblemField>([
  'provider',
  'model',
  'context',
  'maxOutput',
  'timeout',
  'thinking',
  'retries',
])
const extraErrors = computed(() =>
  errors.value.filter((item) => !item.field || !mappedFields.has(item.field)),
)
const inherited = computed(() => {
  const mind = form.draft.value!.roles.mind
  const provider = form.nameOf(mind.provider)
  const model = mind.model.trim()
  return model ? `${provider} / ${model}` : provider
})
/**
 * A chat model that accepts images looks at them itself; the vision card starts collapsed while still
 * allowing pre-configuring a standalone vision model without erasing it on collapse.
 */
const mindSees = computed(() => props.role === 'vision' && form.draft.value!.roles.mind.image_input)
const visionExpanded = ref(false)
watch(
  () => errors.value.length,
  (count, previous = 0) => {
    if (count > 0 && count > previous) visionExpanded.value = true
  },
  { immediate: true },
)
watch(
  () => form.triedSave.value,
  (tried) => {
    if (tried && errors.value.length > 0) visionExpanded.value = true
  },
)
const visionCollapsed = computed(() => mindSees.value && !visionExpanded.value)
function openVision() {
  if (props.role !== 'vision') return
  if (!binding.value) form.toggleRole('vision', true)
  visionExpanded.value = true
}
function collapseVision() {
  if (props.role !== 'vision') return
  visionExpanded.value = false
}
function switchToStandaloneVision() {
  if (props.role !== 'vision') return
  form.useStandaloneVision()
  visionExpanded.value = true
}
const bothThinking = computed(() =>
  Boolean(
    binding.value && binding.value.reasoning_effort !== null && binding.value.thinking_budget_tokens !== null,
  ),
)
const advancedHasError = computed(() =>
  Boolean(
    binding.value && (binding.value.timeout_seconds === null || bothThinking.value || fieldError('retries')),
  ),
)
const advancedOpen = ref(false)
watch(
  advancedHasError,
  (hasError) => {
    if (hasError) advancedOpen.value = true
  },
  { immediate: true },
)
watch(
  () => form.triedSave.value,
  (tried) => {
    if (tried && advancedHasError.value) advancedOpen.value = true
  },
)
const canRefreshModels = computed(() => Boolean(row.value))
const refreshModelsDisabled = computed(() => !row.value || !hasKey(row.value) || !row.value.base_url.trim())
const refreshingModels = computed(() => Boolean(row.value && form.catalogLoading.value[row.value.id]))
/** Marked once the provider's list was read and the model typed here is not in it, e.g. after a retirement. */
const unlisted = computed(() => {
  const listed = binding.value && form.catalog.value[binding.value.provider]
  return Boolean(
    listed?.length && binding.value!.model && !listed.some((item) => item.id === binding.value!.model),
  )
})

const showAntiBagu = computed(() =>
  Boolean(
    props.role === 'mind' &&
    binding.value &&
    (isDeepSeekModel(binding.value.model, row.value?.base_url) || binding.value.anti_bagu),
  ),
)
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
/** Waits before each retry, typed as positive numbers separated by commas or spaces. */
function parseRetries(text: string): { values: number[]; error: 'format' | 'max' | null } {
  const trimmed = text.trim()
  if (!trimmed) return { values: [], error: null }
  const parts = trimmed.split(/[,，\s]+/).filter(Boolean)
  if (parts.length > 20) return { values: [], error: 'max' }
  const values: number[] = []
  for (const part of parts) {
    if (!/^(?:\d+(?:\.\d+)?|\.\d+)$/.test(part)) return { values: [], error: 'format' }
    const num = Number(part)
    if (!Number.isFinite(num) || num <= 0) return { values: [], error: 'format' }
    values.push(num)
  }
  return { values, error: null }
}
const retries = ref('')
watch(
  [() => form.draft.value, () => binding.value === null],
  () => {
    retries.value = binding.value?.retry_delays_seconds.join(', ') ?? ''
    form.setRetryError(props.role, null)
  },
  { immediate: true },
)
watch(
  () => binding.value?.retry_delays_seconds.join(', ') ?? '',
  (saved) => {
    const current = parseRetries(retries.value)
    if (!current.error && current.values.join(', ') !== saved) retries.value = saved
  },
)
watch(retries, (text) => {
  if (!binding.value) {
    form.setRetryError(props.role, null)
    return
  }
  const parsed = parseRetries(text)
  form.setRetryError(props.role, parsed.error)
  if (!parsed.error) binding.value.retry_delays_seconds = parsed.values
})
</script>

<template>
  <section class="flex min-w-0 flex-col gap-4 py-6 first:pt-1 last:pb-0">
    <header class="flex min-h-8 items-center justify-between gap-3">
      <div class="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
        <h3 class="shrink-0 text-base font-semibold text-ink">{{ title }}</h3>
        <span
          v-if="binding && binding.model"
          class="min-w-0 truncate font-mono text-xs text-muted"
          :class="!(visionCollapsed && binding.model) && 'max-sm:hidden'"
        >
          {{ binding.model }}
        </span>
        <span v-else-if="!binding && role !== 'vision'" class="min-w-0 truncate text-xs text-muted">
          {{ t('models.roles.followsMind') }}
          <template v-if="inherited">
            ·
            <span class="font-mono">{{ inherited }}</span>
          </template>
        </span>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <Button
          v-if="role === 'mind' && form.canSyncFromMind.value"
          size="sm"
          variant="ghost"
          @click="form.syncCustomRolesFromMind()"
        >
          {{ t('models.roles.syncToCustomRoles') }}
        </Button>
        <Button v-else-if="visionCollapsed" size="sm" variant="ghost" @click="openVision">
          {{ binding ? t('models.roles.editVision') : t('models.roles.configureVision') }}
        </Button>
        <template v-else-if="mindSees">
          <Button size="sm" variant="ghost" @click="collapseVision">
            {{ t('common.collapse') }}
          </Button>
          <Switch v-model="enabled" :aria-label="title" />
        </template>
        <Switch v-else-if="role !== 'mind'" v-model="enabled" :aria-label="title" />
      </div>
    </header>
    <div
      v-if="role === 'vision' && (!binding || mindSees)"
      class="flex flex-wrap items-center justify-between gap-2"
    >
      <p class="text-sm text-muted">
        {{
          mindSees
            ? binding
              ? t('models.roles.visionBackupActive')
              : t('models.roles.mindSees')
            : t('models.roles.noVision')
        }}
      </p>
      <Button v-if="mindSees" size="sm" variant="secondary" @click="switchToStandaloneVision">
        {{ t('models.roles.useStandaloneVision') }}
      </Button>
    </div>
    <template v-if="binding && !visionCollapsed">
      <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
        <Field :label="t('models.roles.provider')" :error="fieldError('provider')">
          <Select
            :model-value="binding.provider"
            :options="form.optionsFor(role)"
            :placeholder="t('models.roles.noProvider')"
            @update:model-value="(id) => id && form.chooseRoleProvider(role, id)"
          />
        </Field>
        <Field
          :label="t('models.roles.model')"
          :error="fieldError('model') ?? (unlisted ? t('models.roles.notListed') : null)"
        >
          <ModelName
            v-model="binding.model"
            :models="form.catalog.value[binding.provider]"
            :can-refresh="canRefreshModels"
            :refresh-disabled="refreshModelsDisabled"
            :refreshing="refreshingModels"
            @refresh="row && form.loadCatalog(row.id)"
          />
        </Field>
        <Transition name="ui-rise">
          <DeepSeekAntiBaguCard
            v-if="showAntiBagu"
            v-model="binding.anti_bagu"
            class="sm:col-span-2 lg:order-4 lg:col-span-3"
          />
        </Transition>
        <Field :label="t('models.roles.context')" :error="fieldError('context')" class="lg:order-3">
          <NumberInput v-model="binding.context_window_tokens" :min="1" :steppers="false" unit="tokens" />
        </Field>
        <Field :label="t('models.roles.maxOutput')" :error="fieldError('maxOutput')" class="lg:order-5">
          <NumberInput v-model="binding.max_output_tokens" :min="1" :steppers="false" unit="tokens" />
        </Field>
        <Field :label="t('models.roles.effort')" class="lg:order-5">
          <Select
            :model-value="binding.reasoning_effort ?? UNSET"
            :options="efforts"
            @update:model-value="
              (value) => (binding!.reasoning_effort = !value || value === UNSET ? null : value)
            "
          />
        </Field>
        <Field v-if="api === 'openai-chat'" :label="t('models.roles.thinkingSwitch')" class="lg:order-5">
          <Select
            :model-value="binding.thinking ?? UNSET"
            :options="thinkingOptions"
            @update:model-value="
              (value) => (binding!.thinking = value === 'enabled' || value === 'disabled' ? value : null)
            "
          />
        </Field>
      </div>
      <div v-if="role === 'mind' || role === 'vision'" class="grid gap-x-8 gap-y-3 sm:grid-cols-2">
        <Field :label="t('models.roles.imageInput')" inline>
          <Switch v-model="binding.image_input" :aria-label="t('models.roles.imageInput')" />
        </Field>
        <Field v-if="role === 'mind'" :label="t('models.roles.quickReply')" inline>
          <Switch v-model="quickReply" :aria-label="t('models.roles.quickReply')" />
        </Field>
      </div>
      <Collapsible
        v-model:open="advancedOpen"
        variant="inline"
        :title="t('models.roles.advanced')"
        :dot="advancedHasError ? 'error' : false"
      >
        <div class="mt-2 grid gap-x-5 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
          <Field :label="t('models.roles.timeout')" :error="fieldError('timeout')">
            <NumberInput
              v-model="binding.timeout_seconds"
              :min="1"
              :steppers="false"
              :unit="t('groups.settings.seconds')"
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
          <Field
            v-if="api === 'anthropic' || api === 'gemini'"
            :label="t('models.roles.thinking')"
            :error="fieldError('thinking')"
          >
            <NumberInput
              v-model="binding.thinking_budget_tokens"
              :min="0"
              :steppers="false"
              unit="tokens"
              :placeholder="t('common.none')"
            />
          </Field>
          <Field :label="t('models.roles.retries')" :error="fieldError('retries')">
            <Input v-model="retries" mono :placeholder="t('models.roles.noRetry')" />
          </Field>
          <template v-if="api === 'openai-chat'">
            <Field :label="t('models.roles.history.label')">
              <Select v-model="binding.history_policy" :options="histories" />
            </Field>
            <Field :label="t('models.roles.outputField')">
              <Select v-model="binding.output_token_field" :options="outputFields" />
            </Field>
          </template>
        </div>
      </Collapsible>
      <ul v-if="extraErrors.length" class="flex list-none flex-col gap-1 text-sm text-error">
        <li v-for="item in extraErrors" :key="item.text">{{ item.text }}</li>
      </ul>
      <ProbeTools v-if="row" :row="row" :binding="binding" />
    </template>
  </section>
</template>
