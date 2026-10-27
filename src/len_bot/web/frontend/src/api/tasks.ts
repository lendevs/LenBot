import { http, queryString, request, requestBlob, socketUrl } from './client'

/** Types of panel/routes/tasks.py, materials.py, skills.py and task_storage.py as one task uses them. */

export type TaskStatus = 'queued' | 'running' | 'waiting_input' | 'done' | 'failed' | 'cancelled'
export type TaskFilter = 'active' | 'all' | 'done' | 'failed' | 'cancelled'

/** A question from the task (`extension_ui_request`). */
export interface TaskQuestion {
  id: string
  method: 'input' | 'editor' | 'confirm' | 'select' | string
  title: string
  message?: string
  options?: string[]
  [field: string]: unknown
}

/** `work/store.py` Task. */
export interface Task {
  id: number
  scene: string
  requester: string
  goal: string
  deliverable: string
  context: string
  input: string
  materials: string[]
  status: TaskStatus
  created: number
  started: number | null
  ended: number | null
  container: string | null
  question: TaskQuestion | null
  summary: string | null
  error: string | null
}

export interface RegisteredFile {
  id: number
  task_id: number
  name: string
  size: number
  note: string | null
  status: 'registered'
  exists: boolean
  upload: {
    status: 'uploaded' | 'failed' | 'unconfirmed' | 'simulated' | string
    error?: string | null
    [field: string]: unknown
  } | null
}

export interface TaskEventPreview {
  id: number
  kind: string
  created: number
  delivered_at: number | null
  event_type: string | null
  tool_name: string | null
  preview: string
  truncated: boolean
}

/** One stored event in full; `body` is the event as the task runner recorded it. */
export interface TaskEvent {
  id: number
  body: Record<string, unknown>
  [field: string]: unknown
}

export interface TaskDetail {
  task: Task & { workspace_discard_requested: boolean; active_timeout_seconds: number | null }
  events: TaskEventPreview[]
  network: Record<string, unknown> | null
  browser: { public_enabled: boolean; output_count: number }
  next_after: number
  files: RegisteredFile[]
}

/** GET /api/host/tasks/state */
export interface TaskService {
  configured: boolean
  timezone: string
  accepting: boolean
  error: string | null
  scenes: { scene: string; timezone: string | null; enabled: boolean; [field: string]: unknown }[]
  public_network: boolean
  file_upload: boolean
}

/** What the live socket sends; `preview` is the text the task is writing now. */
export interface LiveSnapshot {
  task_id: number
  status: TaskStatus
  preview: { text: string; truncated: boolean; complete: boolean } | null
}

export interface DelegateInput {
  goal: string
  deliverable: string
  context: string
  materials: string[]
  resources?: { reference: Record<string, unknown>; name: string }[]
}

export type TaskAction =
  | { action: 'append' | 'continue'; text: string }
  | { action: 'answer'; question_id: string; text?: string | null; confirmed?: boolean }
  | { action: 'cancel' }

export interface SharedMaterials {
  directory: string
  exists: boolean
  files: { name: string; size: number }[]
}

export interface SkillInfo {
  name: string
  description: string
  source: string
  path: string
}

export interface SkillFiles {
  skill: SkillInfo
  files: { path: string; size: number }[]
  used_by_running: string[]
}

export interface SkillText {
  path: string
  offset: number
  content: string
  next_offset: number | null
}

const taskPath = (id: number, suffix = '') => `/api/host/tasks/${id}${suffix}`

export const tasksApi = {
  state: (signal?: AbortSignal) => http.get<TaskService>('/api/host/tasks/state', undefined, signal),
  list: (scene: string, status: TaskFilter, offset: number, signal?: AbortSignal) =>
    http.get<{ items: Task[]; next_offset: number | null }>(
      '/api/host/tasks',
      { scene, status, offset, limit: 20 },
      signal,
    ),
  detail: (scene: string, id: number, after = 0, signal?: AbortSignal) =>
    http.get<TaskDetail>(taskPath(id), { scene, after, limit: 100 }, signal),
  event: (scene: string, id: number, event: number) =>
    http.get<TaskEvent>(taskPath(id, `/events/${event}`), { scene }),
  delegate: (scene: string, body: DelegateInput) =>
    request<Task>('/api/host/tasks/delegate', { method: 'POST', query: { scene }, body }),
  action: (scene: string, id: number, body: TaskAction) =>
    request<unknown>('/api/host/tasks/action', { method: 'POST', query: { scene }, body: { ...body, id } }),
  download: (scene: string, id: number, file: number) =>
    requestBlob(taskPath(id, `/files/${file}`), { query: { scene } }),
  sessionUrl: (scene: string, id: number) => `${taskPath(id, '/session')}?${queryString({ scene })}`,
  exportUrl: (scene: string, id: number) => `${taskPath(id, '/export')}?${queryString({ scene })}`,
  liveUrl: (scene: string, id: number) => socketUrl(`${taskPath(id, '/live')}?${queryString({ scene })}`),
  closeEnvironment: (scene: string, id: number) =>
    request<unknown>(taskPath(id, '/close-environment'), { method: 'POST', query: { scene } }),

  materials: (scene: string, signal?: AbortSignal) =>
    http.get<SharedMaterials>('/api/host/materials', { scene }, signal),
  adoptMaterial: (
    scene: string,
    body: { task_id: number; file_id: number; name: string; directory: string },
  ) =>
    request<{ name: string }>('/api/host/materials/adopt', {
      method: 'POST',
      query: { scene },
      body: { ...body, confirmed: true },
    }),

  skills: (scene: string, id: number, signal?: AbortSignal) =>
    http.get<{ items: SkillInfo[] }>(taskPath(id, '/skills'), { scene }, signal),
  skillFiles: (scene: string, id: number, name: string, signal?: AbortSignal) =>
    http.get<SkillFiles>('/api/host/skills/files', { scene, source: 'task', name, task_id: id }, signal),
  skillText: (scene: string, id: number, name: string, path: string, offset: number) =>
    http.get<SkillText>('/api/host/skills/text', { scene, source: 'task', name, task_id: id, path, offset }),
  moveSkill: (scene: string, id: number, name: string, target: 'scene' | 'shared') =>
    request<unknown>('/api/host/skills/move', {
      method: 'POST',
      query: { scene },
      body: { source: 'task', name, task_id: id, target },
    }),
}
