import { computed, inject, ref, type InjectionKey } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { pluginsApi, type Health, type PluginsSnapshot } from '../../api/plugins'
import { keys } from '../../api/query'
import { readPendingRestart } from '../../host/store.js'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

export function usePlugins() {
  const { t } = useI18n()
  const client = useQueryClient()
  const snapshot = useQuery({ queryKey: keys.plugins.all(), queryFn: ({ signal }) => pluginsApi.read(signal) })
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

  /** Which write is running: a plugin name, `install`, `paths` or `scene:<id>`. */
  const busy = ref<string | null>(null)
  /**
   * Runs one write and takes the snapshot it answers with. Errors go to a toast unless `quiet`, in which case
   * the caller shows them (a dialog keeps them next to its form).
   */
  async function run(
    part: string,
    action: () => Promise<PluginsSnapshot>,
    options: { success?: string; failure?: string; quiet?: boolean } = {},
  ): Promise<PluginsSnapshot | null> {
    busy.value = part
    try {
      const result = await action()
      client.setQueryData(keys.plugins.all(), result)
      void client.invalidateQueries({ queryKey: keys.plugins.health() })
      void readPendingRestart()
      if (options.success) toast.success(options.success)
      return result
    } catch (error) {
      if (options.quiet) throw error
      toast.error(options.failure ?? t('plugins.failed'), { detail: describeError(error, t('ui.error.network')).message })
      void snapshot.refetch()
      return null
    } finally {
      busy.value = null
    }
  }
  return { snapshot, healthOf, busy: computed(() => busy.value), run }
}

export type PluginsState = ReturnType<typeof usePlugins>
export const pluginsKey: InjectionKey<PluginsState> = Symbol('plugins')
export function usePluginsState(): PluginsState {
  const state = inject(pluginsKey)
  if (!state) throw new Error('usePluginsState() needs PluginsView')
  return state
}
