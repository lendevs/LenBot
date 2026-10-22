import { reactive } from 'vue'
import { http } from './client'
import type { HostState, SceneTitles } from './host'
import { sceneTitles } from './scenes'

/**
 * Host-wide state shared by the shell and the pages: read on demand and after host events. Each read keeps
 * only its latest answer, and everything is dropped on logout.
 */
export interface HostStore {
  state: HostState | null
  stateError: unknown
  restart: Record<string, unknown> | null
  titleErrors: Record<string, string>
  overview: Record<string, unknown> | null
  overviewError: unknown
  members: Record<string, number>
  updates: Record<string, unknown> | null
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
})

const reads = { state: 0, titles: 0, overview: 0, restart: 0, updates: 0 }

export async function readHostState(): Promise<void> {
  const own = ++reads.state
  try {
    const value = await http.get<HostState>('/api/host/state')
    if (own !== reads.state) return
    host.state = value
    host.stateError = null
  } catch (error) {
    if (own === reads.state) host.stateError = error
  }
}

export async function readSceneTitles(): Promise<void> {
  const own = ++reads.titles
  try {
    const value = await http.get<SceneTitles>('/api/host/scene-titles')
    if (own !== reads.titles) return
    Object.assign(sceneTitles, value.titles)
    host.members = value.members
    host.titleErrors = value.errors
  } catch (error) {
    if (own === reads.titles)
      host.titleErrors = { '': error instanceof Error ? error.message : String(error) }
  }
}

export async function readOverview(): Promise<void> {
  const own = ++reads.overview
  try {
    const value = await http.get<Record<string, unknown>>('/api/host/overview')
    if (own !== reads.overview) return
    host.overview = value
    host.overviewError = null
  } catch (error) {
    if (own === reads.overview) host.overviewError = error
  }
}

export async function readPendingRestart(): Promise<void> {
  const own = ++reads.restart
  try {
    const value = await http.get<Record<string, unknown>>('/api/host/pending-restart')
    if (own === reads.restart) host.restart = value
  } catch (error) {
    if (own === reads.restart) host.restart = { error }
  }
}

export async function readUpdates(): Promise<void> {
  const own = ++reads.updates
  try {
    const value = await http.get<Record<string, unknown>>('/api/host/updates')
    if (own === reads.updates) host.updates = value
  } catch {
    if (own === reads.updates) host.updates = null
  }
}

export function clearHost(): void {
  for (const key of Object.keys(reads) as (keyof typeof reads)[]) reads[key] += 1
  Object.assign(host, {
    state: null,
    stateError: null,
    restart: null,
    titleErrors: {},
    overview: null,
    overviewError: null,
    members: {},
  })
  for (const key of Object.keys(sceneTitles)) delete sceneTitles[key]
}
