<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { BookmarkPlus, Pencil } from '@lucide/vue'
import { learningApi, type Expression, type Review } from '../../../api/learning'
import { keys } from '../../../api/query'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import Pager from './Pager.vue'
import { useEdits } from './useEdits'
import { usePagedList } from './usePagedList'

const props = defineProps<{ scene: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const list = usePagedList<Expression, Review>(
  (status, offset) => keys.scene.learning(props.scene, 'expressions', status, offset),
  (status, offset, signal) => learningApi.expressions(props.scene, status, offset, signal),
  'pending',
)
const filters = computed(() =>
  (['pending', 'adopted', 'rejected'] as const).map((value) => ({
    value,
    label: t(`groups.learning.review.${value}`),
  })),
)
const edits = useEdits((item: Expression) => ({ situation: item.situation, style: item.style }))
watch(edits.dirty, (value) => emit('dirty', value), { immediate: true })

const failed = (error: unknown) =>
  toast.error(t('groups.learning.saveFailed'), {
    detail: describeError(error, t('ui.error.network')).message,
  })
const save = useMutation({
  mutationFn: ({ item, status }: { item: Expression; status: Review }) => {
    const text = edits.editing(item.id)
      ? edits.draft(item.id)
      : { situation: item.situation, style: item.style }
    return learningApi.putExpression(props.scene, item.id, {
      situation: text.situation.trim(),
      style: text.style.trim(),
      status,
    })
  },
  onSuccess: (_, { item }) => edits.stop(item.id),
  onError: failed,
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})
const busy = (item: Expression) => save.isPending.value && save.variables.value?.item.id === item.id
const invalid = (item: Expression) => {
  const draft = edits.draft(item.id)
  return Boolean(draft) && (!draft.situation.trim() || !draft.style.trim())
}

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
  <div class="flex flex-col gap-4">
    <SegmentedControl
      :model-value="list.filter.value"
      :options="filters"
      size="sm"
      :label="t('groups.learning.kinds.expressions')"
      class="self-start"
      @update:model-value="(value: Review) => list.choose(value)"
    />
    <Skeleton v-if="list.query.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="list.query.isError.value"
      :title="t('groups.learning.readFailed')"
      :error="list.query.error.value"
      :retry="list.query.refetch"
    />
    <EmptyState v-else-if="!list.page.value?.items.length" :title="t('groups.learning.empty')" compact />
    <template v-else-if="list.page.value">
      <ul class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li v-for="item in list.page.value.items" :key="item.id" class="flex flex-col gap-3 py-3.5">
          <div v-if="edits.editing(item.id)" class="grid gap-3 sm:grid-cols-2">
            <Field :label="t('groups.learning.expression.situation')">
              <Textarea v-model="edits.draft(item.id).situation" :rows="1" />
            </Field>
            <Field :label="t('groups.learning.expression.style')">
              <Textarea v-model="edits.draft(item.id).style" :rows="1" />
            </Field>
          </div>
          <div v-else class="flex min-w-0 flex-col gap-1">
            <p class="text-xs text-muted">{{ item.situation }}</p>
            <p class="text-base break-words text-ink">{{ item.style }}</p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-xs text-subtle">
              {{ t('groups.learning.sources', { n: item.count }) }}
            </span>
            <Badge v-if="(item.disliked ?? 0) >= 2" tone="warning">
              {{ t('groups.learning.expression.disliked', { n: item.disliked }) }}
            </Badge>
            <span class="mr-auto" />
            <template v-if="edits.editing(item.id)">
              <Button size="sm" variant="ghost" @click="edits.stop(item.id)">{{ t('common.cancel') }}</Button>
              <Button
                size="sm"
                variant="primary"
                :loading="busy(item)"
                :disabled="invalid(item) || !edits.changed(item.id)"
                @click="save.mutate({ item, status: item.status })"
              >
                {{ t('common.save') }}
              </Button>
            </template>
            <template v-else>
              <Button size="sm" variant="ghost" :icon="Pencil" @click="edits.start(item)">
                {{ t('common.edit') }}
              </Button>
              <Button
                v-if="item.status === 'adopted'"
                size="sm"
                variant="ghost"
                :icon="BookmarkPlus"
                @click="
                  example = { expression_id: item.id, context: item.situation, line: item.style, tags: [] }
                "
              >
                {{ t('groups.learning.example.action') }}
              </Button>
              <Button
                v-if="item.status !== 'pending'"
                size="sm"
                variant="ghost"
                :disabled="busy(item)"
                @click="save.mutate({ item, status: 'pending' })"
              >
                {{ t('groups.learning.actions.restore') }}
              </Button>
              <Button
                v-if="item.status !== 'rejected'"
                size="sm"
                variant="ghost"
                :disabled="busy(item)"
                @click="save.mutate({ item, status: 'rejected' })"
              >
                {{ t('groups.learning.actions.reject') }}
              </Button>
              <Button
                v-if="item.status !== 'adopted'"
                size="sm"
                variant="primary"
                :loading="busy(item)"
                @click="save.mutate({ item, status: 'adopted' })"
              >
                {{ t('groups.learning.actions.adopt') }}
              </Button>
            </template>
          </div>
        </li>
      </ul>
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
