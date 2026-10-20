import { QueryClient } from '@tanstack/vue-query'
import { ApiError, SessionChangedError } from './client'

/**
 * Query keys: the first element is the area, then ids from general to specific, so invalidating a prefix
 * refreshes everything below it (`['scene', id]` covers that group's timeline, settings and memory).
 */
export const keys = {
  auth: {
    context: () => ['auth', 'context'] as const,
    me: () => ['auth', 'me'] as const,
  },
  host: {
    all: () => ['host'] as const,
    state: () => ['host', 'state'] as const,
    overview: () => ['host', 'overview'] as const,
    sceneTitles: () => ['host', 'scene-titles'] as const,
    pendingRestart: () => ['host', 'pending-restart'] as const,
    availableScenes: () => ['host', 'available-scenes'] as const,
    settings: () => ['host', 'settings'] as const,
    limits: () => ['host', 'limits'] as const,
  },
  personas: {
    all: () => ['personas'] as const,
  },
  plugins: {
    all: () => ['plugins'] as const,
  },
  memory: {
    all: () => ['memory'] as const,
    state: () => ['memory', 'state'] as const,
    browse: (scene: string, scope: string, path: string) => ['memory', scene, scope, 'browse', path] as const,
    file: (scene: string, scope: string, path: string) => ['memory', scene, scope, 'file', path] as const,
    summary: (scene: string, scope: string, path: string) =>
      ['memory', scene, scope, 'summary', path] as const,
    history: (scene: string, path: string) => ['memory', scene, 'history', path] as const,
  },
  scene: {
    all: (scene: string) => ['scene', scene] as const,
    timeline: (scene: string) => ['scene', scene, 'timeline'] as const,
    control: (scene: string) => ['scene', scene, 'control'] as const,
    turn: (scene: string, turnId: string) => ['scene', scene, 'turn', turnId] as const,
    permissions: (scene: string) => ['scene', scene, 'permissions'] as const,
    learningAll: (scene: string) => ['scene', scene, 'learning'] as const,
    learning: (scene: string, ...parts: unknown[]) => ['scene', scene, 'learning', ...parts] as const,
    sessionAll: (scene: string) => ['scene', scene, 'session'] as const,
    session: (scene: string, activeOnly: boolean) => ['scene', scene, 'session', { activeOnly }] as const,
  },
}

function retry(failures: number, error: unknown): boolean {
  if (error instanceof SessionChangedError) return false
  // Only a request that never got an answer is retried, once; an HTTP error is shown as it is.
  return error instanceof ApiError && error.status === 0 && failures < 1
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Live data is refreshed by events from /api/host/stream, not by polling.
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry,
      refetchOnWindowFocus: true,
    },
    mutations: { retry: false },
  },
})
