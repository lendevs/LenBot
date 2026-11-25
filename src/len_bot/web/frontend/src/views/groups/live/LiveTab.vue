<script setup lang="ts">
import { computed, nextTick, onMounted, ref, toRef, watch } from 'vue'
import { useEventListener, useResizeObserver } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, AudioLines } from '@lucide/vue'
import { personaAvatar } from '../../../api/host'
import { failedMessage, failedTurn, itemKey } from '../../../api/timeline'
import { host } from '../../../api/hostStore'
import { formatNumber } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Sheet from '../../../ui/Sheet.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Spinner from '../../../ui/Spinner.vue'
import VirtualList from '../../../ui/VirtualList.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useRoles } from '../roleSwitch'
import FocusBar from './FocusBar.vue'
import MessageRow from './MessageRow.vue'
import NoticeRow from './NoticeRow.vue'
import TurnCard from './TurnCard.vue'
import VoiceList from './VoiceList.vue'
import { useTimeline } from './useTimeline'

const props = defineProps<{ scene: string; timeZone: string; persona: string; personaPath?: string }>()

type Filter = 'all' | 'turns' | 'errors'
const isFilter = (value: unknown): value is Filter =>
  value === 'all' || value === 'turns' || value === 'errors'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { roles } = useRoles()
const currentRole = computed(() =>
  props.personaPath ? (roles.value.find((role) => role.path === props.personaPath) ?? null) : null,
)
const personaAvatarUrl = computed(() => (currentRole.value ? personaAvatar(currentRole.value) : null))

/** What VirtualList exposes; refs are unwrapped on the component instance. */
const list = ref<{ scrollToEnd: (behavior?: ScrollBehavior) => void; atEnd: boolean }>()
const pinnedToEnd = computed(() => list.value?.atEnd ?? true)
const { query, items, unreadCount, hasNewerGap, jumping, clearUnread, jumpToLatest } = useTimeline(
  toRef(props, 'scene'),
  { pinnedToEnd },
)
const filter = computed<Filter>({
  get: () => (isFilter(route.query.filter) ? route.query.filter : 'all'),
  set: (value) => {
    const next = { ...route.query }
    if (value === 'all') delete next.filter
    else next.filter = value
    void router.replace({ query: next })
  },
})
const voice = ref(false)
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

const latestLabel = computed(() => {
  if (hasNewerGap.value) return t('groups.live.latestGap')
  if (unreadCount.value > 0) return t('groups.live.latestUnread', { n: formatNumber(unreadCount.value) })
  return t('groups.live.latest')
})

function older() {
  if (!jumping.value && query.hasNextPage.value && !query.isFetchingNextPage.value) void query.fetchNextPage()
}
async function toLatest() {
  if (hasNewerGap.value) {
    try {
      await jumpToLatest()
    } catch (error) {
      toast.error(t('groups.live.readFailed'), {
        detail: describeError(error, t('ui.error.network')).message,
      })
      return
    }
    await nextTick()
  } else {
    clearUnread()
  }
  list.value?.scrollToEnd('smooth')
}
function toggle(id: string, value: boolean) {
  const next = new Set(expanded.value)
  if (value) next.add(id)
  else next.delete(id)
  expanded.value = next
}

/**
 * The list fills the visible viewport below its top edge down to the shell's bottom padding, preventing
 * nested double scrollbars on both desktop and narrow mobile screens.
 */
const frame = ref<HTMLElement>()
const height = ref(480)
function fit() {
  const element = frame.value
  if (!element) return
  const main = element.closest('main')
  const padding = main ? parseFloat(getComputedStyle(main).paddingBottom) : 0
  const viewport = window.visualViewport?.height ?? window.innerHeight
  const top = Math.max(0, element.getBoundingClientRect().top)
  height.value = Math.max(240, Math.floor(viewport - top - padding))
}
useEventListener(window, 'resize', fit)
if (typeof window !== 'undefined' && window.visualViewport) {
  useEventListener(window.visualViewport, 'resize', fit)
}
// The header above wraps differently by width and language; its size moves the list's top edge.
useResizeObserver(() => frame.value?.closest('main') ?? null, fit)
watch(frame, () => nextTick(fit), { immediate: true })
onMounted(() => nextTick(fit))

watch(filter, () => nextTick(() => list.value?.scrollToEnd()))
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3" :aria-label="t('groups.live.label')">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <SegmentedControl v-model="filter" :options="filters" size="sm" :label="t('groups.live.label')" />
      <Button size="sm" variant="ghost" :icon="AudioLines" @click="voice = true">
        {{ t('groups.live.voice') }}
      </Button>
    </div>

    <FocusBar :scene="scene" :time-zone="timeZone" :name-of="nameOf" />
    <Skeleton v-if="query.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="query.isError.value"
      :title="t('groups.live.readFailed')"
      :error="query.error.value"
      :retry="query.refetch"
    />
    <EmptyState v-else-if="!items.length" :title="t('groups.live.empty')" />
    <div v-else ref="frame" class="relative border-t border-line" :style="{ height: `${height}px` }">
      <div v-if="!shown.length" class="flex h-full flex-col items-center justify-center px-4 text-center">
        <EmptyState :title="t('groups.live.noMatch')" compact>
          <Button
            v-if="query.hasNextPage.value"
            size="sm"
            variant="secondary"
            :loading="query.isFetchingNextPage.value"
            @click="older"
          >
            {{ t('groups.live.loadOlder') }}
          </Button>
        </EmptyState>
      </div>
      <VirtualList
        v-else
        ref="list"
        :items="shown"
        :get-key="itemKey"
        :estimate-size="72"
        follow-end
        class="h-full py-2 pr-1.5"
        @reach-start="older"
      >
        <template #header>
          <div class="flex min-h-9 items-center justify-center py-1 text-xs text-subtle">
            <span v-if="query.isFetchingNextPage.value" class="inline-flex items-center gap-2">
              <Spinner :size="13" />
              {{ t('groups.live.older') }}
            </span>
            <span v-else-if="!query.hasNextPage.value">{{ t('groups.live.start') }}</span>
          </div>
        </template>
        <template #default="{ item }">
          <MessageRow
            v-if="item.type === 'message'"
            :message="item"
            :time-zone="timeZone"
            :persona="persona"
            :persona-avatar="personaAvatarUrl"
            :name-of="nameOf"
          />
          <NoticeRow
            v-else-if="item.type === 'notice'"
            :notice="item"
            :time-zone="timeZone"
            :name-of="nameOf"
          />
          <TurnCard
            v-else
            :turn="item"
            :scene="scene"
            :time-zone="timeZone"
            :persona-key="currentRole?.key"
            :persona-directory="currentRole?.path"
            :name-of="nameOf"
            :expanded="expanded.has(item.turn_id)"
            @update:expanded="(value: boolean) => toggle(item.turn_id, value)"
          />
        </template>
      </VirtualList>
      <Transition name="ui-rise">
        <div
          v-if="shown.length && list && (!list.atEnd || hasNewerGap)"
          class="pointer-events-none absolute inset-x-0 bottom-3 z-10 flex justify-center"
        >
          <span class="pointer-events-auto rounded-md shadow-float">
            <Button
              size="sm"
              :variant="unreadCount > 0 || hasNewerGap ? 'primary' : 'secondary'"
              :icon="ArrowDown"
              :loading="jumping"
              @click="void toLatest()"
            >
              {{ latestLabel }}
            </Button>
          </span>
        </div>
      </Transition>
    </div>

    <Sheet v-model:open="voice" :title="t('groups.live.voice')" size="lg">
      <VoiceList :scene="scene" />
    </Sheet>
  </section>
</template>
