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

/**
 * Merge a fresh newest page into the loaded pages. Items already loaded are replaced by their newer
 * version wherever they are; new items join the newest page. When more happened than one page holds,
 * the loaded history no longer joins up and only the fresh page is kept.
 */
export function mergeNewest(data: Data, fresh: TimelinePage): Data {
  const [first] = data.pages
  if (!first || !fresh.items.length) return data
  const newestLoaded = data.pages.flatMap((page) => page.items).sort(compareItems).at(-1)
  const oldestFresh = fresh.items[0]
  if (newestLoaded && fresh.next_before !== null && compareItems(oldestFresh, newestLoaded) > 0) {
    return { pages: [fresh], pageParams: [undefined] }
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
  pages[0] = { ...pages[0], items: [...pages[0].items, ...updates.values()].sort(compareItems) }
  return { ...data, pages }
}

/**
 * One group's timeline, newest page first. Messages and turn events of the group read the newest page
 * again (at most one request at a time) instead of every loaded page.
 */
export function useTimeline(scene: Ref<string>) {
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
        client.setQueryData<Data>(key, (data) => (data ? mergeNewest(data, fresh) : data))
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
