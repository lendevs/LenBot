<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowLeft, BookOpen, FileText, Plus, Trash2 } from '@lucide/vue'
import { keys } from '../../../api/query'
import { personasApi, type KnowledgeListing } from '../../../api/personas'
import { groupLabel } from '../../../layouts/shell/scenes'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Spinner from '../../../ui/Spinner.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useRoleWrites } from './writes'

const props = defineProps<{ persona: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const writes = useRoleWrites(computed(() => props.persona))
const listingKey = computed(() => keys.personas.part(props.persona, 'knowledge'))
const listing = useQuery({
  queryKey: listingKey,
  queryFn: ({ signal }) => personasApi.knowledge(props.persona, signal),
})
const files = computed(() => listing.data.value?.files ?? [])
const directory = computed(() => listing.data.value?.saved_path ?? '')
const title = (filename: string) => filename.replace(/\.md$/, '')

/** The document in the editor: a saved one with its saved text, or a new one (`filename` null). */
const open = ref<{ filename: string | null; content: string } | null>(null)
const name = ref('')
const text = ref('')
const dirty = computed(() =>
  open.value === null ? false : open.value.filename === null ? Boolean(name.value || text.value) : text.value !== open.value.content,
)
watch(dirty, (value) => emit('dirty', value), { immediate: true })
const target = computed(() => {
  if (open.value?.filename) return open.value.filename
  const value = name.value.trim()
  return value.endsWith('.md') ? value : `${value}.md`
})
const problem = computed(() => {
  if (open.value?.filename !== null) return null
  if (!name.value.trim()) return t('personas.detail.knowledge.nameRequired')
  return files.value.some((file) => file.filename === target.value) ? t('personas.detail.knowledge.taken') : null
})

const leave = async () =>
  !dirty.value || confirm({ title: t('personas.detail.knowledge.discard'), confirmLabel: t('common.discard'), tone: 'danger' })

const reading = useMutation({
  mutationFn: (filename: string) => personasApi.document(props.persona, directory.value, filename),
  onSuccess: ({ content }, filename) => {
    open.value = { filename, content }
    text.value = content
  },
})
async function pick(filename: string) {
  if (open.value?.filename === filename || !(await leave())) return
  reading.mutate(filename)
}
async function create() {
  if (!(await leave())) return
  open.value = { filename: null, content: '' }
  name.value = ''
  text.value = ''
}
async function close() {
  if (!(await leave())) return
  open.value = null
  text.value = ''
}

function adopt(result: KnowledgeListing) {
  client.setQueryData(listingKey.value, result)
  writes.done(result)
}
const save = useMutation({
  mutationFn: () =>
    personasApi.writeDocument(props.persona, open.value!.filename === null, directory.value, target.value, text.value),
  onSuccess: (result) => {
    adopt(result)
    const saved = result.document
    if (saved) {
      open.value = { filename: saved.filename, content: saved.content }
      text.value = saved.content
    }
  },
})
const removal = useMutation({
  mutationFn: (filename: string) => personasApi.removeDocument(props.persona, directory.value, filename),
  onSuccess: (result) => {
    client.setQueryData(listingKey.value, result)
    writes.done(result, [], t('personas.detail.knowledge.removed'))
    open.value = null
    text.value = ''
  },
  onError: (error) =>
    toast.error(t('personas.detail.knowledge.removeFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
async function remove() {
  const filename = open.value?.filename
  if (!filename) return
  const shared = listing.data.value?.affected_scenes ?? []
  const sure = await confirm({
    title: t('personas.detail.knowledge.removeTitle', { name: title(filename) }),
    message: shared.length
      ? t('personas.detail.knowledge.removeShared', { names: shared.map(groupLabel).join(t('personas.separator')) })
      : undefined,
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) removal.mutate(filename)
}
function discard() {
  if (!open.value) return
  if (open.value.filename === null) {
    open.value = null
    name.value = ''
  }
  text.value = open.value?.content ?? ''
}
</script>

<template>
  <Skeleton v-if="listing.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="listing.isError.value"
    :title="t('personas.detail.knowledge.readFailed')"
    :error="listing.error.value"
    :retry="listing.refetch"
  />
  <div v-else class="grid min-w-0 items-start gap-5 lg:grid-cols-[16rem_minmax(0,1fr)]">
    <aside class="flex min-w-0 flex-col gap-2" :class="open && 'max-lg:hidden'">
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-base font-semibold">{{ t('personas.detail.knowledge.title') }}</h3>
        <Button size="sm" :icon="Plus" @click="create">{{ t('personas.detail.knowledge.create') }}</Button>
      </div>
      <EmptyState v-if="!files.length" :icon="BookOpen" :title="t('personas.detail.knowledge.empty')" compact />
      <ul v-else class="flex list-none flex-col gap-0.5">
        <li v-for="file in files" :key="file.filename">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-fill focus-visible:focus-ring"
            :class="open?.filename === file.filename && 'bg-fill'"
            :aria-current="open?.filename === file.filename || undefined"
            @click="pick(file.filename)"
          >
            <FileText :size="16" class="shrink-0 text-muted" aria-hidden="true" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-ink">{{ title(file.filename) }}</span>
              <span class="block truncate text-xs text-muted">
                {{ t('personas.detail.knowledge.chars', { n: file.chars }) }}<template v-if="file.tags.length">
                  · {{ file.tags.join(t('personas.separator')) }}</template
                >
              </span>
            </span>
            <Spinner v-if="reading.isPending.value && reading.variables.value === file.filename" :size="14" />
          </button>
        </li>
      </ul>
      <ErrorNote v-if="reading.isError.value" :title="t('personas.detail.knowledge.openFailed')" :error="reading.error.value" />
    </aside>

    <section v-if="open" class="flex min-w-0 flex-col gap-4">
      <div class="flex min-h-8 items-center gap-2">
        <Button variant="ghost" size="sm" :icon="ArrowLeft" class="lg:hidden" @click="close">
          {{ t('personas.detail.knowledge.title') }}
        </Button>
        <h3 class="min-w-0 flex-1 truncate text-base font-semibold max-lg:hidden">
          {{ open.filename ? title(open.filename) : t('personas.detail.knowledge.new') }}
        </h3>
        <Button
          v-if="open.filename"
          size="sm"
          variant="danger-ghost"
          :icon="Trash2"
          :loading="removal.isPending.value"
          class="ml-auto"
          @click="remove"
        >
          {{ t('common.delete') }}
        </Button>
      </div>
      <Field v-if="open.filename === null" :label="t('personas.detail.knowledge.filename')" :error="name ? problem : null">
        <Input v-model="name" mono placeholder="people/xiaoming.md" />
      </Field>
      <Field :label="open.filename === null ? t('personas.detail.knowledge.content') : undefined">
        <Textarea v-model="text" :rows="16" :max-rows="40" :aria-label="t('personas.detail.knowledge.content')" />
      </Field>
      <SaveBar
        :dirty="dirty"
        :saving="save.isPending.value"
        :error="save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : problem"
        :invalid="Boolean(problem)"
        @save="save.mutate()"
        @discard="discard"
      />
    </section>
    <EmptyState v-else :icon="FileText" :title="t('personas.detail.knowledge.pick')" class="max-lg:hidden" />
  </div>
</template>
