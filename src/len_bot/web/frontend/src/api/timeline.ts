import { http } from './client'

/** Types of panel/routes/timeline.py; field names follow the response models there. */
export interface Verdict {
  woke: boolean
  channel: 'direct' | 'named' | 'attention' | 'focus' | 'ambient' | 'explore' | null
  reason: string
  score: number | null
  threshold: number | null
}

export interface Sender {
  uid: string
  nickname: string | null
  card: string | null
  role: string | null
}

export interface TimelineMessage {
  type: 'message'
  at: number
  message_seq: number
  platform_message_id: string | null
  sender: Sender
  time: number
  text: string
  images: { index: number; url: string | null; summary: string | null }[]
  reply_to: string | null
  reply: { platform_message_id: string; sender: Sender; text: string } | null
  is_self: boolean
  status: string
  recalled: boolean
  verdict: Verdict | null
}

export interface Tokens {
  input: number
  output: number
  cached: number
  known_calls: number
  unknown_calls: number
}

export interface TimelineTurn {
  type: 'turn'
  at: number
  turn_id: string
  status: string
  channel: string
  started: number
  ended: number | null
  steps: number
  expressions: number
  tokens: Tokens
  tools: string[]
  error: string | null
}

export type TimelineItem = TimelineMessage | TimelineTurn

export interface TimelinePage {
  scene: string
  items: TimelineItem[]
  next_before: string | null
}

export interface ToolDetail {
  call_id: string
  name: string
  arguments: Record<string, unknown>
  result: string | null
  status: 'pending' | 'complete' | 'error' | 'interrupted'
  messages: TimelineMessage[]
}

export interface ModelStep {
  id: number
  role: string
  started: number
  ended: number | null
  error: string | null
  tokens: { input: number; output: number; cached: number | null } | null
  snapshot_expired_at: number | null
}

export interface Step {
  step: number
  models: ModelStep[]
  text: string
  thoughts: string[]
  tools: ToolDetail[]
}

export interface RecallItem {
  scope: string
  path: string
  content: string
  kind: string
  truncated: boolean
}

export interface TurnDetail {
  turn: {
    id: string
    scene: string
    started: number
    ended: number | null
    status: string
    error: string | null
    wake_channel: string
  }
  recall: RecallItem[] | null
  steps: Step[]
}

const scenePath = (scene: string) => `/api/host/scenes/${encodeURIComponent(scene)}`

export const timelineApi = {
  page: (scene: string, before?: string, signal?: AbortSignal) =>
    http.get<TimelinePage>(`${scenePath(scene)}/timeline`, { before, limit: 50 }, signal),
  turn: (scene: string, turnId: string, signal?: AbortSignal) =>
    http.get<TurnDetail>(`${scenePath(scene)}/turns/${encodeURIComponent(turnId)}`, undefined, signal),
}

export const itemKey = (item: TimelineItem) =>
  item.type === 'message' ? `m${item.message_seq}` : `t${item.turn_id}`

/** Server order: time, then messages before turns, then sequence or id. */
export function compareItems(a: TimelineItem, b: TimelineItem): number {
  if (a.at !== b.at) return a.at - b.at
  if (a.type !== b.type) return a.type === 'message' ? -1 : 1
  if (a.type === 'message' && b.type === 'message') return a.message_seq - b.message_seq
  const [left, right] = [(a as TimelineTurn).turn_id, (b as TimelineTurn).turn_id]
  return left < right ? -1 : left > right ? 1 : 0
}

export const failedTurn = (status: string) =>
  ['error', 'timeout', 'interrupted', 'step_limit'].includes(status)
export const failedMessage = (status: string) => status === 'failed' || status === 'unconfirmed'
