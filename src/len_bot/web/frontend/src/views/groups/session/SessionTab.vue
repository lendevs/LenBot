<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRef, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery, useQueryClient, type InfiniteData } from '@tanstack/vue-query'
import { useResizeObserver } from '@vueuse/core'
import { ChevronDown, RefreshCcw, Sparkles } from '@lucide/vue'
import { keys } from '../../../api/query'
import { sessionApi, type SessionEntry, type SessionPage } from '../../../api/session'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { useHostEvent } from '../../../realtime/stream'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import FormSection from '../../../ui/FormSection.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import Timeline from '../../../ui/Timeline.vue'
import EntryItem from './EntryItem.vue'
import { useSessionActions } from './useSessionActions'

const props = defineProps<{ scene: string; timeZone: string }>()

const { t } = useI18n()
const client = useQueryClient()
const scene = toRef(props, 'scene')
const everything = ref(false)
const { starting, compacting, startSession, compactRecap } = useSessionActions(scene)

const queryKey = computed(() => keys.scene.session(props.scene, !everything.value))
const query = useInfiniteQuery({
  queryKey,
  queryFn: ({ pageParam, signal }) =>
    sessionApi.page(props.scene, { before: pageParam, activeOnly: !everything.value }, signal),
  initialPageParam: undefined as number | undefined,
  getNextPageParam: (page) => page.next_before ?? undefined,
})
const newest = computed(() => query.data.value?.pages[0])
/** Pages are newest first; entries inside a page are oldest first. */
const entries = computed<SessionEntry[]>(() =>
  [...(query.data.value?.pages ?? [])].reverse().flatMap((page) => page.entries),
)
const results = computed(() => {
  const found = new Map<string, SessionEntry>()
  for (const entry of entries.value) {
    if (entry.message.role === 'tool' && entry.message.tool_call_id)
      found.set(entry.message.tool_call_id, entry)
  }
  return found
})
/** Tool results that answer a loaded call are shown under the call instead of on their own. */
const shown = computed(() => {
  const calls = new Set(
    entries.value.flatMap((entry) => (entry.message.tool_calls ?? []).map((call) => call.id)),
  )
  return entries.value.filter(
    (entry) =>
      !(entry.message.role === 'tool' && entry.message.tool_call_id && calls.has(entry.message.tool_call_id)),
  )
})
const firstActive = computed(() => shown.value.findIndex((entry) => entry.active))

type SessionData = InfiniteData<SessionPage, number | undefined>

/**
 * Merge a freshly fetched newest page into the loaded session pages without dropping older pages that the
 * user already scrolled back to load.
 */
function mergeNewestSession(data: SessionData, fresh: SessionPage): SessionData {
  if (!data.pages.length || fresh.next_before === null) {
    return { pages: [fresh], pageParams: [undefined] }
  }
  let maxLoadedSeq: number | undefined
  for (const page of data.pages) {
    for (const entry of page.entries) {
      if (maxLoadedSeq === undefined || entry.seq > maxLoadedSeq) maxLoadedSeq = entry.seq
    }
  }
  if (maxLoadedSeq === undefined || (fresh.entries.length > 0 && fresh.entries[0]!.seq > maxLoadedSeq)) {
    return { pages: [fresh], pageParams: [undefined] }
  }
  const updates = new Map(fresh.entries.map((entry) => [entry.seq, entry]))
  const prepared = data.pages.map((page) => {
    let entries = page.entries.map((entry) => {
      const next = updates.get(entry.seq)
      if (next) {
        updates.delete(entry.seq)
        return next
      }
      const active = entry.seq > fresh.compact_through
      return entry.active === active ? entry : { ...entry, active }
    })
    if (fresh.active_only) {
      entries = entries.filter((entry) => entry.seq > fresh.compact_through)
    }
    const oldestCompacted =
      fresh.active_only &&
      ((page.entries.length > 0 && page.entries[0]!.seq <= fresh.compact_through) ||
        (page.next_before !== null && page.next_before <= fresh.compact_through + 1))
    return { page, entries, oldestCompacted }
  })

  const updatedPages: SessionPage[] = []
  const updatedParams: (number | undefined)[] = []
  prepared.forEach(({ page, entries, oldestCompacted }, index) => {
    if (index === 0) {
      const retainedOld = entries.length > 0
      const mergedEntries = [...entries, ...updates.values()].sort((a, b) => a.seq - b.seq)
      const nextBefore = !retainedOld ? fresh.next_before : oldestCompacted ? null : page.next_before
      updatedPages.push({
        ...page,
        timezone: fresh.timezone,
        recap: fresh.recap,
        compact_through: fresh.compact_through,
        last_message_seq: fresh.last_message_seq,
        next_before: nextBefore,
        entries: mergedEntries,
      })
      updatedParams.push(data.pageParams[index])
    } else if (entries.length > 0) {
      updatedPages.push({
        ...page,
        next_before: oldestCompacted ? null : page.next_before,
        entries,
      })
      updatedParams.push(data.pageParams[index])
    }
  })

  return { pages: updatedPages, pageParams: updatedParams }
}

