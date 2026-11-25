<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlignLeft, Check, Copy, RotateCcw, SlidersHorizontal } from '@lucide/vue'
import type { ConfigField } from '../../../api/plugins'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Textarea from '../../../ui/Textarea.vue'
import SchemaForm from '../schema/SchemaForm.vue'
import { draftToJson, hasDefault, initialField, jsonToDraft, type Draft } from '../schema/config'

const draft = defineModel<Draft>({ required: true })
const props = defineProps<{
  fields: ConfigField[]
  /** False when the plugin's folder cannot be read, so its parameters are unknown. */
  readable: boolean
  sceneChoices: string[]
  enabledScenes?: string[]
  configured: Record<string, boolean>
  problems: Record<string, string>
  /** Incremented by the parent when the draft is discarded or reloaded from server. */
  resetKey?: number
  onEnablePicked?: (scenes: string[]) => void | Promise<void>
  enablingPicked?: boolean
}>()
const emit = defineEmits<{ 'update:jsonError': [error: string | null] }>()

const { t } = useI18n()
const mode = ref<'form' | 'json'>('form')
const jsonText = ref('')
const jsonError = ref<string | null>(null)
const copied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(copyTimer))

function setJsonError(value: string | null) {
  if (jsonError.value !== value) {
    jsonError.value = value
    emit('update:jsonError', value)
  }
}

const modeOptions = computed(() => [
  { value: 'form' as const, label: t('plugins.form.modeForm'), disabled: Boolean(jsonError.value) },
  { value: 'json' as const, label: t('plugins.form.modeJson') },
])

watch(mode, (next) => {
  if (next === 'json') {
    jsonText.value = draftToJson(props.fields, draft.value, props.configured)
    setJsonError(null)
  }
})
watch([() => props.resetKey, () => props.fields], () => {
  if (mode.value === 'json') {
    jsonText.value = draftToJson(props.fields, draft.value, props.configured)
  }
  setJsonError(null)
})

function onJsonInput(value: string) {
  jsonText.value = value
  const parsed = jsonToDraft(props.fields, value, props.configured, t)
  if ('error' in parsed) {
    setJsonError(parsed.error)
    return
  }
  setJsonError(null)
  draft.value = parsed.draft
}

function formatJson() {
  const parsed = jsonToDraft(props.fields, jsonText.value, props.configured, t)
  if ('error' in parsed) {
    setJsonError(parsed.error)
    return
  }
  setJsonError(null)
  draft.value = parsed.draft
  jsonText.value = draftToJson(props.fields, parsed.draft, props.configured)
}

async function copyJson() {
  if (jsonError.value) return
  const sanitized = draftToJson(props.fields, draft.value, props.configured, { redactSecrets: true })
  try {
    await navigator.clipboard.writeText(sanitized)
    copied.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => (copied.value = false), 1800)
  } catch {
    // Clipboard unavailable outside secure contexts.
  }
}

const canResetAll = computed(() => {
  if (jsonError.value) return true
  return props.fields.some(
    (field) =>
      hasDefault(field) &&
      JSON.stringify(draft.value[field.key]) !== JSON.stringify(initialField(field, field.default)),
  )
})
function resetAll() {
  const next: Draft = { ...draft.value }
  for (const field of props.fields) {
    if (hasDefault(field)) next[field.key] = initialField(field, field.default)
  }
  draft.value = next
  if (mode.value === 'json') {
    jsonText.value = draftToJson(props.fields, next, props.configured)
    setJsonError(null)
  }
}

const problemMessages = computed(() => Object.values(props.problems))
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <template v-if="readable && fields.length">
      <div class="flex flex-wrap items-center justify-end gap-2">
        <template v-if="mode === 'json'">
          <Button
            size="sm"
            variant="ghost"
            :icon="AlignLeft"
            :disabled="Boolean(jsonError)"
            @click="formatJson"
          >
            {{ t('plugins.form.formatJson') }}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            :icon="copied ? Check : Copy"
            :disabled="Boolean(jsonError)"
            @click="copyJson"
          >
            {{ copied ? t('common.copied') : t('plugins.form.copyJson') }}
          </Button>
        </template>
        <Button size="sm" variant="ghost" :icon="RotateCcw" :disabled="!canResetAll" @click="resetAll">
          {{ t('plugins.form.resetAll') }}
        </Button>
        <SegmentedControl
          v-model="mode"
          :options="modeOptions"
          size="sm"
          :label="t('plugins.form.modeForm')"
        />
      </div>

      <SchemaForm
        v-if="mode === 'form'"
        v-model="draft"
        :fields="fields"
        :scene-choices="sceneChoices"
        :enabled-scenes="enabledScenes"
        :configured="configured"
        :problems="problems"
        :on-enable-picked="onEnablePicked"
        :enabling-picked="enablingPicked"
      />
      <div v-else class="flex min-w-0 max-w-3xl flex-col gap-2">
        <Textarea
          :model-value="jsonText"
          :rows="14"
          :max-rows="36"
          mono
          spellcheck="false"
          :invalid="Boolean(jsonError || problemMessages.length)"
          :aria-label="t('plugins.form.modeJson')"
          @update:model-value="onJsonInput"
        />
        <p v-if="jsonError" role="alert" class="text-xs font-medium text-error">
          {{ jsonError }}
        </p>
        <ul
          v-else-if="problemMessages.length"
          role="alert"
          class="flex list-none flex-col gap-1 text-xs font-medium text-error"
        >
          <li v-for="(message, index) in problemMessages" :key="index">{{ message }}</li>
        </ul>
      </div>
    </template>
    <EmptyState
      v-else
      :icon="SlidersHorizontal"
      :title="readable ? t('plugins.detail.noFields') : t('plugins.detail.unreadable')"
      compact
    />
  </div>
</template>
