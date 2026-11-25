<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { Pencil, Search } from '@lucide/vue'
import { learningApi, type JargonTerm, type JargonView, type Review } from '../../../api/learning'
import { keys } from '../../../api/query'
import { formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import Pager from './Pager.vue'
import { useEdits } from './useEdits'
import { usePagedList } from './usePagedList'

const props = defineProps<{ scene: string }>()
const filter = defineModel<JargonView>('filter', { default: 'learned' })
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const list = usePagedList<JargonTerm, JargonView>(
  (status, offset) => keys.scene.learning(props.scene, 'jargon', status, offset),
  (status, offset, signal) => learningApi.jargon(props.scene, status, offset, signal),
  filter,
)
const edits = useEdits((item: JargonTerm) => ({ meaning: item.meaning ?? item.latest_meaning ?? '' }))
watch(edits.dirty, (value) => emit('dirty', value), { immediate: true })

const search = ref('')
const keyword = computed(() => search.value.trim().toLowerCase())
const filteredItems = computed(() => {
  const rows = list.page.value?.items ?? []
  const q = keyword.value
  if (!q) return rows
  return rows.filter((item) =>
    [
      item.term,
      item.meaning,
      item.latest_meaning,
      item.judgment?.usage_condition,
      item.judgment?.difference,
      item.judgment?.ordinary_meaning,
      ...(item.judgment?.aliases ?? []),
    ].some((part) => part?.toLowerCase().includes(q)),
  )
})

const rowErrors = reactive<Record<number, unknown>>({})
watch([() => props.scene, list.filter, list.offset], () => {
  edits.clear()
  for (const key of Object.keys(rowErrors)) delete rowErrors[Number(key)]
})
watch(
  () => [list.page.value, list.query.isPlaceholderData.value] as const,
  ([page, placeholder]) => {
    if (!page || placeholder) return
    edits.prune(page.items.map((item) => item.id))
  },
)

const save = useMutation({
  mutationFn: ({ item, status }: { item: JargonTerm; status: Review }) => {
    delete rowErrors[item.id]
    return learningApi.putJargon(props.scene, item.id, {
      // Fixing a meaning saves the edited text; going back to automatic drops it.
      meaning:
        status === 'pending'
          ? null
          : (edits.editing(item.id) ? edits.draft(item.id).meaning : item.meaning)?.trim() || null,
      status,
    })
  },
  onSuccess: (_, { item, status }) => {
    edits.stop(item.id)
    delete rowErrors[item.id]
    toast.success(
      t(
        status === 'adopted'
          ? 'groups.learning.jargon.fixedDone'
          : status === 'rejected'
            ? 'groups.learning.jargon.disabledDone'
            : 'groups.learning.jargon.automaticDone',
      ),
    )
  },
  onError: (error, { item }) => {
    rowErrors[item.id] = error
    toast.error(t('groups.learning.saveFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
  },
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})
const busy = (item: JargonTerm) => save.isPending.value && save.variables.value?.item.id === item.id
function startEdit(item: JargonTerm) {
  delete rowErrors[item.id]
  edits.start(item)
}
function stopEdit(id: number) {
  delete rowErrors[id]
  edits.stop(id)
}
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
      <p v-if="!filteredItems.length" class="py-6 text-center text-sm text-muted">
        {{ t('common.noResults') }}
      </p>
      <TransitionGroup
        v-else
        tag="ul"
        name="ui-list"
        class="flex list-none flex-col divide-y divide-line border-y border-line"
      >
        <li v-for="item in filteredItems" :key="item.id" class="flex flex-col gap-2.5 py-4">
          <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <strong class="text-base font-semibold text-ink">{{ item.term }}</strong>
            <Badge v-if="item.status === 'adopted'" tone="success">
              {{ t('groups.learning.jargon.fixed') }}
            </Badge>
            <Badge v-else-if="item.classification === 'ordinary'">
              {{ t('groups.learning.jargon.ordinaryLabel') }}
            </Badge>
            <span class="text-xs text-subtle tabular">
              {{ t('groups.learning.jargon.count', { n: formatNumber(item.count) }) }}
            </span>
            <span v-if="item.judgment?.aliases.length" class="text-xs text-muted">
              · {{ item.judgment.aliases.join(' / ') }}
            </span>
          </div>
          <Field v-if="edits.editing(item.id)" :label="t('groups.learning.jargon.meaning')">
            <Input v-model="edits.draft(item.id).meaning" />
          </Field>
          <template v-else>
            <p v-if="item.status === 'adopted'" class="text-sm leading-6 break-words text-ink">
              {{ item.meaning }}
            </p>
            <p
              class="text-sm leading-6 break-words"
              :class="item.status === 'adopted' ? 'text-muted' : 'text-ink-2'"
            >
              <span class="text-muted">{{ t('groups.learning.jargon.latest') }}</span>
              {{ item.latest_meaning || t('groups.learning.jargon.noMeaning') }}
            </p>
            <p v-if="item.judgment?.usage_condition" class="text-sm break-words text-ink-2">
              <span class="text-muted">{{ t('groups.learning.jargon.usageCondition') }}</span>
              {{ item.judgment.usage_condition }}
            </p>
            <p v-if="item.judgment?.difference" class="text-sm break-words text-ink-2">
              <span class="text-muted">{{ t('groups.learning.jargon.difference') }}</span>
              {{ item.judgment.difference }}
            </p>
            <p v-if="item.judgment?.ordinary_meaning" class="text-sm break-words text-ink-2">
              <span class="text-muted">{{ t('groups.learning.jargon.ordinary') }}</span>
              {{ item.judgment.ordinary_meaning }}
            </p>
            <div
              v-if="item.judgment?.evidence.length"
              class="flex flex-col gap-1.5 pt-0.5 text-sm text-ink-2"
            >
              <span class="text-xs text-muted tabular">
                {{
                  t('groups.learning.jargon.evidenceCount', {
                    n: formatNumber(item.judgment.evidence.length),
                  })
                }}
              </span>
              <blockquote
                v-for="evidence in item.judgment.evidence"
                :key="evidence.message_id"
                class="border-l-2 border-line pl-3 text-sm break-words"
              >
                {{ evidence.quote }}
                <span class="ml-1 text-xs text-subtle tabular">#{{ evidence.message_id }}</span>
              </blockquote>
            </div>
          </template>
          <div class="flex flex-wrap items-center justify-end gap-1.5">
            <template v-if="edits.editing(item.id)">
              <Button size="sm" variant="ghost" @click="stopEdit(item.id)">{{ t('common.cancel') }}</Button>
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
              <Button size="sm" :icon="Pencil" :disabled="busy(item)" @click="startEdit(item)">
                {{ item.status === 'adopted' ? t('common.edit') : t('groups.learning.jargon.fix') }}
              </Button>
            </template>
          </div>
          <ErrorNote
            v-if="rowErrors[item.id]"
            :title="t('groups.learning.saveFailed')"
            :error="rowErrors[item.id]"
          />
        </li>
      </TransitionGroup>
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
