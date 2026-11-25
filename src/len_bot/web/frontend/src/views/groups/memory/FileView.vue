<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { History, Pencil, Trash2 } from '@lucide/vue'
import { memoryApi, type MemoryScope, type MemoryState } from '../../../api/memory'
import { keys } from '../../../api/query'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import MarkdownText from '../../../ui/MarkdownText.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import DeleteDialog from './DeleteDialog.vue'
import HistoryDialog from './HistoryDialog.vue'

const props = defineProps<{
  scene: string
  scope: MemoryScope
  /** null while creating a new file in `directory`. */
  path: string | null
  directory: string
  state: MemoryState
  timeZone: string
}>()
const emit = defineEmits<{ dirty: [value: boolean]; changed: [path: string | null]; close: [] }>()

const { t } = useI18n()
const client = useQueryClient()
const can = (action: string) => props.state.actions.includes(action)
const writable = computed(() => can('write') && (props.scope === 'scene' || props.state.public_writable))
const inScene = computed(() => props.scope === 'scene')

const doc = useQuery({
  queryKey: computed(() => keys.memory.file(props.scene, props.scope, props.path ?? '')),
  queryFn: ({ signal }) => memoryApi.read(props.scene, props.scope, props.path!, signal),
  enabled: props.path !== null,
})
const original = computed(() => doc.data.value?.content ?? '')
const editing = ref(props.path === null)
const editorMode = ref<'edit' | 'preview'>('edit')
const editorModes = computed(() => [
  { value: 'edit' as const, label: t('groups.memory.file.modes.edit') },
  { value: 'preview' as const, label: t('groups.memory.file.modes.preview') },
])
const content = ref('')
const baseContent = ref<string | null>(props.path === null ? '' : null)
const remoteUpdated = ref(false)
const reason = ref('')
const initialPath = props.directory ? `${props.directory}/` : ''
const newPath = ref(initialPath)
const pathTouched = ref(false)
const reasonTouched = ref(false)

const dirty = computed(
  () =>
    editing.value &&
    (content.value !== (baseContent.value ?? original.value) ||
      reason.value !== '' ||
      (props.path === null && newPath.value !== initialPath)),
)

function normalizeNewPath() {
  pathTouched.value = true
  const trimmed = newPath.value.trim()
  if (!trimmed || trimmed.endsWith('/')) {
    newPath.value = trimmed
    return
  }
  if (!trimmed.endsWith('.md')) {
    newPath.value = `${trimmed}.md`
    return
  }
  newPath.value = trimmed
}

function validatePath(raw: string, requireSuffix: boolean): string | null {
  const trimmed = raw.trim()
  if (!trimmed) return t('common.required')
  if (trimmed.startsWith('/') || trimmed.endsWith('/')) return t('groups.memory.file.invalidPath')
  const segments = trimmed.split('/')
  if (segments.some((seg) => !seg || seg === '.' || seg === '..')) return t('groups.memory.file.invalidPath')
  const filename = segments[segments.length - 1] ?? ''
  if (filename.endsWith('.md')) {
    if (!filename.slice(0, -3).trim()) return t('groups.memory.file.invalidPath')
    return null
  }
  return requireSuffix ? t('groups.memory.file.invalidPath') : null
}

const pathError = computed(() =>
  props.path === null ? validatePath(newPath.value, pathTouched.value) : null,
)
const shownPathError = computed(() => (pathTouched.value || dirty.value ? pathError.value : null))
const reasonError = computed(() => (reason.value.trim() ? null : t('common.required')))
const shownReasonError = computed(() => (reasonTouched.value || dirty.value ? reasonError.value : null))
const invalid = computed(() =>
  Boolean((props.path === null && validatePath(newPath.value, false)) || reasonError.value),
)

