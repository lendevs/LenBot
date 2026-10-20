import { http, request } from './client'

/** Types of panel/routes/learning.py, jargon.py, stickers.py and reply_effects.py. */

export type Review = 'pending' | 'adopted' | 'rejected'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/** `configuration/learning.py` LearningSettings. */
export interface LearningSettings {
  extract: boolean
  jargon_extract: boolean
  collect_stickers: boolean
  reply_effects: boolean
  min_messages: number | null
  batch_size: number | null
  idle_seconds: number | null
  max_age_seconds: number | null
  auto_adopt: boolean
  embedding: unknown
}

export interface LearningConfig {
  scene: string
  running: LearningSettings | null
  saved: LearningSettings | null
  restart_required: boolean
}

export interface LearningState {
  scene: string
  enabled: boolean
  index: { needs_rebuild?: boolean; rebuilding?: boolean; [field: string]: unknown } | null
  selection_enabled: boolean
  expression_counts: Record<Review, number>
  latest: { status: string; ended: number | null; error: string | null } | null
  service_state: unknown
}

export interface Expression {
  id: number
  situation: string
  style: string
  status: Review
  updated: number
  indexed: boolean
  count: number
}

export interface JargonTerm {
  id: number
  term: string
  count: number
  latest_meaning: string | null
  confidence: number | null
  meaning: string | null
  status: Review
}

export interface Sticker {
  id: number
  description: string | null
  text: string | null
  emotions: string[]
  tags: string[]
  review: Review
  status: 'queued' | 'running' | 'complete' | 'failed' | 'interrupted'
  error?: string | null
  meta: {
    mime_type: string
    width: number | null
    height: number | null
    animated: boolean
    bytes: number
  } | null
}

export type Reaction = 'agree' | 'continue' | 'correct' | 'negative' | 'unrelated' | 'uncertain'
export type EffectState = Reaction | 'observing' | 'no_messages' | 'waiting' | 'failed'

export interface ReplyEffectsState {
  enabled: boolean
  days: number
  distribution: { samples: number; partial: number; input_gap: number; states: Record<EffectState, number> }
}

export interface ReplyEffect {
  id: number
  turn_id: string | null
  channels: string[]
  first_sent_at: number
  state: EffectState
  reason: string | null
  partial: boolean
}

export interface RenderedMessage {
  record: number
  rendered: string | null
}

export interface ReplyEffectDetail extends ReplyEffect {
  expression: RenderedMessage[]
  before: RenderedMessage[]
  followups: RenderedMessage[]
}

const base = (scene: string) => `/api/host/scenes/${encodeURIComponent(scene)}`
const learningBase = (scene: string) => `${base(scene)}/learning`

export const learningApi = {
  config: (scene: string, signal?: AbortSignal) =>
    http.get<LearningConfig>(
      `/api/host/settings/scenes/${encodeURIComponent(scene)}/learning`,
      undefined,
      signal,
    ),
  putConfig: (scene: string, learning: LearningSettings | null) =>
    http.put<LearningConfig>(`/api/host/settings/scenes/${encodeURIComponent(scene)}/learning`, { learning }),
  state: (scene: string, signal?: AbortSignal) =>
    http.get<LearningState>(learningBase(scene), undefined, signal),
  learnNow: (scene: string) => http.post<unknown>(`${learningBase(scene)}/request`),
  reindex: (scene: string) => http.post<{ expressions: number }>(`${learningBase(scene)}/reindex`),

  expressions: (scene: string, status: Review, offset: number, signal?: AbortSignal) =>
    http.get<Page<Expression>>(`${learningBase(scene)}/expressions`, { status, offset, limit: 20 }, signal),
  putExpression: (scene: string, id: number, body: { situation: string; style: string; status: Review }) =>
    http.put<Expression>(`${learningBase(scene)}/expressions/${id}`, body),

  jargon: (scene: string, status: Review, offset: number, signal?: AbortSignal) =>
    http.get<Page<JargonTerm>>(`${learningBase(scene)}/jargon/terms`, { status, offset, limit: 20 }, signal),
  putJargon: (scene: string, id: number, body: { meaning: string | null; status: Review }) =>
    http.put<JargonTerm>(`${learningBase(scene)}/jargon/terms/${id}`, body),

  stickers: (scene: string, review: Review, offset: number, signal?: AbortSignal) =>
    http.get<Page<Sticker>>(
      `${learningBase(scene)}/stickers/candidates`,
      // Pending review only lists stickers whose description is finished.
      { review, offset, limit: 20, status: review === 'pending' ? 'complete' : undefined },
      signal,
    ),
  stickerImage: (scene: string, id: number) => `${learningBase(scene)}/stickers/candidates/${id}/image`,
  putSticker: (
    scene: string,
    id: number,
    body: {
      description: string | null
      text: string | null
      emotions: string[]
      tags: string[]
      review: Review
    },
  ) => http.put<Sticker>(`${learningBase(scene)}/stickers/candidates/${id}`, body),

  effects: (scene: string, signal?: AbortSignal) =>
    http.get<ReplyEffectsState>(`${base(scene)}/reply-effects`, { days: 7 }, signal),
  effectItems: (scene: string, state: string | undefined, offset: number, signal?: AbortSignal) =>
    http.get<Page<ReplyEffect>>(
      `${base(scene)}/reply-effects/items`,
      { state, offset, limit: 20, days: 7 },
      signal,
    ),
  effect: (scene: string, id: number, signal?: AbortSignal) =>
    http.get<ReplyEffectDetail>(`${base(scene)}/reply-effects/items/${id}`, undefined, signal),

  personaLocation: (scene: string) => http.get<{ saved_path: string }>(`${base(scene)}/persona-location`),
  addExample: (
    scene: string,
    body: { expression_id: number; context: string; line: string; tags: string[]; directory: string },
  ) => request<unknown>(`${base(scene)}/persona-examples`, { method: 'POST', body }),
}
