import { computed, onScopeDispose, type Ref } from 'vue'
import { useInfiniteQuery, useQueryClient, type InfiniteData } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import {
  compareItems,
  itemKey,
  timelineApi,
  type TimelineItem,
  type TimelinePage,
} from '../../../api/timeline'
import { useHostEvent } from '../../../realtime/stream'

type Data = InfiniteData<TimelinePage, string | undefined>

const DEFAULT_MAX_PINNED_ITEMS = 400

export interface MergeNewestOptions {
  /** True when the viewport is pinned to the newest end and old head pages can be trimmed. */
  pinnedToEnd?: boolean
  /** Maximum items retained in memory while pinned to the end. */
  maxItems?: number
}

function trimOldestPages(data: Data, fresh: TimelinePage, maxItems: number): Data {
  const total = data.pages.reduce((sum, page) => sum + page.items.length, 0)
  if (total <= maxItems) return data
  const keptPages: TimelinePage[] = []
  let keptCount = 0
  for (const page of data.pages) {
    if (keptPages.length > 0 && keptCount + page.items.length > maxItems) break
    keptPages.push(page)
    keptCount += page.items.length
  }
  if (keptPages.length === 1 && keptPages[0]!.items.length > maxItems) {
    return { pages: [fresh], pageParams: [undefined] }
  }
  return {
    pages: keptPages,
    pageParams: data.pageParams.slice(0, keptPages.length),
  }
}

/**
 * Merge a fresh newest page into the loaded pages. Items already loaded are replaced by their newer
 * version wherever they are; new items join the newest page. When pinned to the bottom, ancient head pages
 * past `maxItems` are trimmed while preserving a valid `next_before` cursor; when scrolled up reading
 * history, the loaded viewport is preserved untouched.
 */
export function mergeNewest(data: Data, fresh: TimelinePage, options: MergeNewestOptions = {}): Data {
  const pinnedToEnd = options.pinnedToEnd ?? true
  const maxItems = options.maxItems ?? DEFAULT_MAX_PINNED_ITEMS
  const [first] = data.pages
  if (!first || !fresh.items.length) return data
  const newestLoaded = data.pages
    .flatMap((page) => page.items)
    .sort(compareItems)
    .at(-1)
  const oldestFresh = fresh.items[0]
  if (newestLoaded && fresh.next_before !== null && compareItems(oldestFresh, newestLoaded) > 0) {
    return pinnedToEnd ? { pages: [fresh], pageParams: [undefined] } : data
  }
  const updates = new Map(fresh.items.map((item) => [itemKey(item), item]))
  const pages = data.pages.map((page) => ({
    ...page,
    items: page.items.map((item) => {
      const key = itemKey(item)
      const next = updates.get(key)
      if (next) updates.delete(key)
      return next ?? item
    }),
  }))
  pages[0] = { ...pages[0]!, items: [...pages[0]!.items, ...updates.values()].sort(compareItems) }
  const merged: Data = { ...data, pages }
  return pinnedToEnd ? trimOldestPages(merged, fresh, maxItems) : merged
}

/**
 * One group's timeline, newest page first. Messages and turn events of the group read the newest page
 * again (at most one request at a time) instead of every loaded page.
 */
export function useTimeline(
  scene: Ref<string>,
  options: { pinnedToEnd?: Ref<boolean>; maxItems?: number } = {},
) {
  const client = useQueryClient()
  const queryKey = computed(() => keys.scene.timeline(scene.value))
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => timelineApi.page(scene.value, pageParam, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_before ?? undefined,
    // Kept current by events while open; reopening starts again at the newest page.
    staleTime: Infinity,
    gcTime: 0,
  })

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
        if (!client.getQueryData<Data>(key)) return
        const fresh = await timelineApi.page(scene.value)
        if (key !== queryKey.value) return
        const mergeOpts: MergeNewestOptions = {
          pinnedToEnd: options.pinnedToEnd?.value ?? true,
          maxItems: options.maxItems,
        }
        client.setQueryData<Data>(key, (data) => (data ? mergeNewest(data, fresh, mergeOpts) : data))
      } while (again)
    } catch {
      // The next event or a reconnect reads again; the loaded items stay as they are.
    } finally {
      reading = false
    }
  }
  /** Turn steps arrive in bursts; the turn summaries need not follow every one. */
  function soon(delay: number) {
    if (timer) return
    timer = setTimeout(() => {
      timer = undefined
      void readNewest()
    }, delay)
  }
  useHostEvent('*', (event) => {
    if (event.scene !== scene.value) return
    if (/^(message\.(received|sent)|notice\.received|turn\.(started|ended))$/.test(event.type)) soon(150)
    else if (event.type === 'turn.step') soon(1000)
  })
  onScopeDispose(() => clearTimeout(timer))

  const items = computed<TimelineItem[]>(() =>
    [...(query.data.value?.pages ?? [])].reverse().flatMap((page) => page.items),
  )
  return { query, items }
}
