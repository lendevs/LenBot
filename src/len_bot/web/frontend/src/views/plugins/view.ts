import type { AvailableEntry, Health, Permission, PluginsSnapshot, RunningPlugin } from '../../api/plugins'
import type { Tone } from '../../ui/Badge.vue'

/** Read-only views over the plugins snapshot, shared by the list and the detail page. */

export const pluginNames = (snapshot: PluginsSnapshot) =>
  [
    ...new Set([
      ...Object.keys(snapshot.available),
      ...Object.keys(snapshot.saved.plugins),
      ...snapshot.running.plugins.map((item) => item.name),
    ]),
  ].sort()

/** The plugin's one readable directory; null when it is missing, unreadable or provided twice. */
export function manifestOf(snapshot: PluginsSnapshot, name: string): AvailableEntry | null {
  const entries = snapshot.available[name] ?? []
  return entries.length === 1 && !entries[0].error ? entries[0] : null
}
export const runningOf = (snapshot: PluginsSnapshot, name: string): RunningPlugin | null =>
  snapshot.running.plugins.find((item) => item.name === name) ?? null
/** Saved and not turned off; the host only keeps parameters of plugins it loads. */
export const configuredIn = (snapshot: PluginsSnapshot, name: string) => name in snapshot.saved.plugins
export const disabledIn = (snapshot: PluginsSnapshot, name: string) => snapshot.saved.disabled.includes(name)
export const enabledIn = (snapshot: PluginsSnapshot, name: string) =>
  configuredIn(snapshot, name) && !disabledIn(snapshot, name)
export const scenesUsing = (snapshot: PluginsSnapshot, name: string) =>
  Object.keys(snapshot.scenes).filter((scene) => (snapshot.scenes[scene].saved ?? []).includes(name))
export const versionOf = (snapshot: PluginsSnapshot, name: string) =>
  runningOf(snapshot, name)?.version ||
  manifestOf(snapshot, name)?.source?.installed?.version ||
  manifestOf(snapshot, name)?.version ||
  ''
export const descriptionOf = (snapshot: PluginsSnapshot, name: string) =>
  runningOf(snapshot, name)?.description || manifestOf(snapshot, name)?.description || ''
export const permissionsOf = (snapshot: PluginsSnapshot, name: string): Permission[] | null =>
  runningOf(snapshot, name)?.permissions ?? manifestOf(snapshot, name)?.permissions ?? null
export const isolationOf = (snapshot: PluginsSnapshot, name: string) =>
  runningOf(snapshot, name)?.isolation || manifestOf(snapshot, name)?.isolation || 'inline'
export const featureCount = (running: RunningPlugin | null) =>
  running ? running.commands.length + running.rules.length + running.tools.length : 0

export type PluginStatus = 'disabled' | 'running' | 'degraded' | 'failed' | 'starting' | 'stopped' | 'pending' | 'idle'
const tones: Record<PluginStatus, Tone> = {
  disabled: 'neutral',
  running: 'success',
  degraded: 'warning',
  failed: 'error',
  starting: 'info',
  stopped: 'neutral',
  pending: 'info',
  idle: 'neutral',
}
export const statusTone = (status: PluginStatus) => tones[status]

/** `pending`: saved but not loaded yet (a restart or apply away); `idle`: installed, never turned on. */
export function statusOf(snapshot: PluginsSnapshot, name: string, health: Health | null): PluginStatus {
  if (disabledIn(snapshot, name)) return 'disabled'
  const running = runningOf(snapshot, name)
  if (!running) return configuredIn(snapshot, name) ? 'pending' : 'idle'
  if (running.status === 'failed' || health?.level === 'failed') return 'failed'
  if (health?.level === 'degraded') return 'degraded'
  if (health?.level === 'starting') return 'starting'
  if (running.status === 'running') return 'running'
  return 'stopped'
}

/** Filter buckets of the installed list. */
export type Bucket = 'on' | 'attention' | 'disabled' | 'idle'
export function bucketOf(status: PluginStatus): Bucket {
  if (status === 'disabled') return 'disabled'
  if (status === 'idle') return 'idle'
  return status === 'failed' || status === 'degraded' ? 'attention' : 'on'
}

const permissionKey = (list: Permission[] | null | undefined) =>
  list == null ? null : list.map((item) => item.name).sort().join(',')

/** How a staged candidate differs from the running version in what it may do. */
export function candidateChange(snapshot: PluginsSnapshot, name: string) {
  const now = runningOf(snapshot, name)
  const next = manifestOf(snapshot, name)
  if (!now || !next || !('permissions' in next)) return { permissions: undefined, isolation: undefined }
  return {
    permissions: permissionKey(now.permissions) !== permissionKey(next.permissions) ? (next.permissions ?? null) : undefined,
    isolation: (now.isolation || 'inline') !== (next.isolation || 'inline') ? next.isolation : undefined,
  }
}
