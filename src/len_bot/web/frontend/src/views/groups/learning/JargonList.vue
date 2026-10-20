<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { Pencil } from '@lucide/vue'
import { learningApi, type JargonTerm, type Review } from '../../../api/learning'
import { keys } from '../../../api/query'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import Pager from './Pager.vue'
import { useEdits } from './useEdits'
import { usePagedList } from './usePagedList'

const props = defineProps<{ scene: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const list = usePagedList<JargonTerm, Review>(
  (status, offset) => keys.scene.learning(props.scene, 'jargon', status, offset),
  (status, offset, signal) => learningApi.jargon(props.scene, status, offset, signal),
  'pending',
)
const filters = computed(() =>
  (['pending', 'adopted', 'rejected'] as const).map((value) => ({ value, label: t(`groups.learning.jargon.${value}`) })),
)
const edits = useEdits((item: JargonTerm) => ({ meaning: item.meaning ?? item.latest_meaning ?? '' }))
watch(edits.dirty, (value) => emit('dirty', value), { immediate: true })

const save = useMutation({
  mutationFn: ({ item, status }: { item: JargonTerm; status: Review }) =>
    learningApi.putJargon(props.scene, item.id, {
      // Fixing a meaning saves the edited text; going back to automatic drops it.
      meaning: status === 'pending' ? null : (edits.editing(item.id) ? edits.draft(item.id).meaning : item.meaning)?.trim() || null,
      status,
    }),
  onSuccess: (_, { item }) => edits.stop(item.id),
  onError: (error) =>
    toast.error(t('groups.learning.saveFailed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})
const busy = (item: JargonTerm) => save.isPending.value && save.variables.value?.item.id === item.id
</script>

<template>
  <div class="flex flex-col gap-4">
    <SegmentedControl
      :model-value="list.filter.value"
      :options="filters"
      size="sm"
      :label="t('groups.learning.kinds.jargon')"
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
        <li v-for="item in list.page.value.items" :key="item.id" class="flex flex-col gap-2.5 py-3.5">
          <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <strong class="text-base font-semibold text-ink">{{ item.term }}</strong>
            <span class="text-xs text-subtle">{{ t('groups.learning.jargon.count', { n: item.count }) }}</span>
            <Badge v-if="item.status === 'adopted'" tone="brand">{{ t('groups.learning.jargon.fixed') }}</Badge>
          </div>
          <Field v-if="edits.editing(item.id)" :label="t('groups.learning.jargon.meaning')">
            <Input v-model="edits.draft(item.id).meaning" />
          </Field>
          <template v-else>
            <p v-if="item.status === 'adopted'" class="text-sm break-words text-ink">{{ item.meaning }}</p>
            <p class="text-sm break-words" :class="item.status === 'adopted' ? 'text-muted' : 'text-ink-2'">
              {{ t('groups.learning.jargon.latest') }}{{ item.latest_meaning || t('groups.learning.jargon.noMeaning') }}
            </p>
          </template>
          <div class="flex flex-wrap items-center justify-end gap-2">
            <template v-if="edits.editing(item.id)">
              <Button size="sm" variant="ghost" @click="edits.stop(item.id)">{{ t('common.cancel') }}</Button>
              <Button
                size="sm"
                variant="primary"
                :loading="busy(item)"
                :disabled="!edits.draft(item.id).meaning.trim()"
                @click="save.mutate({ item, status: 'adopted' })"
              >
                {{ t('groups.learning.jargon.fix') }}
              </Button>
            </template>
            <template v-else>
              <Button
                v-if="item.status !== 'pending'"
                size="sm"
                variant="ghost"
                :disabled="busy(item)"
                @click="save.mutate({ item, status: 'pending' })"
              >
                {{ t('groups.learning.jargon.automatic') }}
              </Button>
              <Button
                v-if="item.status !== 'rejected'"
                size="sm"
                variant="ghost"
                :disabled="busy(item)"
                @click="save.mutate({ item, status: 'rejected' })"
              >
                {{ t('groups.learning.jargon.disable') }}
              </Button>
              <Button size="sm" :icon="Pencil" :disabled="busy(item)" @click="edits.start(item)">
                {{ item.status === 'adopted' ? t('common.edit') : t('groups.learning.jargon.fix') }}
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
