import { http, request } from './client'

/** One tool call as the model asked for it; `arguments` is the JSON text the model wrote. */
export interface EntryToolCall {
  id: string
  type: string
  function: { name: string; arguments: string }
}

/**
 * A message of the model's conversation as stored in `mind_entries`: what LenBot handed the model (`user`),
 * what the model answered (`assistant`), and tool results (`tool`). Provider continuation data starts with `_`.
 */
export interface EntryMessage {
  role: 'user' | 'assistant' | 'tool' | 'system' | string
  content?: unknown
  tool_calls?: EntryToolCall[] | null
  tool_call_id?: string
  [field: string]: unknown
}

export interface SessionEntry {
  seq: number
  message: EntryMessage
  created: number | null
  /** After the last compaction or new session, so the model still reads it as it is. */
  active: boolean
}

/** GET /api/host/scenes/{scene}/history */
export interface SessionPage {
  scene: string
  timezone: string
  active_only: boolean
  recap: string | null
  /** Entries up to this sequence are folded into the recap or belong to an earlier session. */
  compact_through: number
  last_message_seq: number
  entries: SessionEntry[]
  next_before: number | null
}

const historyPath = (scene: string) => `/api/host/scenes/${encodeURIComponent(scene)}/history`

export const sessionApi = {
  page: (scene: string, options: { before?: number; activeOnly: boolean }, signal?: AbortSignal) =>
    http.get<SessionPage>(
      historyPath(scene),
      { limit: 50, active_only: options.activeOnly, before: options.before },
      signal,
    ),
  compact: (scene: string) =>
    request<{ turn_id: string; compact_through: number; recap: string }>(`${historyPath(scene)}/compact`, {
      method: 'POST',
      query: { confirmed: true },
    }),
  newContext: (scene: string) =>
    request<{ compact_through: number; message: string }>(`${historyPath(scene)}/new-context`, {
      method: 'POST',
      query: { confirmed: true },
    }),
}
