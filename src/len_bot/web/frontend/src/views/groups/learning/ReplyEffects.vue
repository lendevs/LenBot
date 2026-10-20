<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ChevronDown } from '@lucide/vue'
import { learningApi, type EffectState, type ReplyEffect } from '../../../api/learning'
import { keys } from '../../../api/query'
import { formatDateTime } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import StatTile from '../../../ui/StatTile.vue'
import { useLiveLabels } from '../live/labels'
import Pager from './Pager.vue'
import { usePagedList } from './usePagedList'

const props = defineProps<{ scene: string; timeZone: string }>()

const { t } = useI18n()
const labels = useLiveLabels()
const summary = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'effects')),
  queryFn: ({ signal }) => learningApi.effects(props.scene, signal),
})
const reactions = ['agree', 'continue', 'correct', 'negative', 'unrelated', 'uncertain'] as const
const tones: Record<EffectState, Tone> = {
  agree: 'success',
  continue: 'success',
  correct: 'warning',
  negative: 'error',
  unrelated: 'neutral',
  uncertain: 'neutral',
  observing: 'info',
  no_messages: 'neutral',
  waiting: 'info',
  failed: 'error',
}

type Filter = 'all' | 'attention'
const list = usePagedList<ReplyEffect, Filter>(
  (filter, offset) => keys.scene.learning(props.scene, 'effect-items', filter, offset),
  (filter, offset, signal) =>
    learningApi.effectItems(props.scene, filter === 'all' ? undefined : filter, offset, signal),
  'all',
)
const filters = computed(() =>
  (['all', 'attention'] as const).map((value) => ({ value, label: t(`groups.learning.effects.filters.${value}`) })),
)
const open = ref<number | null>(null)
const detail = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'effect', open.value)),
  queryFn: ({ signal }) => learningApi.effect(props.scene, open.value!, signal),
  enabled: computed(() => open.value !== null),
})
</script>

<template>
  <div class="flex flex-col gap-5">
    <Skeleton v-if="summary.isPending.value" :lines="2" />
    <ErrorNote
      v-else-if="summary.isError.value"
      :title="t('groups.learning.readFailed')"
      :error="summary.error.value"
      :retry="summary.refetch"
    />
    <template v-else-if="summary.data.value">
      <p v-if="!summary.data.value.enabled" class="text-sm text-muted">{{ t('groups.learning.effects.off') }}</p>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile
          v-for="reaction in reactions"
          :key="reaction"
          :label="t(`groups.learning.effects.states.${reaction}`)"
          :value="summary.data.value.distribution.states[reaction]"
        />
      </div>
      <p class="text-xs text-subtle">
        {{ t('groups.learning.effects.samples', { n: summary.data.value.distribution.samples, days: summary.data.value.days }) }}
      </p>
    </template>

    <SegmentedControl
      :model-value="list.filter.value"
      :options="filters"
      size="sm"
      :label="t('groups.learning.kinds.effects')"
      class="self-start"
      @update:model-value="(value: Filter) => list.choose(value)"
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
        <li v-for="item in list.page.value.items" :key="item.id">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center gap-3 py-3 text-left text-sm hover:bg-hover focus-visible:focus-ring"
            :aria-expanded="open === item.id"
            @click="open = open === item.id ? null : item.id"
          >
            <Badge :tone="tones[item.state]">{{ t(`groups.learning.effects.states.${item.state}`) }}</Badge>
            <span class="min-w-0 flex-1 truncate text-ink-2">{{ item.reason || item.channels.map(labels.channel).join(' · ') }}</span>
            <time class="shrink-0 text-xs text-subtle tabular">{{ formatDateTime(item.first_sent_at, { timeZone }) }}</time>
            <ChevronDown :size="15" class="shrink-0 text-muted transition-transform" :class="open === item.id && 'rotate-180'" aria-hidden="true" />
          </button>
          <div v-if="open === item.id" class="flex flex-col gap-3 pb-4 pl-1 text-sm">
            <Skeleton v-if="detail.isPending.value" :lines="3" />
            <ErrorNote v-else-if="detail.isError.value" :title="t('groups.learning.readFailed')" :error="detail.error.value" :retry="detail.refetch" />
            <template v-else-if="detail.data.value">
              <div v-for="part in ['before', 'expression', 'followups'] as const" :key="part" class="flex flex-col gap-1">
                <p class="text-xs font-medium text-muted">{{ t(`groups.learning.effects.parts.${part}`) }}</p>
                <p v-if="!detail.data.value[part].length" class="text-subtle">{{ t('common.none') }}</p>
                <pre
                  v-for="message in detail.data.value[part]"
                  :key="message.record"
                  class="rounded-md px-3 py-2 font-mono text-xs leading-5 break-words whitespace-pre-wrap"
                  :class="part === 'expression' ? 'bg-brand-soft text-ink' : 'bg-fill text-ink-2'"
                >{{ message.rendered ?? t('groups.learning.effects.gone') }}</pre>
              </div>
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
