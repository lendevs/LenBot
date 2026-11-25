import { computed, ref, watch, type Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import type { Page } from '../../../api/learning'

/** One page of a reviewed list; changing the filter goes back to the first page. */
export function usePagedList<T, F extends string>(
  key: (filter: F, offset: number) => readonly unknown[],
  read: (filter: F, offset: number, signal: AbortSignal) => Promise<Page<T>>,
  initial: F | Ref<F>,
) {
  const filter = (typeof initial === 'string' ? ref(initial) : initial) as Ref<F>
  const offset = ref(0)
  watch(filter, () => {
    offset.value = 0
  })
  const query = useQuery({
    queryKey: computed(() => key(filter.value, offset.value)),
    queryFn: ({ signal }) => read(filter.value, offset.value, signal),
    placeholderData: keepPreviousData,
  })
  const page = computed(() => query.data.value)
  // When the last item on the current page is reviewed away, fall back to the previous valid page.
  watch(
    () => [query.data.value, query.isPlaceholderData.value] as const,
    ([data, placeholder]) => {
      if (
        !data ||
        placeholder ||
        data.offset !== offset.value ||
        data.items.length > 0 ||
        data.total <= 0 ||
        offset.value <= 0
      )
        return
      const lastValid = Math.max(0, Math.floor((data.total - 1) / data.limit) * data.limit)
      offset.value = Math.min(lastValid, Math.max(0, offset.value - data.limit))
    },
  )
  function choose(value: F) {
    filter.value = value
    offset.value = 0
  }
  function move(step: -1 | 1) {
    const current = page.value
    if (current) offset.value = Math.max(0, current.offset + step * current.limit)
  }
  return { filter, offset, query, page, choose, move }
}
