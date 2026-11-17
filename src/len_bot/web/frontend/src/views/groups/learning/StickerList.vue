<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { Pencil } from '@lucide/vue'
import { learningApi, type Review, type Sticker } from '../../../api/learning'
import { keys } from '../../../api/query'
import { formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import TagInput from '../../../ui/TagInput.vue'
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
const list = usePagedList<Sticker, Review>(
  (review, offset) => keys.scene.learning(props.scene, 'stickers', review, offset),
  (review, offset, signal) => learningApi.stickers(props.scene, review, offset, signal),
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

const save = useMutation({
  mutationFn: ({ item, review }: { item: Sticker; review: Review }) => {
    const value = edits.editing(item.id) ? edits.draft(item.id) : fresh(item)
    return learningApi.putSticker(props.scene, item.id, {
      description: value.description.trim() || null,
      text: value.text.trim() || null,
      emotions: value.emotions,
      tags: value.tags,
      review,
    })
  },
  onSuccess: (_, { item }) => edits.stop(item.id),
  onError: (error) =>
    toast.error(t('groups.learning.saveFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})
const busy = (item: Sticker) => save.isPending.value && save.variables.value?.item.id === item.id
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
      <ul class="grid list-none gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <li
          v-for="item in list.page.value.items"
          :key="item.id"
          class="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-surface p-3.5"
        >
          <div class="flex min-w-0 gap-3">
            <img
              :src="learningApi.stickerImage(scene, item.id)"
              :alt="item.description || t('groups.learning.sticker.image')"
              loading="lazy"
              class="size-20 shrink-0 rounded-md bg-fill p-1.5 object-contain sm:size-24"
            />
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
              <Badge v-if="item.status === 'failed'" tone="error" class="self-start">
                {{ t('groups.learning.sticker.failed') }}
              </Badge>
            </div>
          </div>
          <div v-if="edits.editing(item.id)" class="flex flex-col gap-3 border-t border-line pt-3">
            <Field :label="t('groups.learning.sticker.description')">
              <Input v-model="edits.draft(item.id).description" />
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
          <div class="mt-auto flex flex-wrap items-center justify-end gap-1.5 border-t border-line pt-2.5">
            <template v-if="edits.editing(item.id)">
              <Button size="sm" variant="ghost" @click="edits.stop(item.id)">{{ t('common.cancel') }}</Button>
              <Button
                size="sm"
                variant="primary"
                :loading="busy(item)"
                :disabled="!edits.changed(item.id)"
                @click="save.mutate({ item, review: item.review })"
              >
                {{ t('common.save') }}
              </Button>
            </template>
            <template v-else>
              <Button size="sm" variant="ghost" :icon="Pencil" @click="edits.start(item)">
                {{ t('common.edit') }}
              </Button>
              <Button
                v-if="item.review !== 'pending'"
                size="sm"
                variant="ghost"
                :disabled="busy(item)"
                @click="save.mutate({ item, review: 'pending' })"
              >
                {{ t('groups.learning.actions.restore') }}
              </Button>
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
                v-if="item.review !== 'adopted'"
                size="sm"
                variant="primary"
                :loading="busy(item)"
                @click="save.mutate({ item, review: 'adopted' })"
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
  </div>
</template>
