import { http } from './client'

/** Types of GET /api/host/logs and /api/host/log-files (panel/app.py, routes/operations.py). */

/** One line of the host's JSON log; correlation IDs and event fields sit at the top level. */
export interface LogRecord {
  /** ISO time in UTC. */
  ts: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL' | string
  /** Logger name, such as len_bot.next.runtime.network. */
  source: string
  event?: string
  message: string
  scene?: string
  turn_id?: string
  tool?: string
  tool_call_id?: string
  plugin?: string
  task_id?: string | number
  message_seq?: number
  job?: string
  error?: { type?: string; message: string; [field: string]: unknown }
  [field: string]: unknown
}

export interface LogFilter {
  level?: 'WARNING' | 'ERROR'
  source?: string
  event?: string
  scene?: string
  turn_id?: string
  plugin?: string
  task_id?: string
  limit: number
}

export interface LogPage {
  /** Newest first. */
  items: LogRecord[]
  directory: string
  limit: number
}

export interface LogFiles {
  items: { name: string; bytes: number }[]
}

export const logsApi = {
  modelCall: (id: number, signal?: AbortSignal) =>
    http.get<Record<string, unknown>>(`/api/host/model-calls/${id}`, undefined, signal),
  read: (filter: LogFilter, signal?: AbortSignal) =>
    http.get<LogPage>('/api/host/logs', { ...filter }, signal),
  files: (signal?: AbortSignal) => http.get<LogFiles>('/api/host/log-files', undefined, signal),
  /** A diagnostic archive of one log file, with account-shaped numbers masked. */
  fileUrl: (name: string) => `/api/host/log-files/${encodeURIComponent(name)}`,
}
