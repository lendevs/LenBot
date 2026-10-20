<script setup lang="ts">
import { computed, nextTick, ref, toRef, watch } from 'vue'
import { useEventListener, useResizeObserver } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { ArrowDown, AudioLines } from '@lucide/vue'
import { failedMessage, failedTurn, itemKey, type TimelineItem } from '../../../api/timeline'
import { host } from '../../../api/hostStore'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Sheet from '../../../ui/Sheet.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Spinner from '../../../ui/Spinner.vue'
import VirtualList from '../../../ui/VirtualList.vue'
import MessageRow from './MessageRow.vue'
import NoticeRow from './NoticeRow.vue'
import TurnCard from './TurnCard.vue'
import VoiceList from './VoiceList.vue'
import { useTimeline } from './useTimeline'

const props = defineProps<{ scene: string; timeZone: string; persona: string }>()

type Filter = 'all' | 'turns' | 'errors'
type Row = TimelineItem | { type: 'edge' }

const { t } = useI18n()
const { query, items } = useTimeline(toRef(props, 'scene'))
const filter = ref<Filter>('all')
const voice = ref(false)
/** What VirtualList exposes; refs are unwrapped on the component instance. */
const list = ref<{ scrollToEnd: (behavior?: ScrollBehavior) => void; atEnd: boolean }>()
const expanded = ref(new Set<string>())

const filters = computed(() =>
  (['all', 'turns', 'errors'] as const).map((value) => ({ value, label: t(`groups.live.filters.${value}`) })),
)
const shown = computed(() =>
  items.value.filter((item) => {
    if (filter.value === 'turns') return item.type === 'turn'
    if (filter.value === 'errors')
      return item.type === 'turn'
        ? failedTurn(item.status) || item.error !== null
        : item.type === 'message' && failedMessage(item.status)
    return true
  }),
)
const rows = computed<Row[]>(() => [{ type: 'edge' }, ...shown.value])
/** Names seen in the loaded messages; the Bot's own account is the persona. */
const names = computed(() => {
  const found = new Map<string, string>()
  for (const item of items.value) {
    if (item.type === 'message' && !item.is_self) {
      const name = item.sender.card || item.sender.nickname
      if (name) found.set(item.sender.uid, name)
    }
  }
  return found
})
function nameOf(uid: string) {
  if (uid === host.state?.bot_id) return props.persona
  return names.value.get(uid) ?? uid.split(':').pop() ?? uid
}
const rowKey = (row: Row) => (row.type === 'edge' ? 'edge' : itemKey(row))

function older() {
  if (query.hasNextPage.value && !query.isFetchingNextPage.value) void query.fetchNextPage()
}
function toggle(id: string, value: boolean) {
  const next = new Set(expanded.value)
  if (value) next.add(id)
  else next.delete(id)
  expanded.value = next
}
/**
 * The list fills the window below its own top edge, down to the shell's bottom padding, so the page itself
 * does not scroll and the newest row sits at the bottom of the screen.
 */
const frame = ref<HTMLElement>()
const height = ref(480)
function fit() {
  const element = frame.value
  if (!element) return
  const main = element.closest('main')
  const padding = main ? parseFloat(getComputedStyle(main).paddingBottom) : 0
  const top = element.getBoundingClientRect().top + window.scrollY
  height.value = Math.max(320, Math.floor(window.innerHeight - top - padding))
}
useEventListener(window, 'resize', fit)
// The header above wraps differently by width and language; its size moves the list's top edge.
useResizeObserver(() => frame.value?.closest('main') ?? null, fit)
watch(frame, () => nextTick(fit))

watch(filter, () => nextTick(() => list.value?.scrollToEnd()))
</script>

<template>
  <section class="flex flex-col gap-3" :aria-label="t('groups.live.label')">
    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl v-model="filter" :options="filters" size="sm" :label="t('groups.live.label')" />
      <Button size="sm" variant="ghost" :icon="AudioLines" class="ml-auto" @click="voice = true">
        {{ t('groups.live.voice') }}
      </Button>
    </div>

    <Skeleton v-if="query.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="query.isError.value"
      :title="t('groups.live.readFailed')"
      :error="query.error.value"
      :retry="query.refetch"
    />
    <EmptyState v-else-if="!items.length" :title="t('groups.live.empty')" />
    <div v-else ref="frame" class="relative" :style="{ height: `${height}px` }">
      <VirtualList
        ref="list"
        :items="rows"
        :get-key="rowKey"
        :estimate-size="72"
        follow-end
        class="h-full pr-1"
        @reach-start="older"
      >
        <template #default="{ item }">
          <div v-if="item.type === 'edge'" class="flex min-h-10 items-center justify-center text-xs text-subtle">
            <span v-if="query.isFetchingNextPage.value" class="inline-flex items-center gap-2">
              <Spinner :size="13" />{{ t('groups.live.older') }}
            </span>
            <span v-else-if="!query.hasNextPage.value">{{ t('groups.live.start') }}</span>
            <span v-else-if="!shown.length">{{ t('groups.live.noMatch') }}</span>
          </div>
          <MessageRow
            v-else-if="item.type === 'message'"
            :message="item"
            :time-zone="timeZone"
            :persona="persona"
            :name-of="nameOf"
          />
          <NoticeRow v-else-if="item.type === 'notice'" :notice="item" :time-zone="timeZone" :name-of="nameOf" />
          <TurnCard
            v-else
            :turn="item"
            :scene="scene"
            :time-zone="timeZone"
            :expanded="expanded.has(item.turn_id)"
            @update:expanded="(value: boolean) => toggle(item.turn_id, value)"
          />
        </template>
      </VirtualList>
      <Transition name="ui-rise">
        <Button
          v-if="list && !list.atEnd"
          size="sm"
          :icon="ArrowDown"
          class="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-float"
          @click="list.scrollToEnd('smooth')"
        >
          {{ t('groups.live.latest') }}
        </Button>
      </Transition>
    </div>

    <Sheet v-model:open="voice" :title="t('groups.live.voice')" size="lg">
      <VoiceList :scene="scene" />
    </Sheet>
  </section>
</template>
