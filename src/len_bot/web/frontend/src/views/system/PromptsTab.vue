<script setup lang="ts">
import { computed, nextTick, onActivated, onDeactivated, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RotateCcw } from '@lucide/vue'
import { keys } from '../../api/query'
import { systemApi, type PromptDocument, type PromptSummary } from '../../api/system'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import { readPendingRestart } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import Button from '../../ui/Button.vue'
import Checkbox from '../../ui/Checkbox.vue'
import Combobox from '../../ui/Combobox.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import SaveBar from '../../ui/SaveBar.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import Textarea from '../../ui/Textarea.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

const emit = defineEmits<{ dirty: [value: boolean] }>()

interface DiffLine {
  kind: 'same' | 'add' | 'del'
  oldLine: number | null
  newLine: number | null
  text: string
}

/** Single-column line-level diff between bundled default text and the current draft. */
function diffLines(beforeText: string, afterText: string): DiffLine[] {
  const before = beforeText === '' ? [] : beforeText.split('\n')
  const after = afterText === '' ? [] : afterText.split('\n')
  let prefix = 0
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) prefix += 1
  let suffix = 0
  while (
    suffix < before.length - prefix &&
    suffix < after.length - prefix &&
    before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  )
    suffix += 1

  const result: DiffLine[] = []
  for (let i = 0; i < prefix; i += 1)
    result.push({ kind: 'same', oldLine: i + 1, newLine: i + 1, text: before[i]! })

  const midA = before.slice(prefix, before.length - suffix)
  const midB = after.slice(prefix, after.length - suffix)
  const m = midA.length
  const n = midB.length

  if (m === 0) {
    for (let j = 0; j < n; j += 1)
      result.push({ kind: 'add', oldLine: null, newLine: prefix + j + 1, text: midB[j]! })
  } else if (n === 0) {
    for (let i = 0; i < m; i += 1)
      result.push({ kind: 'del', oldLine: prefix + i + 1, newLine: null, text: midA[i]! })
  } else if (m * n > 400_000) {
    for (let i = 0; i < m; i += 1)
      result.push({ kind: 'del', oldLine: prefix + i + 1, newLine: null, text: midA[i]! })
    for (let j = 0; j < n; j += 1)
      result.push({ kind: 'add', oldLine: null, newLine: prefix + j + 1, text: midB[j]! })
  } else {
    const stride = n + 1
    const dp = new Uint32Array((m + 1) * stride)
    for (let i = m - 1; i >= 0; i -= 1) {
      for (let j = n - 1; j >= 0; j -= 1) {
        dp[i * stride + j] =
          midA[i] === midB[j]
            ? dp[(i + 1) * stride + (j + 1)]! + 1
            : Math.max(dp[(i + 1) * stride + j]!, dp[i * stride + (j + 1)]!)
      }
    }
    let i = 0
    let j = 0
    while (i < m && j < n) {
      if (midA[i] === midB[j]) {
        result.push({ kind: 'same', oldLine: prefix + i + 1, newLine: prefix + j + 1, text: midA[i]! })
        i += 1
        j += 1
      } else if (dp[(i + 1) * stride + j]! >= dp[i * stride + (j + 1)]!) {
        result.push({ kind: 'del', oldLine: prefix + i + 1, newLine: null, text: midA[i]! })
        i += 1
      } else {
        result.push({ kind: 'add', oldLine: null, newLine: prefix + j + 1, text: midB[j]! })
        j += 1
      }
    }
    while (i < m) {
      result.push({ kind: 'del', oldLine: prefix + i + 1, newLine: null, text: midA[i]! })
      i += 1
    }
    while (j < n) {
      result.push({ kind: 'add', oldLine: null, newLine: prefix + j + 1, text: midB[j]! })
      j += 1
    }
  }

  for (let k = 0; k < suffix; k += 1) {
    const oldIndex = before.length - suffix + k
    const newIndex = after.length - suffix + k
    result.push({ kind: 'same', oldLine: oldIndex + 1, newLine: newIndex + 1, text: before[oldIndex]! })
  }
  return result
}

/** Matches Python string.Template placeholders while ignoring even-count `$` escapes such as `$$key`. */
function placeholderMatches(text: string, key: string): { start: number; end: number }[] {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const pattern = new RegExp(`(?<!\\$)(?:\\$\\$)*(\\$(?:${escaped}(?![A-Za-z0-9_])|\\{${escaped}\\}))`, 'g')
  const found: { start: number; end: number }[] = []
  for (const match of text.matchAll(pattern)) {
    const token = match[1]!
    const start = (match.index ?? 0) + match[0].length - token.length
    found.push({ start, end: start + token.length })
  }
  return found
}

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const active = ref(true)
onActivated(() => {
  active.value = true
  ensureSelected()
})
onDeactivated(() => {
  active.value = false
})