// A turn adds entries as it goes and may compact at the end; steps come in bursts.
let reading = false
let again = false
let timer: ReturnType<typeof setTimeout> | undefined
async function readNewest() {
  if (reading) {
    again = true
    return
  }
  reading = true
  try {
    do {
      again = false
      const key = queryKey.value
      const activeOnly = !everything.value
      if (!client.getQueryData<SessionData>(key)) return
      const fresh = await sessionApi.page(props.scene, { activeOnly })
      if (key !== queryKey.value) return
      client.setQueryData<SessionData>(key, (data) => (data ? mergeNewestSession(data, fresh) : data))
    } while (again)
  } catch {
    // Keep already-loaded pages intact; the next turn event or manual retry refreshes again.
  } finally {
    reading = false
  }
}

useHostEvent('*', (event) => {
  if (event.scene !== props.scene || !event.type.startsWith('turn.') || timer) return
  timer = setTimeout(() => {
    timer = undefined
    void readNewest()
  }, 1000)
})
onBeforeUnmount(() => clearTimeout(timer))

/** A long recap folds to ten lines; the toggle appears only when it is actually cut. */
const recapExpanded = ref(false)
const recapCut = ref(false)
const recapText = useTemplateRef<HTMLElement>('recapText')
useResizeObserver(recapText, () => {
  const element = recapText.value
  if (element && !recapExpanded.value) recapCut.value = element.scrollHeight > element.clientHeight + 1
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-8">
    <Skeleton v-if="query.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="query.isError.value && !newest"
      :title="t('groups.session.readFailed')"
      :error="query.error.value"
      :retry="query.refetch"
    />
    <template v-else-if="newest">
      <FormSection :title="t('groups.session.recap')" :columns="1">
        <template #actions>
          <Button size="sm" :icon="Sparkles" :loading="compacting" @click="compactRecap">
            {{ t('groups.session.compact') }}
          </Button>
        </template>
        <div
          v-if="newest.recap !== null"
          class="rounded-r-md border-l-2 border-line-strong bg-fill px-4 py-3"
        >
          <p
            ref="recapText"
            class="text-sm leading-6 break-words whitespace-pre-wrap text-ink"
            :class="!recapExpanded && 'line-clamp-10'"
          >
            {{ newest.recap }}
          </p>
          <button
            v-if="recapCut || recapExpanded"
            type="button"
            class="mt-2 inline-flex cursor-pointer items-center gap-1 rounded-sm text-xs font-medium text-muted hover:text-ink focus-visible:focus-ring"
            :aria-expanded="recapExpanded"
            @click="recapExpanded = !recapExpanded"
          >
            <ChevronDown
              :size="14"
              class="transition-transform duration-150"
              :class="recapExpanded && 'rotate-180'"
              aria-hidden="true"
            />
            {{ recapExpanded ? t('common.collapse') : t('common.expand') }}
          </button>
        </div>
        <p v-else class="text-sm text-muted">{{ t('groups.session.noRecap') }}</p>
      </FormSection>

      <FormSection :title="t('groups.session.entries')" :columns="1">
        <template #actions>
          <Button size="sm" :icon="RefreshCcw" :loading="starting" @click="startSession">
            {{ t('groups.newSession.action') }}
          </Button>
        </template>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <Switch v-model="everything" size="sm">{{ t('groups.session.everything') }}</Switch>
          <Button
            v-if="query.hasNextPage.value"
            size="sm"
            variant="ghost"
            :loading="query.isFetchingNextPage.value"
            @click="query.fetchNextPage()"
          >
            {{ t('groups.session.older') }}
          </Button>
        </div>
        <ErrorNote
          v-if="query.isError.value"
          :title="t('groups.session.readFailed')"
          :error="query.error.value"
          :retry="query.refetch"
        />
        <p v-if="!shown.length" class="text-sm text-muted">{{ t('groups.session.empty') }}</p>
        <Timeline v-else>
          <template v-for="(entry, index) in shown" :key="entry.seq">
            <li
              v-if="everything && index === firstActive && index > 0"
              class="mb-4 flex items-center gap-3 pt-1 text-xs font-medium text-muted"
            >
              <span class="h-px flex-1 bg-line" />
              {{ t('groups.session.current') }}
              <span class="h-px flex-1 bg-line" />
            </li>
            <EntryItem
              :entry="entry"
              :results="results"
              :time-zone="timeZone"
              :raw="developerDetails"
              :last="index === shown.length - 1"
            />
          </template>
        </Timeline>
      </FormSection>
    </template>
  </div>
</template>
