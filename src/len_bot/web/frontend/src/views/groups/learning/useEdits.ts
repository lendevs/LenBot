import { computed, reactive } from 'vue'

interface Entry<T, D> {
  item: T
  draft: D
}

/** Items being edited in place, by id; an item counts as changed when its draft differs from what was read. */
export function useEdits<T extends { id: number }, D>(fresh: (item: T) => D) {
  const drafts = reactive(new Map()) as Map<number, Entry<T, D>>
  const changed = (id: number) => {
    const entry = drafts.get(id)
    return Boolean(entry) && JSON.stringify(entry!.draft) !== JSON.stringify(fresh(entry!.item))
  }
  return {
    drafts,
    editing: (id: number) => drafts.has(id),
    draft: (id: number) => drafts.get(id)?.draft as D,
    start: (item: T) => void drafts.set(item.id, { item, draft: fresh(item) }),
    stop: (id: number) => void drafts.delete(id),
    clear: () => drafts.clear(),
    changed,
    dirty: computed(() => [...drafts.keys()].some(changed)),
  }
}
