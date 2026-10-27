import { http, request } from './client'

/** Types of panel/routes/schedules.py. */

export type ScheduleStatus = 'pending' | 'blocked' | 'delivered' | 'cancelled'
export type ScheduleFilter = 'active' | 'all' | 'delivered' | 'cancelled'

/** `chat/schedule_store.py` Schedule. */
export interface Schedule {
  id: number
  scene: string
  created: number
  due_at: number
  timezone: string
  note: string
  /** `self` or the account to remind. */
  target: string
  /** Null when the bot set it by itself. */
  requester: string | null
  status: ScheduleStatus
  delivered_at: number | null
  reason: string | null
  interval_seconds: number | null
  cron: string | null
}

export interface ScheduleService {
  timezone: string
  scenes: {
    scene: string
    timezone: string
    enabled: boolean
    tool_allowed: boolean
    [field: string]: unknown
  }[]
}

export interface ProactiveWake {
  id: number
  turn_id: string
  woke_at: number
  outcome: string | null
  assessment: 'reply_effects' | 'arrival_count' | string
  turn_ended: number | null
  [field: string]: unknown
}

/** GET /api/host/schedules/proactive */
export interface ProactivePage {
  timezone: string
  settings: { idle_seconds: number; start: string; end: string } | null
  pause: { until: number } | null
  next_at: number | null
  next_reason: string | null
  items: ProactiveWake[]
  next_offset: number | null
}

export const schedulesApi = {
  state: (signal?: AbortSignal) => http.get<ScheduleService>('/api/host/schedules/state', undefined, signal),
  list: (scene: string, status: ScheduleFilter, offset: number, signal?: AbortSignal) =>
    http.get<{ items: Schedule[]; next_offset: number | null }>(
      '/api/host/schedules',
      { scene, status, offset, limit: 20 },
      signal,
    ),
  /** `when` is an ISO time with offset, `every <n>m|h|d`, or `cron:<minute hour day month weekday>`. */
  create: (scene: string, body: { when: string; note: string; for: string }) =>
    request<Schedule>('/api/host/schedules', { method: 'POST', query: { scene }, body }),
  cancel: (scene: string, id: number) =>
    request<Schedule>(`/api/host/schedules/${id}/cancel`, { method: 'POST', query: { scene } }),
  proactive: (scene: string, offset: number, signal?: AbortSignal) =>
    http.get<ProactivePage>('/api/host/schedules/proactive', { scene, offset }, signal),
}
