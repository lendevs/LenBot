import { onBeforeUnmount, onMounted, unref, type Ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, type LocationQuery } from 'vue-router'
import { i18n } from '../i18n'
import { confirm } from '../ui/confirm'

/**
 * Ask before leaving a page with unsaved edits: on navigation away, on a change of query parameters other
 * than `keep`, and (through the browser's own prompt) on closing or reloading the tab.
 */
export function useUnsavedChanges(
  dirty: Ref<boolean> | boolean,
  { onDiscard, keep = [] }: { onDiscard?: () => void; keep?: string[] } = {},
) {
  const others = (query: LocationQuery) =>
    JSON.stringify(
      Object.entries(query)
        .filter(([key]) => !keep.includes(key))
        .sort(),
    )

  async function confirmLeave(): Promise<boolean> {
    if (!unref(dirty)) return true
    const { t } = i18n.global
    const leave = await confirm({
      title: t('ui.unsaved.title'),
      message: t('ui.unsaved.message'),
      confirmLabel: t('common.discard'),
      tone: 'danger',
    })
    if (leave) onDiscard?.()
    return leave
  }

  function beforeUnload(event: BeforeUnloadEvent) {
    if (!unref(dirty)) return
    event.preventDefault()
    event.returnValue = ''
  }

  onBeforeRouteLeave(confirmLeave)
  onBeforeRouteUpdate((to, from) =>
    to.path === from.path && others(to.query) === others(from.query) ? true : confirmLeave(),
  )
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
  return { confirmLeave }
}
