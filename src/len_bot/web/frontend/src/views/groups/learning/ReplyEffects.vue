<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ChevronDown, X } from '@lucide/vue'
import { learningApi, type EffectState, type Reaction, type ReplyEffect } from '../../../api/learning'
import { keys } from '../../../api/query'
import { formatDateTime, formatNumber } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
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
const days = ref<'7' | '30'>('7')
const dayCount = computed(() => Number(days.value))
const dayOptions = computed(() => [
  { value: '7' as const, label: t('groups.learning.effects.days7') },
  { value: '30' as const, label: t('groups.learning.effects.days30') },
])

const summary = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'effects', dayCount.value)),
  queryFn: ({ signal }) => learningApi.effects(props.scene, dayCount.value, signal),
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

type Filter = 'all' | 'attention' | Reaction
const list = usePagedList<ReplyEffect, Filter>(
  (filter, offset) => keys.scene.learning(props.scene, 'effect-items', dayCount.value, filter, offset),
  (filter, offset, signal) =>
    learningApi.effectItems(
      props.scene,
      filter === 'all' ? undefined : filter,
      offset,
      dayCount.value,
      signal,
    ),
  'all',
)
watch(days, () => {
  list.offset.value = 0
  open.value = null
})
const filters = computed<{ value: Filter; label: string }[]>(() =>
  (['all', 'attention'] as const).map((value) => ({
    value,
    label: t(`groups.learning.effects.filters.${value}`),
  })),
)
const activeReaction = computed<Reaction | null>(() =>
  (reactions as readonly string[]).includes(list.filter.value) ? (list.filter.value as Reaction) : null,
)
function toggleReaction(reaction: Reaction) {
  list.choose(list.filter.value === reaction ? 'all' : reaction)
}

const open = ref<number | null>(null)
const detail = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'effect', open.value)),
  queryFn: ({ signal }) => learningApi.effect(props.scene, open.value!, signal),
  enabled: computed(() => open.value !== null),
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <Skeleton v-if="summary.isPending.value" :lines="2" />
    <ErrorNote
      v-else-if="summary.isError.value"
      :title="t('groups.learning.readFailed')"
      :error="summary.error.value"
      :retry="summary.refetch"
    />
    <div v-else-if="summary.data.value" class="flex flex-col gap-3 border-b border-line pb-5">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p v-if="!summary.data.value.enabled" class="text-sm text-muted">
          {{ t('groups.learning.effects.off') }}
        </p>
        <p v-else class="text-xs text-subtle tabular">
          {{
            t('groups.learning.effects.samples', {
              n: formatNumber(summary.data.value.distribution.samples),
              days: formatNumber(summary.data.value.days),
            })
          }}
        </p>
        <SegmentedControl
          v-model="days"
          :options="dayOptions"
          size="sm"
          :label="t('groups.learning.effects.range')"
        />
      </div>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <button
          v-for="reaction in reactions"
          :key="reaction"
          type="button"
          class="cursor-pointer rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:focus-ring"
          :class="
            list.filter.value === reaction
              ? 'border-primary bg-selected'
              : 'border-line bg-surface hover:border-line-strong hover:bg-hover'
          "
          :aria-pressed="list.filter.value === reaction"
          @click="toggleReaction(reaction)"
        >
          <StatTile
            :label="t(`groups.learning.effects.states.${reaction}`)"
            :value="summary.data.value.distribution.states[reaction]"
          />
        </button>
      </div>
      <p v-if="!summary.data.value.enabled" class="text-xs text-subtle tabular">
        {{
          t('groups.learning.effects.samples', {
            n: formatNumber(summary.data.value.distribution.samples),
            days: formatNumber(summary.data.value.days),
          })
        }}
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl
        :model-value="list.filter.value"
        :options="filters"
        size="sm"
        :label="t('groups.learning.kinds.effects')"
        @update:model-value="(value: Filter) => list.choose(value)"
      />
      <Button v-if="activeReaction" size="sm" variant="secondary" :icon-right="X" @click="list.choose('all')">
        {{ t(`groups.learning.effects.states.${activeReaction}`) }}
      </Button>
    </div>

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
            class="flex w-full cursor-pointer items-center gap-3 px-2 py-3 text-left text-sm transition-colors duration-150 hover:bg-hover focus-visible:focus-ring"
            :aria-expanded="open === item.id"
            @click="open = open === item.id ? null : item.id"
          >
            <Badge :tone="tones[item.state]">{{ t(`groups.learning.effects.states.${item.state}`) }}</Badge>
            <span class="min-w-0 flex-1 truncate text-ink-2">
              {{ item.reason || item.channels.map(labels.channel).join(' · ') }}
            </span>
            <time class="shrink-0 text-xs text-subtle tabular">
              {{ formatDateTime(item.first_sent_at, { timeZone }) }}
            </time>
            <ChevronDown
              :size="15"
              class="shrink-0 text-muted transition-transform duration-150"
              :class="open === item.id && 'rotate-180'"
              aria-hidden="true"
            />
          </button>
          <div v-if="open === item.id" class="flex flex-col gap-3 px-2 pb-4 text-sm">
            <div v-if="item.turn_id" class="flex justify-end">
              <Button
                size="sm"
                variant="ghost"
                :to="{ name: 'host-logs', query: { scene, turn: item.turn_id } }"
              >
                {{ t('groups.learning.effects.turn') }}
              </Button>
            </div>
            <Skeleton v-if="detail.isPending.value" :lines="3" />
            <ErrorNote
              v-else-if="detail.isError.value"
              :title="t('groups.learning.readFailed')"
              :error="detail.error.value"
              :retry="detail.refetch"
            />
            <template v-else-if="detail.data.value">
              <div
                v-for="part in ['before', 'expression', 'followups'] as const"
                :key="part"
                class="flex flex-col gap-1.5"
              >
                <p class="text-xs font-medium text-muted">{{ t(`groups.learning.effects.parts.${part}`) }}</p>
                <p v-if="!detail.data.value[part].length" class="text-subtle">{{ t('common.none') }}</p>
                <pre
                  v-for="message in detail.data.value[part]"
                  :key="message.record"
                  class="rounded-md px-3 py-2 font-mono text-xs leading-5 break-words whitespace-pre-wrap"
                  :class="
                    part === 'expression'
                      ? 'border border-line-strong bg-surface text-ink'
                      : 'bg-fill text-ink-2'
                  "
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
