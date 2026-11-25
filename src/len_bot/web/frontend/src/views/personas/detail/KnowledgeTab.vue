<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowLeft, BookOpen, FileText, Plus, Search, Trash2, Upload } from '@lucide/vue'
import { keys } from '../../../api/query'
import { personasApi, type KnowledgeListing } from '../../../api/personas'
import { formatNumber } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Spinner from '../../../ui/Spinner.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { hasUnclosedFrontmatter, parseFrontmatterTags, syncFrontmatterTags } from './frontmatter'
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
  refetchInterval: (query) =>
    query.state.data?.files.some((file) => file.index === 'processing') ? 3000 : false,
})
const files = computed(() => listing.data.value?.files ?? [])
const directory = computed(() => listing.data.value?.saved_path ?? '')
const title = (filename: string) => filename.replace(/\.md$/, '')
const search = ref('')
const filteredFiles = computed(() => {
  const words = search.value.trim().toLowerCase()
  if (!words) return files.value
  return files.value.filter((file) =>
    [file.filename, title(file.filename), ...file.tags].some((part) => part.toLowerCase().includes(words)),
  )
})

/** The document in the editor: a saved one with its saved text, or a new one (`filename` null). */
const open = ref<{ filename: string | null; content: string } | null>(null)
const name = ref('')
const text = ref('')
const unclosedFrontmatter = computed(() => hasUnclosedFrontmatter(text.value))
const docTags = computed<string[]>({
  get: () => parseFrontmatterTags(text.value),
  set: (value) => {
    text.value = syncFrontmatterTags(text.value, value)
  },
})
const dirty = computed(() =>
  open.value === null
    ? false
    : open.value.filename === null
      ? Boolean(name.value || text.value)
      : text.value !== open.value.content,
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
  return files.value.some((file) => file.filename === target.value)
    ? t('personas.detail.knowledge.taken')
    : null
})

const leave = async () =>
  !dirty.value ||
  confirm({
    title: t('personas.detail.knowledge.discard'),
    confirmLabel: t('common.discard'),
    tone: 'danger',
  })

let readSeq = 0
let readController: AbortController | null = null
const loadingFile = ref<string | null>(null)
const readError = ref<unknown>(null)

function cancelRead() {
  readSeq += 1
  readController?.abort()
  readController = null
  loadingFile.value = null
}
onBeforeUnmount(cancelRead)
watch(
  () => props.persona,
  () => {
    cancelRead()
    readError.value = null
  },
)

/** Write endpoints omit reference index fields; keep untouched files' status until background refetch returns. */
function mergeListing(
  result: KnowledgeListing,
  changedFilenames: ReadonlySet<string> = new Set(),
): KnowledgeListing {
  const previous = listing.data.value?.files ?? []
  const byName = new Map(previous.map((item) => [item.filename, item]))
  return {
    ...result,
    files: result.files.map((item) => {
      if (changedFilenames.has(item.filename)) return item
      const prev = byName.get(item.filename)
      if (!prev) return item
      return {
        ...item,
        ...(prev.index !== undefined ? { index: prev.index } : {}),
        ...(prev.chunks !== undefined ? { chunks: prev.chunks } : {}),
        ...(prev.vectors !== undefined ? { vectors: prev.vectors } : {}),
      }
    }),
  }
}

async function pick(filename: string) {
  if (open.value?.filename === filename || loadingFile.value === filename) return
  if (!(await leave())) return
  cancelRead()
  const seq = readSeq
  const controller = new AbortController()
  readController = controller
  loadingFile.value = filename
  readError.value = null
  try {
    const { content } = await personasApi.document(
      props.persona,
      directory.value,
      filename,
      controller.signal,
    )
    if (seq !== readSeq) return
    open.value = { filename, content }
    text.value = content
    save.reset()
  } catch (error) {
    if (seq !== readSeq || controller.signal.aborted) return
    readError.value = error
  } finally {
    if (seq === readSeq) {
      loadingFile.value = null
      readController = null
    }
  }
}
async function create() {
  if (!(await leave())) return
  cancelRead()
  readError.value = null
  open.value = { filename: null, content: '' }
  name.value = ''
  text.value = ''
  save.reset()
}
async function close() {
  if (!(await leave())) return
  cancelRead()
  readError.value = null
  open.value = null
  text.value = ''
  save.reset()
}

