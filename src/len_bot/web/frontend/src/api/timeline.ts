import { http } from './client'

/** Types of panel/routes/timeline.py; field names follow the response models there. */
export interface Verdict {
  woke: boolean
  channel: 'direct' | 'named' | 'attention' | 'focus' | 'ambient' | 'explore' | null
  reason: string
  score: number | null
  threshold: number | null
  /** Below 1 when recent reactions to ambient interjections lowered the participation score. */
  effect_factor?: number | null
  /** Terms of the participation score (`chat/attention.py` participation_parts); score = max(0, raw) × activity × effect. */
  parts?: VerdictParts | null
}

export const PART_NAMES = [
  'base',
  'question',
  'help',
  'filler',
  'no_text',
  'other_bots',
  'self_share',
  'gap',
] as const
export type VerdictParts = Record<(typeof PART_NAMES)[number] | 'raw' | 'activity', number> & {
  messages: number
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
  /** Seconds from the message that woke the turn, or from its start, to the first expression. */
  first_expression_wait: number | null
}

/** A platform notice; `raw` is the event as the platform sent it. */
export interface TimelineNotice {
  type: 'notice'
  at: number
  id: number
  kind: string
  sub_type: string | null
  time: number
  user_id: string | null
  /** The group card or nickname the account last spoke with in this group. */
  user_name: string | null
  operator_id: string | null
  operator_name: string | null
  duration: number | null
  platform_message_id: string | null
  raw: Record<string, unknown>
}

export type TimelineItem = TimelineMessage | TimelineTurn | TimelineNotice

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
  retries: number
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
  /** Zip of the turn, its model and tool calls and the log records with its ID. */
  exportUrl: (scene: string, turnId: string) =>
    `${scenePath(scene)}/turns/${encodeURIComponent(turnId)}/export`,
}

export const itemKey = (item: TimelineItem) =>
  item.type === 'message'
    ? `m${item.message_seq}`
    : item.type === 'notice'
      ? `n${item.id}`
      : `t${item.turn_id}`

const rank = { message: 0, notice: 1, turn: 2 } as const

/** Server order: time, then messages, notices, turns, then sequence or id. */
export function compareItems(a: TimelineItem, b: TimelineItem): number {
  if (a.at !== b.at) return a.at - b.at
  if (a.type !== b.type) return rank[a.type] - rank[b.type]
  if (a.type === 'message' && b.type === 'message') return a.message_seq - b.message_seq
  if (a.type === 'notice' && b.type === 'notice') return a.id - b.id
  const [left, right] = [(a as TimelineTurn).turn_id, (b as TimelineTurn).turn_id]
  return left < right ? -1 : left > right ? 1 : 0
}

export const failedTurn = (status: string) =>
  ['error', 'timeout', 'interrupted', 'step_limit', 'send_failed'].includes(status)
export const failedMessage = (status: string) => status === 'failed' || status === 'unconfirmed'
