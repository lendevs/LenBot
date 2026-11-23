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
import Skeleton from '../../../ui/Skeleton.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
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
const content = ref('')
const baseContent = ref<string | null>(props.path === null ? '' : null)
const remoteUpdated = ref(false)
const reason = ref('')
const initialPath = props.directory ? `${props.directory}/` : ''
const newPath = ref(initialPath)
const dirty = computed(
  () =>
    editing.value &&
    (content.value !== (baseContent.value ?? original.value) ||
      reason.value !== '' ||
      (props.path === null && newPath.value !== initialPath)),
)
function reloadRemote() {
  content.value = original.value
  baseContent.value = doc.data.value ? original.value : props.path === null ? '' : null
  remoteUpdated.value = false
}
function startEdit() {
  reloadRemote()
  editing.value = true
}
watch(
  () => [props.scene, props.scope, props.path] as const,
  () => {
    baseContent.value = props.path === null ? '' : doc.data.value ? original.value : null
    content.value = props.path === null ? '' : original.value
    remoteUpdated.value = false
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
    baseContent.value = result.after
    content.value = result.after
    remoteUpdated.value = false
    reason.value = ''
    editing.value = false
    toast.success(t('common.saved'))
    emit('changed', path)
  },
})
async function cancel() {
  if (dirty.value && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') })))
    return
  if (props.path === null) return emit('close')
  reloadRemote()
  reason.value = ''
  editing.value = false
}
const canSave = computed(
  () => reason.value.trim() !== '' && (props.path !== null || newPath.value.trim().endsWith('.md')),
)

const removing = ref(false)
const historyOpen = ref(false)
function removed() {
  removing.value = false
  void client.invalidateQueries({ queryKey: keys.memory.all() })
  emit('changed', null)
}
</script>

<template>
  <form v-if="editing" class="flex max-w-3xl flex-col gap-4" @submit.prevent="canSave && save.mutate()">
    <header class="flex min-h-8 items-center border-b border-line pb-3">
      <h3 class="min-w-0 truncate font-mono text-sm font-medium text-ink">
        {{ path ?? t('groups.memory.create') }}
      </h3>
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
    <Field v-if="path === null" :label="t('groups.memory.file.path')">
      <Input v-model="newPath" placeholder="people/name.md" mono />
    </Field>
    <Field :label="t('groups.memory.file.content')">
      <Textarea v-model="content" :rows="12" :max-rows="30" mono />
    </Field>
    <Field :label="t('groups.memory.file.reason')">
      <Input v-model="reason" />
    </Field>
    <ErrorNote
      v-if="save.isError.value"
      :title="t('groups.memory.file.saveFailed')"
      :error="save.error.value"
    />
    <div class="flex justify-end gap-2">
      <Button variant="ghost" :disabled="save.isPending.value" @click="cancel">
        {{ t('common.cancel') }}
      </Button>
      <Button type="submit" variant="primary" :loading="save.isPending.value" :disabled="!canSave">
        {{ t('common.save') }}
      </Button>
    </div>
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