function adopt(result: KnowledgeListing, changedFilenames?: ReadonlySet<string>, message?: string) {
  client.setQueryData(listingKey.value, mergeListing(result, changedFilenames))
  writes.done(result, ['knowledge'], message)
}
let saveSnapshot: { targetPersona: string; submittedText: string } | null = null
const save = useMutation({
  mutationFn: () => {
    const targetPersona = props.persona
    const submittedText = text.value
    saveSnapshot = { targetPersona, submittedText }
    return personasApi.writeDocument(
      targetPersona,
      open.value!.filename === null,
      directory.value,
      target.value,
      submittedText,
    )
  },
  onSuccess: (result) => {
    const snapshot = saveSnapshot
    saveSnapshot = null
    if (snapshot && props.persona !== snapshot.targetPersona) {
      void client.invalidateQueries({ queryKey: keys.personas.part(snapshot.targetPersona, 'knowledge') })
      return
    }
    const saved = result.document
    const changedName = saved?.filename ?? target.value
    adopt(result, new Set([changedName]))
    if (saved) {
      open.value = { filename: saved.filename, content: saved.content }
      if (!snapshot || text.value === snapshot.submittedText) {
        text.value = saved.content
      }
    }
  },
})
const removal = useMutation({
  mutationFn: (filename: string) => personasApi.removeDocument(props.persona, directory.value, filename),
  onSuccess: (result) => {
    adopt(result, undefined, t('personas.detail.knowledge.removed'))
    open.value = null
    text.value = ''
    save.reset()
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
      ? t('personas.detail.knowledge.removeShared', {
          names: shared.map(groupLabel).join(t('personas.separator')),
        })
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
  save.reset()
}

const mdPicker = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
let dragDepth = 0

const importing = useMutation({
  mutationFn: async (payload: {
    entries: { filename: string; content: string; exists: boolean }[]
    openFilename: string | null
    openText: string
  }) => {
    const targetPersona = props.persona
    const targetDirectory = directory.value
    let latest: KnowledgeListing | null = null
    const changed = new Set<string>()
    const written = new Map<string, { filename: string; content: string }>()
    for (const item of payload.entries) {
      latest = await personasApi.writeDocument(
        targetPersona,
        !item.exists,
        targetDirectory,
        item.filename,
        item.content,
      )
      changed.add(item.filename)
      const doc = latest.document ?? { filename: item.filename, content: item.content }
      written.set(doc.filename, { filename: doc.filename, content: doc.content })
    }
    return {
      targetPersona,
      latest,
      changed,
      written,
      count: payload.entries.length,
      openFilename: payload.openFilename,
      openText: payload.openText,
    }
  },
  onSuccess: ({ targetPersona, latest, changed, written, count, openFilename, openText }) => {
    if (!latest) return
    if (props.persona !== targetPersona) {
      void client.invalidateQueries({ queryKey: keys.personas.part(targetPersona, 'knowledge') })
      return
    }
    if (loadingFile.value && written.has(loadingFile.value)) {
      cancelRead()
    }
    adopt(latest, changed, t('personas.detail.knowledge.imported', { n: count }, count))
    const currentFilename = open.value?.filename ?? null
    if (currentFilename && written.has(currentFilename)) {
      const updated = written.get(currentFilename)!
      const untouchedDuringImport = currentFilename === openFilename && text.value === openText
      open.value = { filename: updated.filename, content: updated.content }
      if (untouchedDuringImport || !dirty.value) {
        text.value = updated.content
        save.reset()
      }
      return
    }
    if (count === 1 && !dirty.value && latest.document) {
      open.value = { filename: latest.document.filename, content: latest.document.content }
      text.value = latest.document.content
      save.reset()
    }
  },
  onError: (error) => {
    toast.error(t('personas.detail.knowledge.importFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
    void listing.refetch()
  },
})

async function handleImportFiles(picked: File[]) {
  if (!picked.length || importing.isPending.value) return
  const mdFiles = picked.filter((item) => item.name.toLowerCase().endsWith('.md'))
  if (!mdFiles.length) {
    toast.error(t('personas.detail.knowledge.mdOnly'))
    return
  }
  const existingNames = new Set(files.value.map((item) => item.filename))
  const seen = new Set<string>()
  const entries: { filename: string; content: string; exists: boolean }[] = []
  for (const item of mdFiles) {
    const cleanName = item.name.replace(/[\\/]/g, '_')
    if (seen.has(cleanName)) continue
    seen.add(cleanName)
    entries.push({
      filename: cleanName,
      content: await item.text(),
      exists: existingNames.has(cleanName),
    })
  }
  const overwritesOpenDirty =
    dirty.value &&
    Boolean(open.value?.filename && entries.some((item) => item.filename === open.value?.filename))
  if (overwritesOpenDirty && !(await leave())) return
  const collisions = entries.filter((item) => item.exists)
  if (collisions.length) {
    const sure = await confirm({
      title: t('personas.detail.knowledge.overwriteTitle'),
      message: collisions.map((item) => item.filename).join(t('personas.separator')),
      confirmLabel: t('personas.detail.knowledge.overwriteConfirm'),
      tone: 'danger',
    })
    if (!sure) return
  }
  importing.mutate({
    entries,
    openFilename: open.value?.filename ?? null,
    openText: text.value,
  })
}

function mdChosen(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = Array.from(input.files ?? [])
  input.value = ''
  if (picked.length) void handleImportFiles(picked)
}

function onDragEnter(event: DragEvent) {
  if (importing.isPending.value) return
  event.preventDefault()
  dragDepth += 1
  dragging.value = true
}
function onDragOver(event: DragEvent) {
  if (importing.isPending.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  dragging.value = true
}
function onDragLeave(event: DragEvent) {
  if (importing.isPending.value) return
  event.preventDefault()
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragging.value = false
  }
}
function onDrop(event: DragEvent) {
  if (importing.isPending.value) return
  event.preventDefault()
  dragDepth = 0
  dragging.value = false
  const dropped = Array.from(event.dataTransfer?.files ?? [])
  if (dropped.length) void handleImportFiles(dropped)
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
  <div
    v-else
    class="grid min-w-0 items-start gap-5 lg:grid-cols-[16.5rem_minmax(0,1fr)] lg:gap-0"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="mdPicker"
      type="file"
      accept=".md,text/markdown"
      multiple
      class="sr-only"
      tabindex="-1"
      aria-hidden="true"
      @change="mdChosen"
    />
    <aside
      class="flex min-w-0 flex-col gap-2.5 lg:border-r lg:border-line lg:pr-5"
      :class="[open && 'max-lg:hidden', dragging && 'rounded-lg ring-2 ring-primary/60']"
    >
      <div class="flex items-center justify-between gap-1.5">
        <h3 class="text-base font-semibold text-ink">{{ t('personas.detail.knowledge.title') }}</h3>
        <div class="flex items-center gap-1">
          <IconButton
            :icon="Upload"
            :label="t('personas.detail.knowledge.importMd')"
            size="sm"
            variant="ghost"
            :loading="importing.isPending.value"
            @click="mdPicker?.click()"
          />
          <Button size="sm" :icon="Plus" @click="create">{{ t('personas.detail.knowledge.create') }}</Button>
        </div>
      </div>
      <div
        v-if="dragging"
        class="rounded-md border border-dashed border-primary bg-selected/40 px-3 py-2.5 text-center text-xs font-medium text-ink"
      >
        {{ t('personas.detail.knowledge.dropMd') }}
      </div>
      <EmptyState v-if="!files.length" :icon="BookOpen" :title="t('personas.detail.knowledge.empty')" compact>
        <Button
          size="sm"
          variant="secondary"
          :icon="Upload"
          :loading="importing.isPending.value"
          @click="mdPicker?.click()"
        >
          {{ t('personas.detail.knowledge.importMd') }}
        </Button>
      </EmptyState>
      <template v-else>
        <Input
          v-model="search"
          type="search"
          size="sm"
          :icon="Search"
          clearable
          :placeholder="t('common.search')"
          :aria-label="t('common.search')"
        />
        <p v-if="!filteredFiles.length" class="px-2 py-4 text-center text-sm text-muted">
          {{ t('common.noResults') }}
        </p>
        <ul v-else class="flex list-none flex-col gap-0.5">
          <li v-for="file in filteredFiles" :key="file.filename">
            <button
              type="button"
              class="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors focus-visible:focus-ring"
              :class="open?.filename === file.filename ? 'bg-selected text-ink' : 'hover:bg-hover'"
              :aria-current="open?.filename === file.filename || undefined"
              @click="pick(file.filename)"
            >
              <FileText
                :size="16"
                class="shrink-0"
                :class="open?.filename === file.filename ? 'text-ink' : 'text-muted'"
                aria-hidden="true"
              />
              <span class="min-w-0 flex-1">
                <span
                  class="block truncate text-sm text-ink"
                  :class="open?.filename === file.filename ? 'font-semibold' : 'font-medium'"
                >
                  {{ title(file.filename) }}
                </span>
                <span class="block truncate text-xs text-muted tabular">
                  {{ t('personas.detail.knowledge.chars', { n: formatNumber(file.chars) }, file.chars) }}
                  <template v-if="file.index">
                    ·
                    {{
                      file.index === 'indexed'
                        ? t(
                            'personas.detail.knowledge.indexed',
                            { n: formatNumber(file.chunks ?? 0) },
                            file.chunks ?? 0,
                          )
                        : t(`personas.detail.knowledge.${file.index}`)
                    }}
                  </template>
                  <template v-if="file.tags.length">· {{ file.tags.join(t('personas.separator')) }}</template>
                </span>
              </span>
              <Spinner v-if="loadingFile === file.filename" :size="14" />
            </button>
          </li>
        </ul>
      </template>
      <ErrorNote v-if="readError" :title="t('personas.detail.knowledge.openFailed')" :error="readError" />
    </aside>

    <div class="min-w-0 lg:pl-6" :class="!open && 'max-lg:hidden'">
      <section v-if="open" class="flex min-w-0 flex-col gap-4 pb-6">
        <div class="flex min-h-8 items-center gap-2">
          <div class="-ml-2 shrink-0 lg:hidden">
            <Button variant="ghost" size="sm" :icon="ArrowLeft" @click="close">
              {{ t('personas.detail.knowledge.title') }}
            </Button>
          </div>
          <h3 class="min-w-0 flex-1 truncate text-base font-semibold text-ink">
            {{ open.filename ? title(open.filename) : t('personas.detail.knowledge.new') }}
          </h3>
          <div v-if="open.filename" class="ml-auto shrink-0">
            <Button
              size="sm"
              variant="danger-ghost"
              :icon="Trash2"
              :loading="removal.isPending.value"
              @click="remove"
            >
              {{ t('common.delete') }}
            </Button>
          </div>
        </div>
        <Field
          v-if="open.filename === null"
          :label="t('personas.detail.knowledge.filename')"
          :error="name ? problem : null"
        >
          <Input v-model="name" mono placeholder="people/xiaoming.md" />
        </Field>
        <Field :label="t('personas.detail.knowledge.tags')">
          <TagInput v-model="docTags" size="sm" :disabled="unclosedFrontmatter" />
        </Field>
        <Field :label="open.filename === null ? t('personas.detail.knowledge.content') : undefined">
          <Textarea
            v-model="text"
            :rows="16"
            :max-rows="40"
            :aria-label="t('personas.detail.knowledge.content')"
          />
        </Field>
        <SaveBar
          :dirty="dirty"
          :saving="save.isPending.value"
          :error="
            save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : problem
          "
          :raw-error="save.isError.value ? describeError(save.error.value, t('ui.error.network')).raw : null"
          :invalid="Boolean(problem)"
          @save="save.mutate()"
          @discard="discard"
        />
      </section>
      <EmptyState v-else :icon="FileText" :title="t('personas.detail.knowledge.pick')" />
    </div>
  </div>
</template>