function reloadRemote() {
  content.value = original.value
  baseContent.value = doc.data.value ? original.value : props.path === null ? '' : null
  remoteUpdated.value = false
}
function startEdit() {
  reloadRemote()
  editorMode.value = 'edit'
  reasonTouched.value = false
  pathTouched.value = false
  save.reset()
  editing.value = true
}
watch(
  () => [props.scene, props.scope, props.path] as const,
  () => {
    baseContent.value = props.path === null ? '' : doc.data.value ? original.value : null
    content.value = props.path === null ? '' : original.value
    remoteUpdated.value = false
    editorMode.value = 'edit'
    pathTouched.value = false
    reasonTouched.value = false
  },
)
watch(
  () => doc.data.value,
  (next) => {
    if (!next) return
    if (baseContent.value === null) {
      baseContent.value = next.content
      content.value = next.content
      remoteUpdated.value = false
      return
    }
    if (next.content === baseContent.value) {
      remoteUpdated.value = false
      return
    }
    if (!dirty.value) {
      baseContent.value = next.content
      content.value = next.content
      remoteUpdated.value = false
      return
    }
    remoteUpdated.value = true
  },
  { immediate: true },
)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const save = useMutation({
  mutationFn: () =>
    memoryApi.write({
      scene: props.scene,
      scope: props.scope,
      path: props.path ?? newPath.value.trim(),
      content: content.value,
      reason: reason.value.trim(),
    }),
  onSuccess: (result) => {
    const path = props.path ?? newPath.value.trim()
    client.setQueryData(keys.memory.file(props.scene, props.scope, path), { path, content: result.after })
    const dirs = path.split('/').slice(0, -1)
    for (let i = 0; i <= dirs.length; i++) {
      void client.invalidateQueries({
        queryKey: keys.memory.summary(props.scene, props.scope, dirs.slice(0, i).join('/')),
      })
    }
    if (props.scope === 'scene') {
      void client.invalidateQueries({ queryKey: keys.memory.history(props.scene, path) })
    }
    baseContent.value = result.after
    content.value = result.after
    remoteUpdated.value = false
    reason.value = ''
    pathTouched.value = false
    reasonTouched.value = false
    editorMode.value = 'edit'
    editing.value = false
    toast.success(t('common.saved'))
    emit('changed', path)
  },
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

function submit() {
  if (props.path === null) normalizeNewPath()
  reasonTouched.value = true
  if (props.path === null && validatePath(newPath.value, true)) return
  if (reasonError.value) return
  save.mutate()
}

function discard() {
  save.reset()
  reason.value = ''
  pathTouched.value = false
  reasonTouched.value = false
  editorMode.value = 'edit'
  if (props.path === null) {
    newPath.value = initialPath
    content.value = ''
    emit('dirty', false)
    emit('close')
    return
  }
  reloadRemote()
  editing.value = false
}

async function cancel() {
  if (dirty.value && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') })))
    return
  discard()
}

const removing = ref(false)
const historyOpen = ref(false)
function removed() {
  removing.value = false
  void client.invalidateQueries({ queryKey: keys.memory.all() })
  emit('changed', null)
}
</script>

<template>
  <form v-if="editing" class="flex max-w-3xl flex-col gap-4 pb-6" @submit.prevent="submit">
    <header class="flex min-h-8 flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
      <h3 class="min-w-0 flex-1 truncate font-mono text-sm font-medium text-ink">
        {{ path ?? t('groups.memory.create') }}
      </h3>
      <div class="flex shrink-0 items-center gap-2">
        <SegmentedControl
          v-model="editorMode"
          :options="editorModes"
          size="sm"
          :label="t('groups.memory.file.mode')"
        />
        <Button size="sm" variant="ghost" :disabled="save.isPending.value" @click="cancel">
          {{ t('common.cancel') }}
        </Button>
      </div>
    </header>
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
    <Field v-if="path === null" :label="t('groups.memory.file.path')" :error="shownPathError" required>
      <Input v-model="newPath" placeholder="people/name.md" mono @blur="normalizeNewPath" />
    </Field>
    <Field :label="t('groups.memory.file.content')">
      <Textarea v-if="editorMode === 'edit'" v-model="content" :rows="12" :max-rows="30" mono />
      <div v-else class="min-h-60 rounded-md border border-line bg-surface px-3.5 py-3">
        <MarkdownText v-if="content.trim()" :text="content" class="text-base leading-7 text-ink" />
        <p v-else class="text-sm text-muted">{{ t('groups.memory.file.previewEmpty') }}</p>
      </div>
    </Field>
    <Field :label="t('groups.memory.file.reason')" :error="shownReasonError" required>
      <Input v-model="reason" @blur="reasonTouched = true" />
    </Field>
    <SaveBar
      :dirty="dirty"
      :saving="save.isPending.value"
      :error="saveError"
      :raw-error="saveRawError"
      :invalid="invalid"
      @save="submit"
      @discard="discard"
    />
  </form>
  <article v-else class="flex min-w-0 flex-col gap-4">
    <header class="flex min-h-8 flex-wrap items-center gap-2 border-b border-line pb-3">
      <h3 class="min-w-0 flex-1 truncate font-mono text-sm font-medium text-ink" :title="path ?? ''">
        {{ path }}
      </h3>
      <div class="flex flex-wrap items-center gap-1.5">
        <Button v-if="writable && doc.data.value" size="sm" :icon="Pencil" @click="startEdit">
          {{ t('common.edit') }}
        </Button>
        <Button
          v-if="inScene && can('history')"
          size="sm"
          variant="ghost"
          :icon="History"
          @click="historyOpen = true"
        >
          {{ t('groups.memory.history.action') }}
        </Button>
        <Button
          v-if="inScene && (can('delete') || can('forget')) && doc.data.value"
          size="sm"
          variant="danger-ghost"
          :icon="Trash2"
          @click="removing = true"
        >
          {{ t('common.delete') }}
        </Button>
      </div>
    </header>
    <Skeleton v-if="doc.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="doc.isError.value"
      :title="t('groups.memory.readFailed')"
      :error="doc.error.value"
      :retry="doc.refetch"
    />
    <MarkdownText v-else :text="original" class="max-w-3xl text-base leading-7 text-ink" />

    <DeleteDialog
      v-if="path"
      v-model:open="removing"
      :scene="scene"
      :path="path"
      :can-delete="can('delete')"
      :can-forget="can('forget')"
      @removed="removed"
    />
    <HistoryDialog v-if="path" v-model:open="historyOpen" :scene="scene" :path="path" :time-zone="timeZone" />
  </article>
</template>
