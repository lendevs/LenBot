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
    eventLoop: () => ['host', 'event-loop'] as const,
    modelProtocols: () => ['host', 'model-protocols'] as const,
    usage: (period: string) => ['host', 'usage', period] as const,
    mcp: () => ['host', 'mcp'] as const,
    browser: () => ['host', 'browser'] as const,
  },
  /** Skill files do not change with host events; reading them walks directories. */
  skills: {
    all: () => ['skills'] as const,
    scene: (scene: string) => ['skills', scene] as const,
    files: (scene: string, source: string, name: string, taskId: number | null) =>
      ['skills', scene, source, name, taskId, 'files'] as const,
  },
  /** Under `host`, so the `host.changed` event that task progress raises refreshes them. */
  tasks: {
    all: () => ['host', 'tasks'] as const,
    state: () => ['host', 'tasks', 'state'] as const,
    list: (scene: string, filter: string) => ['host', 'tasks', scene, 'list', filter] as const,
    detail: (scene: string, id: number) => ['host', 'tasks', scene, id] as const,
    skills: (scene: string, id: number) => ['host', 'tasks', scene, id, 'skills'] as const,
    materials: (scene: string) => ['host', 'materials', scene] as const,
    scheduleState: () => ['host', 'schedules', 'state'] as const,
    schedules: (scene: string, filter: string) => ['host', 'schedules', scene, filter] as const,
    proactive: (scene: string) => ['host', 'proactive', scene] as const,
    /** Disk use and task files; reading them scans directories, so events do not refresh them. */
    space: () => ['task-space'] as const,
    pool: () => ['task-space', 'pool'] as const,
    usage: (scene: string, query: object) => ['task-space', scene, 'usage', query] as const,
    storage: (scene: string, id: number) => ['task-space', scene, 'task', id] as const,
    files: (scene: string, location: object) => ['task-space', scene, 'files', location] as const,
    /** Stored events and skill files do not change; kept outside `host` so events do not read them again. */
    event: (scene: string, id: number, event: number) => ['task-records', scene, id, 'event', event] as const,
    skillFiles: (scene: string, id: number, name: string) =>
      ['task-records', scene, id, 'skill', name] as const,
  },
  personas: {
    all: () => ['personas'] as const,
    /** One role's files; outside `personas`, so a library refresh does not read an open form again. */
    role: (key: string) => ['persona', key] as const,
    part: (key: string, part: 'profile' | 'knowledge' | 'stickers' | 'files' | 'abilities') =>
      ['persona', key, part] as const,
  },
  plugins: {
    all: () => ['plugins'] as const,
    health: () => ['plugins', 'health'] as const,
    catalog: () => ['plugin-catalog'] as const,
    market: (query: string, category: string | null) =>
      ['plugin-catalog', 'market', { query, category }] as const,
  },
  memory: {
    all: () => ['memory'] as const,
    state: () => ['memory', 'state'] as const,
    browse: (scene: string, scope: string, path: string) => ['memory', scene, scope, 'browse', path] as const,
    file: (scene: string, scope: string, path: string) => ['memory', scene, scope, 'file', path] as const,
    summary: (scene: string, scope: string, path: string) =>
      ['memory', scene, scope, 'summary', path] as const,
    history: (scene: string, path: string) => ['memory', scene, 'history', path] as const,
    ingest: () => ['memory', 'ingest'] as const,
    embeddingCalls: (scene: string, scope: string) => ['memory', scene, scope, 'embedding-calls'] as const,
  },
  scene: {
    all: (scene: string) => ['scene', scene] as const,
    timeline: (scene: string) => ['scene', scene, 'timeline'] as const,
    audio: (scene: string) => ['scene', scene, 'audio'] as const,
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
