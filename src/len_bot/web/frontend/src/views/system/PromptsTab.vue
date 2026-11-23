<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RotateCcw } from '@lucide/vue'
import { keys } from '../../api/query'
import { systemApi, type PromptDocument, type PromptSummary } from '../../api/system'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import { readPendingRestart } from '../../api/hostStore'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import Checkbox from '../../ui/Checkbox.vue'
import Combobox from '../../ui/Combobox.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Textarea from '../../ui/Textarea.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const overview = useQuery({
  queryKey: keys.system.prompts(),
  queryFn: ({ signal }) => systemApi.prompts(signal),
})
const items = computed(() => overview.data.value?.items ?? [])
const options = computed(() =>
  items.value.map((item) => ({
    value: item.name,
    label: item.name,
    meta: item.edited ? t('system.prompts.edited') : undefined,
  })),
)
const name = computed({
  get: () => {
    const value = route.query.item
    return typeof value === 'string' && items.value.some((item) => item.name === value) ? value : undefined
  },
  set: (value: string | undefined) => void router.replace({ query: { ...route.query, item: value } }),
})
const document = useQuery({
  queryKey: computed(() => keys.system.prompt(name.value ?? '')),
  queryFn: ({ signal }) => systemApi.prompt(name.value!, signal),
  enabled: computed(() => Boolean(name.value)),
  staleTime: Infinity,
})
const draft = ref('')
const baseName = ref<string | undefined>(undefined)
const baseText = ref<string | null>(null)
const remoteUpdated = ref(false)
const dirty = computed(
  () => Boolean(document.data.value) && baseText.value !== null && draft.value !== baseText.value,
)
function reloadRemote() {
  const next = document.data.value
  if (!next) return
  baseName.value = next.name
  baseText.value = next.text
  draft.value = next.text
  remoteUpdated.value = false
}
watch(
  () => document.data.value,
  (next) => {
    if (!next) {
      if (!name.value) {
        baseName.value = undefined
        baseText.value = null
        draft.value = ''
        remoteUpdated.value = false
      }
      return
    }
    if (baseName.value !== next.name || baseText.value === null) {
      baseName.value = next.name
      baseText.value = next.text
      draft.value = next.text
      remoteUpdated.value = false
      return
    }
    if (next.text === baseText.value) {
      remoteUpdated.value = false
      return
    }
    if (!dirty.value) {
      baseText.value = next.text
      draft.value = next.text
      remoteUpdated.value = false
      return
    }
    remoteUpdated.value = true
  },
  { immediate: true },
)
useUnsavedChanges(dirty, { keep: ['tab'] })

const outdated = computed(() => {
  const value = overview.data.value
  return value?.edited_version && value.edited_version !== value.version ? value : null
})
const editedCount = computed(() => items.value.filter((item) => item.edited).length)
/** Placeholders the default text uses; the backend refuses a text that drops one. */
const missing = computed(() =>
  (document.data.value?.placeholders ?? []).filter(
    (key) => !new RegExp(`\\$(${key}(?![A-Za-z0-9_])|\\{${key}\\})`).test(draft.value),
  ),
)