const overview = useQuery({
  queryKey: keys.system.prompts(),
  queryFn: ({ signal }) => systemApi.prompts(signal),
})
const items = computed(() => overview.data.value?.items ?? [])
const onlyEdited = ref(false)
const selectedName = ref<string | undefined>(undefined)
const name = computed(() =>
  selectedName.value && items.value.some((item) => item.name === selectedName.value)
    ? selectedName.value
    : undefined,
)
function syncQueryItem(target: string | undefined) {
  if (!active.value || route.query.tab !== 'prompts') return
  if (route.query.item === target) return
  void router.replace({ query: { ...route.query, tab: 'prompts', item: target } })
}
function ensureSelected() {
  if (!active.value || route.query.tab !== 'prompts') return
  const fromQuery =
    typeof route.query.item === 'string' && items.value.some((item) => item.name === route.query.item)
      ? route.query.item
      : undefined
  if (fromQuery) {
    selectedName.value = fromQuery
    return
  }
  if (selectedName.value && items.value.some((item) => item.name === selectedName.value)) {
    syncQueryItem(selectedName.value)
    return
  }
  if (!items.value.length) return
  const picked = items.value.find((item) => item.edited) ?? items.value[0]!
  selectedName.value = picked.name
  syncQueryItem(picked.name)
}
watch(() => [route.query.tab, route.query.item, items.value] as const, ensureSelected, { immediate: true })
const options = computed(() =>
  items.value
    .filter((item) => !onlyEdited.value || item.edited || item.name === name.value)
    .map((item) => ({
      value: item.name,
      label: item.name,
      meta: item.edited ? t('system.prompts.edited') : undefined,
    })),
)

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
const viewMode = ref<'edit' | 'diff'>('edit')
const viewModes = computed(() => [
  { value: 'edit' as const, label: t('system.prompts.modes.edit') },
  { value: 'diff' as const, label: t('system.prompts.modes.diff') },
])
const editor = ref<InstanceType<typeof Textarea>>()

const dirty = computed(
  () => Boolean(document.data.value) && baseText.value !== null && draft.value !== baseText.value,
)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

watch(onlyEdited, (on) => {
  if (!on || dirty.value) return
  const current = items.value.find((item) => item.name === name.value)
  if (current?.edited) return
  const firstEdited = items.value.find((item) => item.edited)
  if (firstEdited) {
    selectedName.value = firstEdited.name
    syncQueryItem(firstEdited.name)
  }
})

async function selectPrompt(next: string | string[] | undefined) {
  if (typeof next !== 'string' || !next || next === selectedName.value) return
  if (dirty.value) {
    const leave = await confirm({
      title: t('ui.unsaved.title'),
      message: t('ui.unsaved.message'),
      confirmLabel: t('common.discard'),
      tone: 'danger',
    })
    if (!leave) return
  }
  selectedName.value = next
  syncQueryItem(next)
}

