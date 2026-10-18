// Types of the old reactive host store (store.js) for the TypeScript shell; removed with the store (work.md M4).
import type { HostState } from '../api/host'

export interface HostStore {
  state: HostState | null
  stateError: unknown
  restart: Record<string, unknown> | null
  toast: string
  titleErrors: Record<string, string>
  overview: Record<string, unknown> | null
  overviewError: unknown
  members: Record<string, number>
  updates: Record<string, unknown> | null
}

export const host: HostStore
export function readHostState(): Promise<void>
export function readSceneTitles(): Promise<void>
export function readOverview(): Promise<void>
export function readPendingRestart(): Promise<void>
export function readUpdates(): Promise<void>
export function notify(text: string): void
export function clearHost(): void
