import { http, request } from './client'

/** Types of panel/routes/memory.py; dataclass fields come through `asdict`. */

export type MemoryScope = 'scene' | 'public'

export interface IndexBinding {
  base_url: string | null
  model: string | null
  dimensions: number | null
}

export interface MemoryIndex {
  retrieval: 'hybrid' | 'fulltext' | string
  needs_rebuild: boolean
  stored: IndexBinding | null
  configured: IndexBinding | null
  [field: string]: unknown
}

/** GET /api/host/memory/state */
export interface MemoryState {
  enabled: boolean
  backend: string | null
  /** What the backend supports: browse, read, write, delete, forget, history, search. */
  actions: string[]
  public_writable: boolean
  public_readable: boolean
  auto_recall: boolean
  summaries: boolean
  reindexing: boolean
  index: MemoryIndex | null
  scenes: { scene: string; persona: { id: string; name: string } }[]
  persona_ids: Record<string, string[]>
}

export interface MemoryNode {
  path: string
  name: string
  is_dir: boolean
  access: string | null
}

export interface MemoryChange {
  action: 'write' | 'delete' | 'forget' | string
  changed_at: number
  reason: string
  before: string | null
  after: string | null
}

export interface DirectorySummary {
  enabled: boolean
  summary: {
    abstract: string | null
    overview: string | null
    generated_at: number | null
    changed_after: number | null
  }
  runs: { id: number; status: string; started: number; ended: number | null; error: string | null }[]
}

export interface SearchHit {
  scope: MemoryScope
  path: string
  preview: string
  score: number | null
  total_chars: number | null
}

export interface SourcePreview {
  record: number
  text: string
  excluded: boolean
}

export interface SourcePage {
  snapshot: number
  offset: number
  next_offset: number | null
  previews: SourcePreview[]
}

export interface IngestJob {
  status: 'running' | 'complete' | 'failed' | 'interrupted' | string
  backend: string
  started: number
  ended: number | null
  error: string | null
}

export interface IngestScene {
  scene: string
  latest: IngestJob | null
  worker_error: string | null
  [field: string]: unknown
}

export interface EmbeddingCall {
  id: number
  purpose: 'index' | 'query' | 'reindex' | string
  started: number
  tokens: { input: number } | null
  usage: unknown
  response: unknown
  error: string | null
}

export const memoryApi = {
  state: (signal?: AbortSignal) => http.get<MemoryState>('/api/host/memory/state', undefined, signal),
  browse: (scene: string, scope: MemoryScope, path: string, offset: number, signal?: AbortSignal) =>
    http.get<{ nodes: MemoryNode[]; has_more: boolean }>(
      '/api/host/memory/browse',
      { scene, scope, path, offset, limit: 50 },
      signal,
    ),
  read: (scene: string, scope: MemoryScope, path: string, signal?: AbortSignal) =>
    http.get<{ path: string; content: string }>('/api/host/memory/read', { scene, scope, path }, signal),
  write: (body: { scene: string; scope: MemoryScope; path: string; content: string; reason: string }) =>
    http.put<{ after: string; [field: string]: unknown }>('/api/host/memory/file', body),
  history: (scene: string, path: string, signal?: AbortSignal) =>
    http.get<{ changes: MemoryChange[] }>('/api/host/memory/history', { scene, path }, signal),
  remove: (body: {
    scene: string
    path: string
    reason: string
    forget: boolean
    exclude_records: number[] | null
  }) => http.post<unknown>('/api/host/memory/delete', body),
  sources: (
    scene: string,
    query: { query?: string; who?: string; offset?: number; snapshot?: number },
    signal?: AbortSignal,
  ) => http.get<SourcePage>('/api/host/memory/sources', { scene, ...query }, signal),
  summary: (scene: string, scope: MemoryScope, path: string, signal?: AbortSignal) =>
    http.get<DirectorySummary>('/api/host/memory/summary', { scene, scope, path }, signal),
  summarize: (scene: string, scope: MemoryScope, path: string) =>
    http.post<{ skipped?: string; complete?: boolean }>('/api/host/memory/summary', { scene, scope, path }),
  search: (scene: string, query: string) =>
    http.post<{ hits: SearchHit[] }>('/api/host/memory/search', { scene, query, limit: 10 }),
  ingest: (signal?: AbortSignal) =>
    http.get<{ enabled: boolean; scenes: IngestScene[] }>('/api/host/memory/ingest', undefined, signal),
  ingestAction: (scene: string, action: 'run' | 'retry') =>
    request<unknown>(`/api/host/memory/ingest/${encodeURIComponent(scene)}/${action}`, { method: 'POST' }),
  reindex: () => http.post<{ files: number }>('/api/host/memory/reindex'),
  embeddingCalls: (
    scene: string,
    scope: MemoryScope,
    page: { offset?: number; snapshot?: number },
    signal?: AbortSignal,
  ) =>
    http.get<{ calls: EmbeddingCall[]; next_offset: number | null; snapshot: number }>(
      '/api/host/memory/embedding-calls',
      { scene, scope, limit: 20, ...page },
      signal,
    ),
  embeddingCall: (scene: string, scope: MemoryScope, id: number) =>
    http.get<{ call: unknown }>(`/api/host/memory/embedding-calls/${id}`, { scene, scope }),
}
