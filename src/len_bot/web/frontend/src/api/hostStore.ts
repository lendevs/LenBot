import { reactive } from 'vue'
import { http } from './client'
import type { HostState, SceneTitles } from './host'
import type { Overview } from './overview'
import { sceneTitles } from './scenes'
import type { UpdateState } from './system'

export interface PendingRestartSummary {
  sections?: string[]
  scenes?: string[]
  plugins?: { name: string }[]
  personas?: { name: string }[]
  error?: unknown
  [field: string]: unknown
}

/**
 * Host-wide state shared by the shell and the pages: read on demand and after host events. Each read keeps
 * only its latest answer, and everything is dropped on logout.
 */
export interface HostStore {
  state: HostState | null
  stateError: unknown
  /** Pending restart summary from GET /api/host/pending-restart, or `{ error }` if reading failed. */
  restart: PendingRestartSummary | null
  titleErrors: Record<string, string>
  /** Today's overview snapshot from GET /api/host/overview. */
  overview: Overview | Record<string, unknown> | null
  overviewError: unknown
  members: Record<string, number>
  /** Version and update status from GET /api/host/updates. */
  updates: UpdateState | Record<string, unknown> | null
  /** Installed plugins with a newer catalog version. */
  pluginUpdates: number
}

export const host = reactive<HostStore>({
  state: null,
  stateError: null,
  restart: null,
  titleErrors: {},
  overview: null,
  overviewError: null,
  members: {},
  updates: null,
  pluginUpdates: 0,
})

export interface ReadOptions {
  /** Skip fetching when the last successful read is newer than `maxAge` milliseconds. */
  maxAge?: number
}

type ResourceKey = 'state' | 'titles' | 'overview' | 'restart' | 'updates' | 'pluginUpdates'

const reads: Record<ResourceKey, number> = {
  state: 0,
  titles: 0,
  overview: 0,
  restart: 0,
  updates: 0,
  pluginUpdates: 0,
}
const fetchedAt: Record<ResourceKey, number> = {
  state: 0,
  titles: 0,
  overview: 0,
  restart: 0,
  updates: 0,
  pluginUpdates: 0,
}
const inflight: Partial<Record<ResourceKey, Promise<void>>> = {}

function maxAgeOf(options?: ReadOptions): number {
  return options && typeof options === 'object' && typeof options.maxAge === 'number' ? options.maxAge : 0
}

function runRead(
  key: ResourceKey,
  options: ReadOptions | undefined,
  task: (own: number) => Promise<boolean>,
): Promise<void> {
  const maxAge = maxAgeOf(options)
  if (maxAge > 0) {
    if (inflight[key]) return inflight[key]!
    if (fetchedAt[key] > 0 && Date.now() - fetchedAt[key] < maxAge) return Promise.resolve()
  }
  const own = ++reads[key]
  const promise = task(own)
    .then((ok) => {
      if (ok && own === reads[key]) fetchedAt[key] = Date.now()
    })
    .finally(() => {
      if (inflight[key] === promise) delete inflight[key]
    })
  inflight[key] = promise
  return promise
}

export function readHostState(options?: ReadOptions): Promise<void> {
  return runRead('state', options, async (own) => {
    try {
      const value = await http.get<HostState>('/api/host/state')
      if (own !== reads.state) return false
      host.state = value
      host.stateError = null
      return true
    } catch (error) {
      if (own === reads.state) host.stateError = error
      return false
    }
  })
}

export function readSceneTitles(options?: ReadOptions): Promise<void> {
  return runRead('titles', options, async (own) => {
    try {
      const value = await http.get<SceneTitles>('/api/host/scene-titles')
      if (own !== reads.titles) return false
      Object.assign(sceneTitles, value.titles)
      host.members = value.members
      host.titleErrors = value.errors
      return true
    } catch (error) {
      if (own === reads.titles)
        host.titleErrors = { '': error instanceof Error ? error.message : String(error) }
      return false
    }
  })
}

export function readOverview(options?: ReadOptions): Promise<void> {
  return runRead('overview', options, async (own) => {
    try {
      const value = await http.get<Overview>('/api/host/overview')
      if (own !== reads.overview) return false
      host.overview = value
      host.overviewError = null
      return true
    } catch (error) {
      if (own === reads.overview) host.overviewError = error
      return false
    }
  })
}

export function readPendingRestart(options?: ReadOptions): Promise<void> {
  return runRead('restart', options, async (own) => {
    try {
      const value = await http.get<PendingRestartSummary>('/api/host/pending-restart')
      if (own !== reads.restart) return false
      host.restart = value
      return true
    } catch (error) {
      if (own === reads.restart) host.restart = { error }
      return false
    }
  })
}

export function readUpdates(options?: ReadOptions): Promise<void> {
  return runRead('updates', options, async (own) => {
    try {
      const value = await http.get<UpdateState>('/api/host/updates')
      if (own !== reads.updates) return false
      host.updates = value
      return true
    } catch {
      if (own === reads.updates) host.updates = null
      return false
    }
  })
}

export function readPluginUpdates(options?: ReadOptions): Promise<void> {
  return runRead('pluginUpdates', options, async (own) => {
    try {
      const value = await http.get<{ prepared: boolean }[]>('/api/host/plugin-updates')
      if (own !== reads.pluginUpdates) return false
      host.pluginUpdates = value.filter((item) => !item.prepared).length
      return true
    } catch {
      if (own === reads.pluginUpdates) host.pluginUpdates = 0
      return false
    }
  })
}

export function clearHost(): void {
  for (const key of Object.keys(reads) as ResourceKey[]) {
    reads[key] += 1
    fetchedAt[key] = 0
    delete inflight[key]
  }
  Object.assign(host, {
    state: null,
    stateError: null,
    restart: null,
    titleErrors: {},
    overview: null,
    overviewError: null,
    updates: null,
    pluginUpdates: 0,
    members: {},
  })
  for (const key of Object.keys(sceneTitles)) delete sceneTitles[key]
}
