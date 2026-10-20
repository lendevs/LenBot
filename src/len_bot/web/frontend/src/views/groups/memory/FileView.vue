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
import Skeleton from '../../../ui/Skeleton.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { toast } from '../../../ui/toast'
import AdoptDialog from './AdoptDialog.vue'
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
const reason = ref('')
const initialPath = props.directory ? `${props.directory}/` : ''
const newPath = ref(initialPath)
watch(original, (value) => (content.value = value), { immediate: true })
const dirty = computed(
  () =>
    editing.value &&
    (content.value !== original.value || reason.value !== '' || (props.path === null && newPath.value !== initialPath)),
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
    reason.value = ''
    editing.value = false
    toast.success(t('common.saved'))
    emit('changed', path)
  },
})
async function cancel() {
  if (dirty.value && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') }))) return
  if (props.path === null) return emit('close')
  content.value = original.value
  reason.value = ''
  editing.value = false
}
const canSave = computed(
  () => reason.value.trim() !== '' && (props.path !== null || newPath.value.trim().endsWith('.md')),
)

const removing = ref(false)
const historyOpen = ref(false)
const adopting = ref(false)
const pending = computed(() => inScene.value && Boolean(props.path?.startsWith('legacy-import/')))
function removed() {
  removing.value = false
  void client.invalidateQueries({ queryKey: keys.memory.all() })
  emit('changed', null)
}
function adopted(result: { target: string; source_removed: boolean }) {
  adopting.value = false
  toast.success(t('groups.memory.adopt.done', { path: result.target }))
  emit('changed', result.source_removed ? null : props.path)
}
</script>

<template>
  <form v-if="editing" class="flex flex-col gap-4" @submit.prevent="canSave && save.mutate()">
    <h3 class="truncate font-mono text-sm font-medium text-ink">{{ path ?? t('groups.memory.create') }}</h3>
    <Field v-if="path === null" :label="t('groups.memory.file.path')">
      <Input v-model="newPath" placeholder="people/name.md" mono />
    </Field>
    <Field :label="t('groups.memory.file.content')">
      <Textarea v-model="content" :rows="12" :max-rows="30" mono />
    </Field>
    <Field :label="t('groups.memory.file.reason')">
      <Input v-model="reason" />
    </Field>
    <ErrorNote v-if="save.isError.value" :title="t('groups.memory.file.saveFailed')" :error="save.error.value" />
    <div class="flex justify-end gap-2">
      <Button variant="ghost" :disabled="save.isPending.value" @click="cancel">{{ t('common.cancel') }}</Button>
      <Button type="submit" variant="primary" :loading="save.isPending.value" :disabled="!canSave">
        {{ t('common.save') }}
      </Button>
    </div>
  </form>
  <article v-else class="flex min-w-0 flex-col gap-4">
    <header class="flex flex-wrap items-center gap-2">
      <h3 class="min-w-0 flex-1 truncate font-mono text-sm font-medium text-ink" :title="path ?? ''">{{ path }}</h3>
      <Button v-if="writable && doc.data.value" size="sm" :icon="Pencil" @click="editing = true">
        {{ t('common.edit') }}
      </Button>
      <Button v-if="inScene && can('history')" size="sm" variant="ghost" :icon="History" @click="historyOpen = true">
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
    </header>
    <Skeleton v-if="doc.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="doc.isError.value"
      :title="t('groups.memory.readFailed')"
      :error="doc.error.value"
      :retry="doc.refetch"
    />
    <template v-else>
      <div
        v-if="pending"
        class="flex flex-wrap items-center gap-3 rounded-lg bg-info-bg px-4 py-3 text-sm text-info"
      >
        <span class="min-w-0 flex-1">{{ t('groups.memory.adopt.notice') }}</span>
        <Button size="sm" @click="adopting = true">{{ t('groups.memory.adopt.action') }}</Button>
      </div>
      <p class="text-base leading-7 break-words whitespace-pre-wrap text-ink">{{ original }}</p>
    </template>

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
    <AdoptDialog
      v-if="path && pending"
      v-model:open="adopting"
      :scene="scene"
      :source="path"
      :original="original"
      @adopted="adopted"
    />
  </article>
</template>
