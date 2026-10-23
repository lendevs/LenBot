import { http, queryString, request, requestBlob, type Query } from './client'
import type { Task, TaskStatus } from './tasks'

/** Types of panel/routes/resources.py and task_storage.py. */

export type ResourceScope = 'workspace' | 'inputs' | 'deliveries' | 'runtime' | 'shared'

/** A place to list (`path` is a directory) or a file (`file_id` only for a registered delivery). */
export interface ResourceRef {
  scope: ResourceScope
  task_id: number | null
  path: string
  file_id?: number | null
}

export interface ResourceEntry {
  name: string
  kind: 'file' | 'directory' | 'symlink' | string
  size: number | null
  modified: number
  purpose: 'workspace' | 'output' | 'session' | 'inputs' | 'deliveries' | 'runtime' | 'shared' | string
  mime_type: string
  preview: 'text' | 'image' | 'pdf' | 'download'
  exists: boolean
  reference: ResourceRef
  note: string | null
  upload: { status: string; error?: string | null; [field: string]: unknown } | null
  /** Where an input or delivery was copied from: a reference, or `source_path` for an old input. */
  source: (Partial<ResourceRef> & { reference?: ResourceRef | null; source_path?: string }) | null
  browser_source: {
    created: number
    kind: 'download' | 'screenshot' | 'pdf' | string
    page_url: string | null
    page_title: string | null
    download_url: string | null
  } | null
  registrations: number[]
  deletion: { created: number; requester: string } | null
  deletable: boolean
}

export interface ResourceListing {
  scene: string
  scope: ResourceScope
  task_id: number | null
  path: string
  exists: boolean
  entries: ResourceEntry[]
  next_offset: number | null
}

export interface ResourceText {
  text: string
  offset: number
  size: number
  next_offset: number | null
  encoding: string
}

/** A file picked for the next task, with the name it gets in the task's inputs. */
export interface ResourceInput {
  reference: ResourceRef
  name: string
}

export interface PoolUsage {
  kind: 'apfs' | 'ext4' | string
  mount: string
  source: string
  limit_bytes: number
  used_bytes: number
  available_bytes: number
}

export type Continuation = 'active' | 'retained' | 'discarded'
export type StorageFilter = 'all' | 'active' | 'done' | 'failed' | 'cancelled'
export type EnvironmentFilter = 'all' | 'retained' | 'discarded'
export type CleanupOperation = 'temporary' | 'environment'

/** `work/storage.py` TreeUsage. */
export interface TreeUsage {
  file_bytes: number
  allocated_bytes: number
  files: number
  directories: number
}

export interface StorageRoot {
  kind: 'workspace' | 'runtime' | 'deliveries'
  path: string
  exists: boolean
  usage: TreeUsage | null
}

export interface StorageRow {
  id: number
  goal: string
  requester: string
  status: TaskStatus
  created: number
  ended: number | null
  continuation: Continuation
  cleanable: boolean
  /** Only when the list was read with `measure`. */
  roots: StorageRoot[] | null
  usage_error: string | null
}

export interface StorageQuery {
  status: StorageFilter
  environment: EnvironmentFilter
  since: number | null
  before: number | null
  measure: boolean
}

/** GET /api/host/tasks/{id}/storage */
export interface TaskStorage {
  task_id: number
  task: Task
  continuation: Continuation
  cleanable: boolean
  roots: StorageRoot[]
  temporary: { path: string; kind: 'file' | 'directory'; exists: boolean; file_bytes: number }[]
  last_cleanup: {
    kind: string
    created: number
    complete?: boolean
    error?: string | null
    [field: string]: unknown
  } | null
  hard_disk_quota: PoolUsage | null
}

export interface CleanupResult {
  task_id: number
  status: 'complete' | 'error'
  error: string | null
  removal: { removed: string[]; absent: string[]; [field: string]: unknown } | null
}

const place = (reference: ResourceRef): Query => ({
  scope: reference.scope,
  task_id: reference.task_id,
  path: reference.path,
  file_id: reference.file_id,
})

export const resourcesApi = {
  list: (scene: string, location: ResourceRef, offset: number, signal?: AbortSignal) =>
    http.get<ResourceListing>(
      '/api/host/resources',
      { scene, ...place(location), offset, limit: 100 },
      signal,
    ),
  text: (scene: string, reference: ResourceRef, offset: number) =>
    http.get<ResourceText>('/api/host/resources/text', { scene, ...place(reference), offset }),
  preview: (scene: string, reference: ResourceRef) =>
    requestBlob('/api/host/resources/content', { query: { scene, ...place(reference), preview: true } }),
  downloadUrl: (scene: string, reference: ResourceRef) =>
    `/api/host/resources/content${queryString({ scene, ...place(reference) })}`,
  register: (scene: string, body: { reference: ResourceRef; name: string; note: string }) =>
    request<{ id: number; name: string }>('/api/host/resources/register', {
      method: 'POST',
      query: { scene },
      body,
    }),
  adopt: (scene: string, body: { reference: ResourceRef; name: string }) =>
    request<{ name: string }>('/api/host/resources/adopt', { method: 'POST', query: { scene }, body }),
  remove: (scene: string, reference: ResourceRef) =>
    request<{ name: string }>('/api/host/resources', {
      method: 'DELETE',
      query: { scene },
      body: { reference },
    }),
  upload: (scene: string, file: File, name: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('name', name)
    return request<{ name: string }>('/api/host/resources/upload', { method: 'POST', query: { scene }, body })
  },
}

export const storageApi = {
  pool: (signal?: AbortSignal) =>
    http.get<{ configured: boolean; usage: PoolUsage | null }>(
      '/api/host/task-storage/pool',
      undefined,
      signal,
    ),
  list: (scene: string, query: StorageQuery, offset: number, signal?: AbortSignal) =>
    http.get<{ items: StorageRow[]; measured: boolean; next_offset: number | null }>(
      '/api/host/task-storage',
      { scene, ...query, offset, limit: 20 },
      signal,
    ),
  task: (scene: string, id: number, signal?: AbortSignal) =>
    http.get<TaskStorage>(`/api/host/tasks/${id}/storage`, { scene }, signal),
  cleanup: (scene: string, ids: number[], operation: CleanupOperation) =>
    request<{ items: CleanupResult[] }>('/api/host/task-storage/cleanup', {
      method: 'POST',
      query: { scene },
      body: { task_ids: ids, operation },
    }),
}
