<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch, type ComponentPublicInstance } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { ImageOff, Pencil, RotateCw, Search } from '@lucide/vue'
import { learningApi, type Review, type Sticker, type StickerFilter } from '../../../api/learning'
import { keys } from '../../../api/query'
import { formatBytes, formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import Dialog from '../../../ui/Dialog.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import TagInput from '../../../ui/TagInput.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import Pager from './Pager.vue'
import { useEdits } from './useEdits'
import { usePagedList } from './usePagedList'

const props = defineProps<{ scene: string }>()
const filter = defineModel<StickerFilter>('filter', { default: 'pending' })
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const list = usePagedList<Sticker, StickerFilter>(
  (current, offset) => keys.scene.learning(props.scene, 'stickers', current, offset),
  (current, offset, signal) => learningApi.stickers(props.scene, current, offset, signal),
  filter,
)
const fresh = (item: Sticker) => ({
  description: item.description ?? '',
  text: item.text ?? '',
  emotions: [...item.emotions],
  tags: [...item.tags],
})
const edits = useEdits(fresh)
watch(edits.dirty, (value) => emit('dirty', value), { immediate: true })

const search = ref('')
const keyword = computed(() => search.value.trim().toLowerCase())
const items = computed(() => list.page.value?.items ?? [])
const filteredItems = computed(() => {
  const q = keyword.value
  if (!q) return items.value
  return items.value.filter((item) =>
    [item.description, item.text, item.error, ...item.emotions, ...item.tags].some((part) =>
      part?.toLowerCase().includes(q),
    ),
  )
})

const selectedIds = ref<number[]>([])
const brokenIds = ref(new Set<number>())
const rowErrors = reactive<Record<number, unknown>>({})
const batchError = ref<unknown>(null)
const needsDescriptionId = ref<number | null>(null)
const descInputs = new Map<number, { focus?: () => void }>()
function setDescRef(id: number, el: Element | ComponentPublicInstance | null) {
  if (el) descInputs.set(id, el as unknown as { focus?: () => void })
  else descInputs.delete(id)
}
function markBroken(id: number) {
  const next = new Set(brokenIds.value)
  next.add(id)
  brokenIds.value = next
}

watch(
  () => props.scene,
  () => {
    brokenIds.value = new Set()
  },
)
watch([() => props.scene, list.filter, list.offset], () => {
  edits.clear()
  selectedIds.value = []
  needsDescriptionId.value = null
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
    if (needsDescriptionId.value !== null && !visible.has(needsDescriptionId.value)) {
      needsDescriptionId.value = null
    }
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

function reviewToast(review: Review, edited: boolean): string {
  if (edited && review !== 'adopted') return t('common.saved')
  if (review === 'adopted') return t('groups.learning.adopted')
  if (review === 'rejected') return t('groups.learning.rejected')
  return t('groups.learning.restored')
}

const save = useMutation({
  mutationFn: ({ item, review }: { item: Sticker; review: Review; edited?: boolean }) => {
    delete rowErrors[item.id]
    const value = edits.editing(item.id) ? edits.draft(item.id) : fresh(item)
    return learningApi.putSticker(props.scene, item.id, {
      description: value.description.trim() || null,
      text: value.text.trim() || null,
      emotions: value.emotions,
      tags: value.tags,
      review,
    })
  },
  onSuccess: (_, { item, review, edited }) => {
    edits.stop(item.id)
    if (needsDescriptionId.value === item.id) needsDescriptionId.value = null
    delete rowErrors[item.id]
    selectedIds.value = selectedIds.value.filter((id) => id !== item.id)
    toast.success(reviewToast(review, Boolean(edited)))
  },
  onError: (error, { item }) => {
    rowErrors[item.id] = error
    toast.error(t('groups.learning.saveFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
  },
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})

const retry = useMutation({
  mutationFn: (item: Sticker) => {
    delete rowErrors[item.id]
    return learningApi.retrySticker(props.scene, item.id)
  },
  onSuccess: () => toast.success(t('groups.learning.sticker.retried')),
  onError: (error, item) => {
    rowErrors[item.id] = error
    toast.error(t('groups.learning.sticker.retryFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
  },
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})

const busy = (item: Sticker) =>
  (save.isPending.value && save.variables.value?.item.id === item.id) ||
  (retry.isPending.value && retry.variables.value?.id === item.id)

function startEdit(item: Sticker) {
  delete rowErrors[item.id]
  edits.start(item)
}
function stopEdit(id: number) {
  delete rowErrors[id]
  if (needsDescriptionId.value === id) needsDescriptionId.value = null
  edits.stop(id)
}
async function promptDescription(item: Sticker) {
  delete rowErrors[item.id]
  if (!edits.editing(item.id)) edits.start(item)
  needsDescriptionId.value = item.id
  await nextTick()
  descInputs.get(item.id)?.focus?.()
}
function adoptItem(item: Sticker) {
  const description = (
    edits.editing(item.id) ? edits.draft(item.id).description : (item.description ?? '')
  ).trim()
  if (!description) {
    void promptDescription(item)
    return
  }
  save.mutate({ item, review: 'adopted' })
}
function saveEdit(item: Sticker) {
  const adopting = needsDescriptionId.value === item.id
  const targetReview: Review = adopting ? 'adopted' : item.review
  const description = edits.draft(item.id).description.trim()
  if (targetReview === 'adopted' && !description) {
    needsDescriptionId.value = item.id
    void nextTick(() => descInputs.get(item.id)?.focus?.())
    return
  }
  save.mutate({ item, review: targetReview, edited: true })
}
function editSaveDisabled(item: Sticker): boolean {
  const draft = edits.draft(item.id)
  if (!draft) return true
  if (needsDescriptionId.value === item.id) return !draft.description.trim()
  if (item.review === 'adopted' && !draft.description.trim()) return true
  return !edits.changed(item.id)
}

const currentViewKey = () => `${props.scene}\0${list.filter.value}\0${list.offset.value}`

const batch = useMutation({
  mutationFn: async (review: 'adopted' | 'rejected') => {
    const targetScene = props.scene
    const startedView = currentViewKey()
    batchError.value = null
    const chosen = items.value.filter((item) => selectedIds.value.includes(item.id))
    const skipped: Sticker[] = []
    const requests: {
      id: number
      body: {
        description: string | null
        text: string | null
        emotions: string[]
        tags: string[]
        review: 'adopted' | 'rejected'
      }
    }[] = []
    for (const item of chosen) {
      const value = edits.editing(item.id) ? edits.draft(item.id) : fresh(item)
      if (review === 'adopted' && !value.description.trim()) {
        skipped.push(item)
      } else {
        requests.push({
          id: item.id,
          body: {
            description: value.description.trim() || null,
            text: value.text.trim() || null,
            emotions: [...value.emotions],
            tags: [...value.tags],
            review,
          },
        })
      }
    }
    let ok = 0
    const failedIds: number[] = []
    const failedErrors = new Map<number, unknown>()
    let firstError: unknown = null
    for (const req of requests) {
      try {
        await learningApi.putSticker(targetScene, req.id, req.body)
        if (currentViewKey() === startedView) {
          edits.stop(req.id)
          delete rowErrors[req.id]
        }
        ok += 1
      } catch (error) {
        failedIds.push(req.id)
        failedErrors.set(req.id, error)
        if (currentViewKey() === startedView) {
          rowErrors[req.id] = error
        }
        if (!firstError) firstError = error
      }
    }
    return { targetScene, startedView, review, ok, failedIds, failedErrors, skipped, firstError }
  },
  onSuccess: ({ startedView, review, ok, failedIds, failedErrors, skipped, firstError }) => {
    const sameView = currentViewKey() === startedView
    if (sameView) {
      selectedIds.value = [...failedIds, ...skipped.map((item) => item.id)]
      for (const [id, error] of failedErrors) rowErrors[id] = error
      if (failedIds.length) batchError.value = firstError
    }
    if (failedIds.length) {
      toast.error(t('groups.learning.batchFailed', { ok, fail: failedIds.length }))
    } else if (ok > 0) {
      toast.success(
        t(review === 'adopted' ? 'groups.learning.batchAdopted' : 'groups.learning.batchRejected', { n: ok }),
      )
    }
    if (skipped.length) {
      toast.warning(t('groups.learning.sticker.batchSkippedNoDesc', { n: skipped.length }))
      if (sameView) void promptDescription(skipped[0]!)
    }
  },
  onSettled: (data) =>
    client.invalidateQueries({ queryKey: keys.scene.learningAll(data?.targetScene ?? props.scene) }),
})

const previewing = ref<Sticker | null>(null)
const previewBackdrop = ref<'light' | 'dark'>('light')
const backdropOptions = computed(() => [
  { value: 'light' as const, label: t('groups.learning.sticker.backdropLight') },
  { value: 'dark' as const, label: t('groups.learning.sticker.backdropDark') },
])
const previewOpen = computed({
  get: () => previewing.value !== null,
  set: (value: boolean) => {
    if (!value) previewing.value = null
  },
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
        class="grid list-none gap-3 sm:grid-cols-2 xl:grid-cols-3"
      >
        <li
          v-for="item in filteredItems"
          :key="item.id"
          class="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-surface p-3.5"
        >
          <div class="flex min-w-0 gap-3">
            <div class="relative shrink-0">
              <button
                type="button"
                class="grid size-20 cursor-pointer place-items-center overflow-hidden rounded-md bg-fill p-1.5 transition-colors hover:bg-hover focus-visible:focus-ring sm:size-24"
                :aria-label="`${t('groups.learning.sticker.preview')}: ${item.description || t('groups.learning.sticker.image')}`"
                @click="previewing = item"
              >
                <ImageOff v-if="brokenIds.has(item.id)" :size="20" class="text-subtle" aria-hidden="true" />
                <img
                  v-else
                  :src="learningApi.stickerImage(scene, item.id)"
                  :alt="item.description || t('groups.learning.sticker.image')"
                  loading="lazy"
                  class="max-h-full max-w-full object-contain"
                  @error="markBroken(item.id)"
                />
              </button>
              <span
                v-if="isPendingView"
                class="absolute top-1 left-1 rounded-xs bg-surface/90 p-0.5 shadow-card"
              >
                <Checkbox
                  :model-value="selectedIds.includes(item.id)"
                  :disabled="batch.isPending.value"
                  :aria-label="t('groups.learning.selectItem')"
                  @update:model-value="(on) => toggleOne(item.id, on === true)"
                />
              </span>
            </div>
            <div class="flex min-w-0 flex-1 flex-col gap-1.5">
              <p class="text-sm leading-5 break-words text-ink">
                {{ item.description || t('groups.learning.sticker.noDescription') }}
              </p>
              <p v-if="item.text" class="text-xs break-words text-ink-2">
                <span class="text-muted">{{ t('groups.learning.sticker.text') }}</span>
                · {{ item.text }}
              </p>
              <p v-if="item.posts && item.posts > 1" class="text-xs text-subtle tabular">
                {{
                  t('groups.learning.sticker.posts', {
                    n: formatNumber(item.posts),
                    people: formatNumber(item.posters ?? 0),
                  })
                }}
              </p>
              <div v-if="item.emotions.length || item.tags.length" class="flex flex-wrap gap-1">
                <Badge v-for="emotion in item.emotions" :key="`e${emotion}`" tone="info">
                  {{ emotion }}
                </Badge>
                <Badge v-for="tag in item.tags" :key="`t${tag}`">{{ tag }}</Badge>
              </div>
              <Badge
                v-if="item.status === 'queued' || item.status === 'running'"
                tone="info"
                class="self-start"
              >
                {{ t('groups.learning.sticker.queued') }}
              </Badge>
              <Badge
                v-else-if="item.status === 'failed' || item.status === 'interrupted'"
                tone="error"
                class="self-start"
              >
                {{ t('groups.learning.sticker.failed') }}
              </Badge>
              <p v-if="item.error" class="line-clamp-3 text-xs break-words text-error">
                {{ item.error }}
              </p>
            </div>
          </div>
          <div v-if="edits.editing(item.id)" class="flex flex-col gap-3 border-t border-line pt-3">
            <Field
              :label="t('groups.learning.sticker.description')"
              :required="needsDescriptionId === item.id || item.review === 'adopted'"
              :error="
                needsDescriptionId === item.id && !edits.draft(item.id).description.trim()
                  ? t('groups.learning.sticker.descriptionRequired')
                  : null
              "
            >
              <Input :ref="(el) => setDescRef(item.id, el)" v-model="edits.draft(item.id).description" />
            </Field>
            <Field :label="t('groups.learning.sticker.text')">
              <Input v-model="edits.draft(item.id).text" />
            </Field>
            <Field :label="t('groups.learning.sticker.emotions')">
              <TagInput v-model="edits.draft(item.id).emotions" />
            </Field>
            <Field :label="t('groups.learning.sticker.tags')">
              <TagInput v-model="edits.draft(item.id).tags" />
            </Field>
          </div>
          <ErrorNote
            v-if="rowErrors[item.id]"
            :title="t('groups.learning.saveFailed')"
            :error="rowErrors[item.id]"
          />
          <div class="mt-auto flex flex-wrap items-center justify-end gap-1.5 border-t border-line pt-2.5">
            <template v-if="edits.editing(item.id)">
              <Button size="sm" variant="ghost" @click="stopEdit(item.id)">{{ t('common.cancel') }}</Button>
              <Button
                size="sm"
                variant="primary"
                :loading="busy(item)"
                :disabled="editSaveDisabled(item)"
                @click="saveEdit(item)"
              >
                {{
                  needsDescriptionId === item.id
                    ? t('groups.learning.sticker.saveAndAdopt')
                    : t('common.save')
                }}
              </Button>
            </template>
            <template v-else-if="item.status !== 'complete'">
              <Button
                v-if="item.review !== 'rejected'"
                size="sm"
                variant="ghost"
                :disabled="busy(item)"
                @click="save.mutate({ item, review: 'rejected' })"
              >
                {{ t('groups.learning.actions.reject') }}
              </Button>
              <Button
                v-if="
                  (item.status === 'failed' || item.status === 'interrupted') && item.review !== 'rejected'
                "
                size="sm"
                variant="secondary"
                :icon="RotateCw"
                :loading="busy(item)"
                @click="retry.mutate(item)"
              >
                {{ t('groups.learning.sticker.retry') }}
              </Button>
            </template>
            <template v-else>
              <Button size="sm" variant="ghost" :icon="Pencil" @click="startEdit(item)">
                {{ t('common.edit') }}
              </Button>
              <Button
                v-if="item.review !== 'pending'"
                size="sm"
                variant="ghost"
                :disabled="busy(item) || batch.isPending.value"
                @click="save.mutate({ item, review: 'pending' })"
              >
                {{ t('groups.learning.actions.restore') }}
              </Button>
              <Button
                v-if="item.review !== 'rejected'"
                size="sm"
                variant="ghost"
                :disabled="busy(item) || batch.isPending.value"
                @click="save.mutate({ item, review: 'rejected' })"
              >
                {{ t('groups.learning.actions.reject') }}
              </Button>
              <Button
                v-if="item.review !== 'adopted'"
                size="sm"
                variant="primary"
                :loading="busy(item)"
                :disabled="batch.isPending.value"
                @click="adoptItem(item)"
              >
                {{ t('groups.learning.actions.adopt') }}
              </Button>
            </template>
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
      v-model:open="previewOpen"
      :title="previewing?.description || t('groups.learning.sticker.preview')"
      size="md"
    >
      <template #header>
        <SegmentedControl
          v-model="previewBackdrop"
          :options="backdropOptions"
          size="sm"
          :label="t('groups.learning.sticker.preview')"
          class="ml-auto"
        />
      </template>
      <div v-if="previewing" class="flex flex-col gap-4">
        <div
          class="grid min-h-56 place-items-center overflow-hidden rounded-lg border border-line p-4 transition-colors"
          :class="previewBackdrop === 'dark' ? 'bg-black text-white' : 'bg-white text-black'"
        >
          <div v-if="brokenIds.has(previewing.id)" class="flex flex-col items-center gap-2 text-muted">
            <ImageOff :size="28" aria-hidden="true" />
            <span class="text-xs">{{ t('groups.learning.sticker.imageFailed') }}</span>
          </div>
          <img
            v-else
            :src="learningApi.stickerImage(scene, previewing.id)"
            :alt="previewing.description || t('groups.learning.sticker.image')"
            class="max-h-[60vh] max-w-full object-contain"
            @error="markBroken(previewing.id)"
          />
        </div>
        <div v-if="previewing.meta" class="flex flex-wrap items-center gap-2 text-xs text-muted tabular">
          <span v-if="previewing.meta.width && previewing.meta.height">
            {{ previewing.meta.width }} × {{ previewing.meta.height }}
          </span>
          <span>{{ formatBytes(previewing.meta.bytes) }}</span>
          <Badge v-if="previewing.meta.animated" size="sm">{{ t('groups.learning.sticker.animated') }}</Badge>
        </div>
        <p v-if="previewing.text" class="text-sm text-ink-2">
          <span class="text-muted">{{ t('groups.learning.sticker.text') }}</span>
          · {{ previewing.text }}
        </p>
        <div v-if="previewing.emotions.length || previewing.tags.length" class="flex flex-wrap gap-1.5">
          <Badge v-for="emotion in previewing.emotions" :key="`pe${emotion}`" tone="info">
            {{ emotion }}
          </Badge>
          <Badge v-for="tag in previewing.tags" :key="`pt${tag}`">{{ tag }}</Badge>
        </div>
      </div>
    </Dialog>
  </div>
</template>
