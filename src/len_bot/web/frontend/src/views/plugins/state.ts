import { computed, inject, ref, type InjectionKey } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { pluginsApi, type Health, type PluginsSnapshot } from '../../api/plugins'
import { keys } from '../../api/query'
import { readHostState, readPendingRestart, readPluginUpdates } from '../../api/hostStore'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

export function usePlugins() {
  const { t } = useI18n()
  const client = useQueryClient()
  const snapshot = useQuery({
    queryKey: keys.plugins.all(),
    queryFn: ({ signal }) => pluginsApi.read(signal),
  })
  // Health is cheap to read (no disk access); poll it while the page is open and lay it over the snapshot.
  const health = useQuery({
    queryKey: keys.plugins.health(),
    queryFn: ({ signal }) => pluginsApi.health(signal),
    refetchInterval: () => (document.visibilityState === 'visible' ? 10_000 : false),
  })
  const healthOf = (name: string): Health | null =>
    health.data.value?.plugins.find((item) => item.name === name)?.health ??
    snapshot.data.value?.running.plugins.find((item) => item.name === name)?.health ??
    null

  /**
   * Running write keys: fine-grained keys such as `install:<name>`, `toggle:<name>`, `reload:<name>`,
   * `update:<name>`, `scene:<id>`, `paths`, or `<name>` so single-card writes do not lock other cards.
   */
  const active = ref<string[]>([])
  const busy = computed<string | null>(() => active.value[active.value.length - 1] ?? null)
  const isBusy = (part?: string): boolean =>
    part === undefined ? active.value.length > 0 : active.value.includes(part)
  const pluginBusy = (name: string): boolean =>
    active.value.some((part) => part === name || part.endsWith(`:${name}`))

  /**
   * Runs one write and takes the snapshot it answers with. Errors go to a toast unless `quiet`, in which case
   * the caller shows them (a dialog keeps them next to its form).
   */
  async function run(
    part: string,
    action: () => Promise<PluginsSnapshot>,
    options: { success?: string; failure?: string; quiet?: boolean } = {},
  ): Promise<PluginsSnapshot | null> {
    active.value = [...active.value, part]
    try {
      const result = await action()
      client.setQueryData(keys.plugins.all(), result)
      client.setQueryData(keys.plugins.updates(), result.updates)
      void client.invalidateQueries({ queryKey: keys.plugins.health() })
      void readPendingRestart()
      void readHostState()
      void readPluginUpdates()
      if (options.success) toast.success(options.success)
      return result
    } catch (error) {
      if (options.quiet) throw error
      toast.error(options.failure ?? t('plugins.failed'), {
        detail: describeError(error, t('ui.error.network')).message,
      })
      void snapshot.refetch()
      return null
    } finally {
      const index = active.value.indexOf(part)
      if (index !== -1) active.value = [...active.value.slice(0, index), ...active.value.slice(index + 1)]
    }
  }
  return { snapshot, healthOf, busy, isBusy, pluginBusy, run }
}

export type PluginsState = ReturnType<typeof usePlugins>
export const pluginsKey: InjectionKey<PluginsState> = Symbol('plugins')
export function usePluginsState(): PluginsState {
  const state = inject(pluginsKey)
  if (!state) throw new Error('usePluginsState() needs PluginsView')
  return state
}