function adopt(summary: PromptSummary, text: string) {
  client.setQueryData(keys.system.prompts(), summary)
  const current = document.data.value as PromptDocument
  client.setQueryData(keys.system.prompt(current.name), {
    ...current,
    text,
    edited: text !== current.default,
  })
  baseName.value = current.name
  baseText.value = text
  draft.value = text
  remoteUpdated.value = false
  void readPendingRestart()
}
const save = useMutation({
  mutationFn: (text: string) => systemApi.savePrompt(name.value!, text),
  onSuccess: (summary, text) => {
    adopt(summary, text)
    toast.success(t('common.saved'))
  },
})
const restore = useMutation({
  mutationFn: () => systemApi.resetPrompt(name.value!),
  onSuccess: (summary) => {
    adopt(summary, document.data.value!.default)
    toast.success(t('system.prompts.restored'))
  },
  onError: (error) =>
    toast.error(t('system.prompts.restoreFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
async function confirmRestore() {
  const sure = await confirm({
    title: t('system.prompts.restoreTitle'),
    message: t('system.prompts.restoreMessage', { name: name.value }),
    confirmLabel: t('system.prompts.restore'),
    tone: 'danger',
  })
  if (sure) restore.mutate()
}
const keep = useMutation({
  mutationFn: (value: boolean) => systemApi.keepPrompts(value),
  onSuccess: (summary) => client.setQueryData(keys.system.prompts(), summary),
  onError: (error) =>
    toast.error(t('system.prompts.keepFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
const saveDescribed = computed(() =>
  save.isError.value ? describeError(save.error.value, t('ui.error.network')) : null,
)
const saveError = computed(() => saveDescribed.value?.message ?? null)
const saveRawError = computed(() => {
  const described = saveDescribed.value
  if (!described || described.raw === null || described.raw === described.message) return null
  return described.status === null ? described.raw : `HTTP ${described.status}\n${described.raw}`
})
</script>

<template>
  <Skeleton v-if="overview.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="overview.isError.value"
    :title="t('system.prompts.readFailed')"
    :error="overview.error.value"
    :retry="overview.refetch"
  />
  <div v-else-if="overview.data.value" class="flex min-w-0 max-w-4xl flex-col gap-5">
    <p v-if="outdated" class="rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning tabular">
      {{
        t(
          'system.prompts.outdated',
          { n: editedCount, edited: outdated.edited_version, current: outdated.version },
          editedCount,
        )
      }}
    </p>
    <div class="flex min-w-0 flex-col gap-5">
      <div class="flex flex-wrap items-end justify-between gap-4">
        <div class="w-full sm:w-96">
          <Field :label="t('system.prompts.file')">
            <Combobox v-model="name" :options="options" :placeholder="t('system.prompts.pick')" />
          </Field>
        </div>
        <div class="pb-1.5">
          <Checkbox
            :model-value="overview.data.value.keep_on_update"
            :disabled="keep.isPending.value"
            @update:model-value="(value) => keep.mutate(value === true)"
          >
            {{ t('system.prompts.keep') }}
          </Checkbox>
        </div>
      </div>
      <Skeleton v-if="name && document.isPending.value" :lines="10" />
      <ErrorNote
        v-else-if="document.isError.value"
        :title="t('system.prompts.fileFailed')"
        :error="document.error.value"
        :retry="document.refetch"
      />
      <template v-else-if="name && document.data.value">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p
            v-if="document.data.value.placeholders.length"
            class="flex min-w-0 flex-wrap items-center gap-1.5 text-sm text-muted"
          >
            {{ t('system.prompts.placeholders') }}
            <Badge
              v-for="key in document.data.value.placeholders"
              :key="key"
              :tone="missing.includes(key) ? 'error' : 'neutral'"
            >
              <span class="font-mono">${{ key }}</span>
            </Badge>
          </p>
          <Button
            v-if="document.data.value.edited && !dirty"
            size="sm"
            variant="ghost"
            :icon="RotateCcw"
            :loading="restore.isPending.value"
            @click="confirmRestore"
          >
            {{ t('system.prompts.restore') }}
          </Button>
        </div>
        <div
          v-if="remoteUpdated"
          role="status"
          class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
        >
          <span class="min-w-0 flex-1">{{ t('ui.draft.remoteUpdated') }}</span>
          <Button size="sm" variant="ghost" @click="reloadRemote">
            {{ t('ui.draft.reloadRemote') }}
          </Button>
        </div>
        <Textarea
          v-model="draft"
          :rows="18"
          :max-rows="40"
          mono
          spellcheck="false"
          :aria-label="name"
          :invalid="missing.length > 0"
        />
        <p v-if="missing.length" role="alert" class="text-sm text-error">
          {{ t('system.prompts.missing', { keys: missing.map((key) => `$${key}`).join(', ') }) }}
        </p>
      </template>
    </div>
    <SaveBar
      :dirty="dirty"
      :saving="save.isPending.value"
      :error="saveError"
      :raw-error="saveRawError"
      :invalid="missing.length > 0"
      @save="save.mutate(draft)"
      @discard="reloadRemote"
    />
  </div>
</template>
