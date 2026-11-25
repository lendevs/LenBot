<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { BookmarkPlus, ChevronRight, Pencil, Search } from '@lucide/vue'
import { learningApi, type Expression, type ExpressionDetail, type Review } from '../../../api/learning'
import { keys } from '../../../api/query'
import { formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import Dialog from '../../../ui/Dialog.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import Pager from './Pager.vue'
import { useEdits } from './useEdits'
import { usePagedList } from './usePagedList'

const props = defineProps<{ scene: string }>()
const filter = defineModel<Review>('filter', { default: 'pending' })
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const list = usePagedList<Expression, Review>(
  (status, offset) => keys.scene.learning(props.scene, 'expressions', status, offset),
  (status, offset, signal) => learningApi.expressions(props.scene, status, offset, signal),
  filter,
)
const edits = useEdits((item: Expression) => ({ situation: item.situation, style: item.style }))
watch(edits.dirty, (value) => emit('dirty', value), { immediate: true })

const search = ref('')
const keyword = computed(() => search.value.trim().toLowerCase())
const items = computed(() => list.page.value?.items ?? [])
const filteredItems = computed(() => {
  const q = keyword.value
  if (!q) return items.value
  return items.value.filter(
    (item) => item.situation.toLowerCase().includes(q) || item.style.toLowerCase().includes(q),
  )
})

const selectedIds = ref<number[]>([])
const rowErrors = reactive<Record<number, unknown>>({})
const batchError = ref<unknown>(null)

// Drop invisible drafts and selections when switching filter, page, or group.
watch([() => props.scene, list.filter, list.offset], () => {
  edits.clear()
  selectedIds.value = []
  batchError.value = null
  for (const key of Object.keys(rowErrors)) delete rowErrors[Number(key)]
})
watch(
  () => [list.page.value, list.query.isPlaceholderData.value] as const,
  ([page, placeholder]) => {
    if (!page || placeholder) return
    const visible = new Set(page.items.map((item) => item.id))
    edits.prune(visible)
    selectedIds.value = selectedIds.value.filter((id) => visible.has(id))
  },
)

const isPendingView = computed(() => list.filter.value === 'pending')
const allSelected = computed(() => {
  const ids = filteredItems.value.map((item) => item.id)
  if (!ids.length) return false
  if (ids.every((id) => selectedIds.value.includes(id))) return true
  return ids.some((id) => selectedIds.value.includes(id)) ? 'indeterminate' : false
})
function toggleAll(on: boolean) {
  const ids = filteredItems.value.map((item) => item.id)
  selectedIds.value = on
    ? [...new Set([...selectedIds.value, ...ids])]
    : selectedIds.value.filter((id) => !ids.includes(id))
}
function toggleOne(id: number, on: boolean) {
  selectedIds.value = on
    ? selectedIds.value.includes(id)
      ? selectedIds.value
      : [...selectedIds.value, id]
    : selectedIds.value.filter((value) => value !== id)
}

const expandedSources = ref(new Set<number>())
const sourceCache = reactive<Record<number, { loading: boolean; data?: ExpressionDetail; error?: unknown }>>(
  {},
)
async function loadSources(id: number) {
  sourceCache[id] = { loading: true, data: sourceCache[id]?.data }
  try {
    const data = await client.fetchQuery({
      queryKey: keys.scene.learning(props.scene, 'expression', id),
      queryFn: ({ signal }) => learningApi.expression(props.scene, id, signal),
      staleTime: 5 * 60_000,
    })
    sourceCache[id] = { loading: false, data }
  } catch (error) {
    sourceCache[id] = { loading: false, error }
  }
}
function toggleSources(id: number) {
  const next = new Set(expandedSources.value)
  if (next.has(id)) {
    next.delete(id)
    expandedSources.value = next
    return
  }
  next.add(id)
  expandedSources.value = next
  if (!sourceCache[id]?.data && !sourceCache[id]?.loading) void loadSources(id)
}

function statusToast(status: Review, edited: boolean): string {
  if (edited) return t('common.saved')
  if (status === 'adopted') return t('groups.learning.adopted')
  if (status === 'rejected') return t('groups.learning.rejected')
  return t('groups.learning.restored')
}

const save = useMutation({
  mutationFn: ({ item, status }: { item: Expression; status: Review; edited?: boolean }) => {
    delete rowErrors[item.id]
    const text = edits.editing(item.id)
      ? edits.draft(item.id)
      : { situation: item.situation, style: item.style }
    return learningApi.putExpression(props.scene, item.id, {
      situation: text.situation.trim(),
      style: text.style.trim(),
      status,
    })
  },
  onSuccess: (_, { item, status, edited }) => {
    edits.stop(item.id)
    delete rowErrors[item.id]
    selectedIds.value = selectedIds.value.filter((id) => id !== item.id)
    toast.success(statusToast(status, Boolean(edited)))
  },
  onError: (error, { item }) => {
    rowErrors[item.id] = error
    toast.error(t('groups.learning.saveFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
  },
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})
const busy = (item: Expression) => save.isPending.value && save.variables.value?.item.id === item.id
const invalid = (item: Expression) => {
  const draft = edits.draft(item.id)
  return Boolean(draft) && (!draft.situation.trim() || !draft.style.trim())
}
function startEdit(item: Expression) {
  delete rowErrors[item.id]
  edits.start(item)
}
function stopEdit(id: number) {
  delete rowErrors[id]
  edits.stop(id)
}

const batch = useMutation({
  mutationFn: async (status: 'adopted' | 'rejected') => {
    batchError.value = null
    const chosen = items.value.filter((item) => selectedIds.value.includes(item.id))
    let ok = 0
    const failedIds: number[] = []
    let firstError: unknown = null
    for (const item of chosen) {
      const text = edits.editing(item.id)
        ? edits.draft(item.id)
        : { situation: item.situation, style: item.style }
      try {
        await learningApi.putExpression(props.scene, item.id, {
          situation: text.situation.trim() || item.situation,
          style: text.style.trim() || item.style,
          status,
        })
        edits.stop(item.id)
        delete rowErrors[item.id]
        ok += 1
      } catch (error) {
        failedIds.push(item.id)
        rowErrors[item.id] = error
        if (!firstError) firstError = error
      }
    }
    return { status, ok, failedIds, firstError }
  },
  onSuccess: ({ status, ok, failedIds, firstError }) => {
    selectedIds.value = failedIds
    if (failedIds.length) {
      batchError.value = firstError
      toast.error(t('groups.learning.batchFailed', { ok, fail: failedIds.length }))
    } else if (ok > 0) {
      toast.success(
        t(status === 'adopted' ? 'groups.learning.batchAdopted' : 'groups.learning.batchRejected', { n: ok }),
      )
    }
  },
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})

/** Adding an adopted expression to the persona's examples; the text can be adjusted first. */
const example = ref<{ expression_id: number; context: string; line: string; tags: string[] } | null>(null)
const exampleOpen = computed({
  get: () => example.value !== null,
  set: (value: boolean) => {
    if (!value) example.value = null
  },
})
const addExample = useMutation({
  mutationFn: async () => {
    const value = example.value!
    const target = await learningApi.personaLocation(props.scene)
    return learningApi.addExample(props.scene, { ...value, directory: target.saved_path })
  },
  onSuccess: () => {
    example.value = null
    toast.success(t('groups.learning.example.done'))
  },
  onError: (error) =>
    toast.error(t('groups.learning.example.failed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <Skeleton v-if="list.query.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="list.query.isError.value"
      :title="t('groups.learning.readFailed')"
      :error="list.query.error.value"
      :retry="list.query.refetch"
    />
    <EmptyState v-else-if="!list.page.value?.items.length" :title="t('groups.learning.empty')" compact />
    <template v-else-if="list.page.value">
      <div class="flex flex-wrap items-center gap-3">
        <div class="w-full max-w-xs">
          <Input
            v-model="search"
            type="search"
            size="sm"
            :icon="Search"
            clearable
            :placeholder="t('common.search')"
            :aria-label="t('common.search')"
          />
        </div>
        <Checkbox
          v-if="isPendingView && filteredItems.length"
          :model-value="allSelected"
          @update:model-value="(on) => toggleAll(on === true)"
        >
          <span class="text-xs text-muted">{{ t('groups.learning.selectAll') }}</span>
        </Checkbox>
      </div>
      <ErrorNote v-if="batchError" :title="t('groups.learning.saveFailed')" :error="batchError" />
      <p v-if="!filteredItems.length" class="py-6 text-center text-sm text-muted">
        {{ t('common.noResults') }}
      </p>
      <TransitionGroup
        v-else
        tag="ul"
        name="ui-list"
        class="flex list-none flex-col divide-y divide-line border-y border-line"
      >
        <li v-for="item in filteredItems" :key="item.id" class="flex flex-col gap-3 py-4">
          <div class="flex min-w-0 items-start gap-3">
            <span v-if="isPendingView" class="pt-0.5">
              <Checkbox
                :model-value="selectedIds.includes(item.id)"
                :disabled="batch.isPending.value"
                :aria-label="t('groups.learning.selectItem')"
                @update:model-value="(on) => toggleOne(item.id, on === true)"
              />
            </span>
            <div class="flex min-w-0 flex-1 flex-col gap-3">
              <div v-if="edits.editing(item.id)" class="grid gap-3 sm:grid-cols-2">
                <Field :label="t('groups.learning.expression.situation')">
                  <Textarea v-model="edits.draft(item.id).situation" :rows="1" />
                </Field>
                <Field :label="t('groups.learning.expression.style')">
                  <Textarea v-model="edits.draft(item.id).style" :rows="1" />
                </Field>
              </div>
              <div v-else class="flex min-w-0 flex-col gap-1">
                <p class="text-xs font-medium text-muted">{{ item.situation }}</p>
                <p class="text-base leading-6 break-words text-ink">{{ item.style }}</p>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <button
                  v-if="item.count > 0"
                  type="button"
                  class="inline-flex cursor-pointer items-center gap-0.5 rounded-sm text-xs text-subtle tabular transition-colors hover:text-ink focus-visible:focus-ring"
                  :aria-expanded="expandedSources.has(item.id)"
                  @click="toggleSources(item.id)"
                >
                  <ChevronRight
                    :size="13"
                    class="shrink-0 transition-transform duration-(--dur-1)"
                    :class="expandedSources.has(item.id) && 'rotate-90'"
                    aria-hidden="true"
                  />
                  {{ t('groups.learning.sources', { n: formatNumber(item.count) }) }}
                </button>
                <span v-else class="text-xs text-subtle tabular">
                  {{ t('groups.learning.sources', { n: formatNumber(item.count) }) }}
                </span>
                <Badge v-if="(item.disliked ?? 0) >= 2" tone="warning" class="tabular">
                  {{ t('groups.learning.expression.disliked', { n: formatNumber(item.disliked ?? 0) }) }}
                </Badge>
                <div class="ml-auto flex flex-wrap items-center gap-1.5">
                  <template v-if="edits.editing(item.id)">
                    <Button size="sm" variant="ghost" @click="stopEdit(item.id)">
                      {{ t('common.cancel') }}
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      :loading="busy(item)"
                      :disabled="invalid(item) || !edits.changed(item.id)"
                      @click="save.mutate({ item, status: item.status, edited: true })"
                    >
                      {{ t('common.save') }}
                    </Button>
                  </template>
                  <template v-else>
                    <Button size="sm" variant="ghost" :icon="Pencil" @click="startEdit(item)">
                      {{ t('common.edit') }}
                    </Button>
                    <Button
                      v-if="item.status === 'adopted'"
                      size="sm"
                      variant="ghost"
                      :icon="BookmarkPlus"
                      @click="
                        example = {
                          expression_id: item.id,
                          context: item.situation,
                          line: item.style,
                          tags: [],
                        }
                      "
                    >
                      {{ t('groups.learning.example.action') }}
                    </Button>
                    <Button
                      v-if="item.status !== 'pending'"
                      size="sm"
                      variant="ghost"
                      :disabled="busy(item) || batch.isPending.value"
                      @click="save.mutate({ item, status: 'pending' })"
                    >
                      {{ t('groups.learning.actions.restore') }}
                    </Button>
                    <Button
                      v-if="item.status !== 'rejected'"
                      size="sm"
                      variant="ghost"
                      :disabled="busy(item) || batch.isPending.value"
                      @click="save.mutate({ item, status: 'rejected' })"
                    >
                      {{ t('groups.learning.actions.reject') }}
                    </Button>
                    <Button
                      v-if="item.status !== 'adopted'"
                      size="sm"
                      variant="primary"
                      :loading="busy(item)"
                      :disabled="batch.isPending.value"
                      @click="save.mutate({ item, status: 'adopted' })"
                    >
                      {{ t('groups.learning.actions.adopt') }}
                    </Button>
                  </template>
                </div>
              </div>
              <div
                class="ui-grid-collapse"
                :data-open="expandedSources.has(item.id) ? 'true' : 'false'"
                :inert="!expandedSources.has(item.id)"
              >
                <div>
                  <div
                    v-if="expandedSources.has(item.id) || sourceCache[item.id]"
                    class="flex flex-col gap-1.5 pt-1"
                  >
                    <Skeleton v-if="sourceCache[item.id]?.loading" :lines="2" />
                    <ErrorNote
                      v-else-if="sourceCache[item.id]?.error"
                      :title="t('groups.learning.expression.sourceFailed')"
                      :error="sourceCache[item.id]!.error"
                      :retry="() => loadSources(item.id)"
                    />
                    <template v-else-if="sourceCache[item.id]?.data">
                      <p
                        v-if="!sourceCache[item.id]!.data!.source_messages.length"
                        class="text-xs text-muted"
                      >
                        {{ t('groups.learning.expression.sourceEmpty') }}
                      </p>
                      <pre
                        v-for="msg in sourceCache[item.id]!.data!.source_messages"
                        :key="msg.record"
                        class="rounded-md bg-fill px-3 py-2 font-mono text-xs leading-5 break-words whitespace-pre-wrap text-ink-2"
                        >{{
                          msg.available && msg.rendered !== null
                            ? msg.rendered
                            : t('groups.learning.effects.gone')
                        }}</pre>
                    </template>
                  </div>
                </div>
              </div>
              <ErrorNote
                v-if="rowErrors[item.id]"
                :title="t('groups.learning.saveFailed')"
                :error="rowErrors[item.id]"
              />
            </div>
          </div>
        </li>
      </TransitionGroup>

      <Transition name="ui-rise">
        <div
          v-if="isPendingView && selectedIds.length"
          class="sticky bottom-3 z-(--z-top) flex flex-wrap items-center gap-2 rounded-lg border border-line-strong bg-surface-raised px-3.5 py-2.5 shadow-float"
        >
          <span class="text-sm font-medium text-ink tabular">
            {{ t('groups.learning.selected', { n: formatNumber(selectedIds.length) }) }}
          </span>
          <div class="ml-auto flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant="ghost" :disabled="batch.isPending.value" @click="selectedIds = []">
              {{ t('groups.learning.clearSelection') }}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              :loading="batch.isPending.value && batch.variables.value === 'rejected'"
              :disabled="batch.isPending.value"
              @click="batch.mutate('rejected')"
            >
              {{ t('groups.learning.actions.reject') }}
            </Button>
            <Button
              size="sm"
              variant="primary"
              :loading="batch.isPending.value && batch.variables.value === 'adopted'"
              :disabled="batch.isPending.value"
              @click="batch.mutate('adopted')"
            >
              {{ t('groups.learning.actions.adopt') }}
            </Button>
          </div>
        </div>
      </Transition>

      <Pager
        :offset="list.page.value.offset"
        :limit="list.page.value.limit"
        :total="list.page.value.total"
        :disabled="list.query.isFetching.value"
        @move="list.move"
      />
    </template>

    <Dialog
      v-model:open="exampleOpen"
      :title="t('groups.learning.example.title')"
      :busy="addExample.isPending.value"
    >
      <div v-if="example" class="flex flex-col gap-4">
        <Field :label="t('groups.learning.example.context')">
          <Textarea v-model="example.context" :rows="2" />
        </Field>
        <Field :label="t('groups.learning.example.line')">
          <Textarea v-model="example.line" :rows="2" />
        </Field>
        <Field :label="t('groups.learning.example.tags')">
          <TagInput v-model="example.tags" />
        </Field>
      </div>
      <template #footer>
        <Button variant="ghost" :disabled="addExample.isPending.value" @click="example = null">
          {{ t('common.cancel') }}
        </Button>
        <Button
          variant="primary"
          :loading="addExample.isPending.value"
          :disabled="!example?.context.trim() || !example?.line.trim()"
          @click="addExample.mutate()"
        >
          {{ t('groups.learning.example.add') }}
        </Button>
      </template>
    </Dialog>
  </div>
</template>
