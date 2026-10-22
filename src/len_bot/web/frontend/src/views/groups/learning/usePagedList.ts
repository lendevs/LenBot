import { computed, ref, type Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import type { Page } from '../../../api/learning'

/** One page of a reviewed list; changing the filter goes back to the first page. */
export function usePagedList<T, F extends string>(
  key: (filter: F, offset: number) => readonly unknown[],
  read: (filter: F, offset: number, signal: AbortSignal) => Promise<Page<T>>,
  initial: F,
) {
  const filter = ref(initial) as Ref<F>
  const offset = ref(0)
  const query = useQuery({
    queryKey: computed(() => key(filter.value, offset.value)),
    queryFn: ({ signal }) => read(filter.value, offset.value, signal),
    placeholderData: keepPreviousData,
  })
  const page = computed(() => query.data.value)
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
