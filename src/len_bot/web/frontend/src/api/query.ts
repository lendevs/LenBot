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
  },
  scene: {
    all: (scene: string) => ['scene', scene] as const,
    timeline: (scene: string) => ['scene', scene, 'timeline'] as const,
    turn: (scene: string, turnId: string) => ['scene', scene, 'turn', turnId] as const,
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