function reloadRemote() {
  const next = document.data.value
  if (!next) return
  baseName.value = next.name
  baseText.value = next.text
  draft.value = next.text
  remoteUpdated.value = false
  if (save.isError.value) save.reset()
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
useUnsavedChanges(dirty, { keep: ['tab', 'item'] })

const outdated = computed(() => {
  const value = overview.data.value
  return value?.edited_version && value.edited_version !== value.version ? value : null
})
const editedCount = computed(() => items.value.filter((item) => item.edited).length)

/** Placeholders the default text uses; the backend refuses a text that drops one. */
const missing = computed(() =>
  (document.data.value?.placeholders ?? []).filter(
    (key) => placeholderMatches(draft.value, key).length === 0,
  ),
)

const diff = computed(() => {
  const doc = document.data.value
  if (!doc || viewMode.value !== 'diff') return []
  return diffLines(doc.default, draft.value)
})
const diffStats = computed(() => {
  let added = 0
  let removed = 0
  for (const row of diff.value) {
    if (row.kind === 'add') added += 1
    else if (row.kind === 'del') removed += 1
  }
  return { added, removed }
})

function scrollTextareaToOffset(el: HTMLTextAreaElement, offset: number) {
  const before = el.value.slice(0, offset)
  const line = before.split('\n').length - 1
  const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 20
  const targetTop = Math.max(0, line * lineHeight - el.clientHeight / 3)
  el.scrollTop = targetTop
}

async function onPlaceholderClick(key: string) {
  if (viewMode.value !== 'edit') {
    viewMode.value = 'edit'
    await nextTick()
  }
  const el = editor.value?.$el as HTMLTextAreaElement | undefined
  const matches = placeholderMatches(draft.value, key)
  if (!matches.length) {
    const inserted = `\${${key}}`
    const start = el ? el.selectionStart : draft.value.length
    const end = el ? el.selectionEnd : draft.value.length
    draft.value = draft.value.slice(0, start) + inserted + draft.value.slice(end)
    await nextTick()
    if (el) {
      el.focus()
      el.setSelectionRange(start, start + inserted.length)
      scrollTextareaToOffset(el, start)
    }
    return
  }
  const cursor = el?.selectionEnd ?? 0
  const target = matches.find((item) => item.start >= cursor) ?? matches[0]!
  if (el) {
    el.focus()
    el.setSelectionRange(target.start, target.end)
    scrollTextareaToOffset(el, target.start)
  }
}

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
watch([draft, name], () => {
  if (save.isError.value) save.reset()
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
            <Combobox
              :model-value="name"
              :options="options"
              :placeholder="t('system.prompts.pick')"
              @update:model-value="selectPrompt"
            />
          </Field>
        </div>
        <div class="flex flex-wrap items-center gap-4 pb-1">
          <Field :label="t('system.prompts.onlyEdited')" inline>
            <Switch v-model="onlyEdited" />
          </Field>
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
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex flex-wrap items-center gap-2">
            <SegmentedControl
              v-model="viewMode"
              :options="viewModes"
              size="sm"
              :label="t('system.prompts.file')"
            />
            <Button
              v-if="document.data.value.edited"
              size="sm"
              variant="ghost"
              :icon="RotateCcw"
              :loading="restore.isPending.value"
              @click="confirmRestore"
            >
              {{ t('system.prompts.restore') }}
            </Button>
          </div>
          <p
            v-if="document.data.value.placeholders.length"
            class="flex min-w-0 flex-wrap items-center gap-1.5 text-sm text-muted"
          >
            {{ t('system.prompts.placeholders') }}
            <button
              v-for="key in document.data.value.placeholders"
              :key="key"
              type="button"
              class="inline-flex h-5 cursor-pointer items-center rounded-full px-2 font-mono text-xs font-medium transition-colors focus-visible:focus-ring"
              :class="
                missing.includes(key)
                  ? 'bg-error-bg text-error hover:bg-error-line/70'
                  : 'bg-fill text-ink-2 hover:bg-hover hover:text-ink'
              "
              :title="
                missing.includes(key)
                  ? t('system.prompts.insertPlaceholder', { key: `\${${key}}` })
                  : t('system.prompts.locatePlaceholder', { key: `$${key}` })
              "
              @click="onPlaceholderClick(key)"
            >
              ${{ key }}
            </button>
          </p>
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
          v-if="viewMode === 'edit'"
          ref="editor"
          v-model="draft"
          :rows="18"
          :max-rows="40"
          mono
          spellcheck="false"
          :aria-label="name"
          :invalid="missing.length > 0"
        />
        <div v-else class="flex min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-surface">
          <div v-if="draft === document.data.value.default" class="px-4 py-6 text-center text-sm text-muted">
            {{ t('system.prompts.diffSame') }}
          </div>
          <template v-else>
            <div
              class="flex items-center gap-3 border-b border-line bg-fill px-3.5 py-2 font-mono text-xs tabular"
            >
              <span class="font-medium text-success">+{{ formatNumber(diffStats.added) }}</span>
              <span class="font-medium text-error">-{{ formatNumber(diffStats.removed) }}</span>
            </div>
            <div class="max-h-[34rem] overflow-auto font-mono text-xs leading-5 scrollbar-thin">
              <div
                v-for="(line, index) in diff"
                :key="index"
                class="flex min-w-0 px-2 py-px"
                :class="
                  line.kind === 'add'
                    ? 'bg-success-bg/70 text-ink'
                    : line.kind === 'del'
                      ? 'bg-error-bg/70 text-ink'
                      : 'text-ink-2'
                "
              >
                <span class="w-9 shrink-0 pr-2 text-right text-subtle tabular select-none">
                  {{ line.oldLine ?? '' }}
                </span>
                <span class="w-9 shrink-0 pr-2 text-right text-subtle tabular select-none">
                  {{ line.newLine ?? '' }}
                </span>
                <span
                  class="w-4 shrink-0 text-center select-none"
                  :class="
                    line.kind === 'add'
                      ? 'font-semibold text-success'
                      : line.kind === 'del'
                        ? 'font-semibold text-error'
                        : 'text-subtle'
                  "
                >
                  {{ line.kind === 'add' ? '+' : line.kind === 'del' ? '-' : ' ' }}
                </span>
                <span class="min-w-0 flex-1 break-words whitespace-pre-wrap">{{ line.text || ' ' }}</span>
              </div>
            </div>
          </template>
        </div>
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
