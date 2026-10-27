import { http } from './client'

/** Types of GET /api/host/overview (panel/app.py read_overview) and the host controls the overview uses. */

export interface TurnRecord {
  id: string
  scene: string
  started: number
  status: string
  model_error?: boolean
  error?: string | null
}

export interface Activity {
  kind: 'turn' | 'task' | 'send'
  scene: string
  at: number
  id: string | number
  status: string
  /** Task goal, for `task`. */
  goal?: string
  /** Whether the turn sent anything, for `turn`. */
  spoke?: boolean
}

export interface Overview {
  timezone: string
  sampled_at: number
  /** Start and end of today in the host time zone. */
  since: number
  until: number
  messages: { received?: number; sent?: number; simulated?: number; [status: string]: number | undefined }
  turns: Record<string, number>
  model_calls: number
  tokens: { input: number; output: number; cached: number }
  pending_schedules: number
  recent_errors: TurnRecord[]
  model_errors: { id: number; scene: string; turn_id: string | null; error: string; count: number }[]
  reply_effects: Record<string, number>
  /** Messages per group that failed or may not have been sent today. */
  undelivered: Record<string, number>
  pending_reviews: Record<string, { expressions?: number; stickers?: number }>
  hourly: {
    since: number
    hours: number
    received: number[]
    spoke: number[]
    turns: number[]
    tokens: number[]
  }
  activity: Activity[]
  failed_tasks: Record<string, number>
  memory_stuck: {
    scene: string
    status: 'failed' | 'interrupted'
    error: string | null
    ended: number | null
  }[]
  /** Groups at the hourly speaking limit, with the time it lifts. */
  speech_held: Record<string, number>
  memory_index: { needs_rebuild: boolean; reason: string | null } | null
}

/** GET /api/host/event-loop (panel/routes/diagnostics.py). */
export interface EventLoop {
  running: boolean
  started_at: number | null
  interval_ms: number
  threshold_ms: number
  probes: number
  stalls: number
  stalled_ms_total: number
  /** Gaps from the computer sleeping; not counted as stalls. */
  pauses: number
  max_lag_ms: number
  recent: { at: number; lag_ms: number; task: string | null; stack: string | null }[]
}

export const overviewApi = {
  overview: (signal?: AbortSignal) => http.get<Overview>('/api/host/overview', undefined, signal),
  eventLoop: (signal?: AbortSignal) => http.get<EventLoop>('/api/host/event-loop', undefined, signal),
  connect: () => http.post<{ status: string }>('/api/host/connection/connect'),
  disconnect: () => http.post<{ status: string }>('/api/host/connection/disconnect'),
  /** Pauses or resumes every group; messages are still stored while paused. */
  setAllChat: (enabled: boolean) =>
    http.put<{ enabled: boolean; scenes: number }>('/api/host/control/chat', { enabled }),
  /** While held, turns run and sends are recorded as simulated; nothing reaches the platform. */
  setSendHold: (enabled: boolean) =>
    http.put<{ enabled: boolean }>('/api/host/control/send-hold', { enabled }),
}
