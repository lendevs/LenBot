import { http } from './client'
import type { PersonaExample, PersonaFiles, PersonaProfile } from './personas'
import type { TurnDetail } from './timeline'

/** Types of panel/routes/trials.py (host trials) and trials/panel.py (the isolated chat test). */

export interface ChatSegment {
  type: 'text' | 'mention' | 'image' | 'reply' | string
  data: Record<string, unknown>
}
/** `platform/messages.py` ChatMessage with the stored sequence number and cached images. */
export interface ChatMessage {
  seq: number
  platform_message_id: string | null
  sender: { uid: string; nickname: string | null; card: string | null; role: string | null }
  time: number
  segments: ChatSegment[]
  reply_to: string | null
  is_self: boolean
  send_status: string
  recalled?: boolean
  images: { image_index: number; description?: string | null }[]
}
export interface ChatTurn {
  id: string
  started: number
  ended: number | null
  status: string
  error: string | null
  [field: string]: unknown
}
export interface ChatState {
  scene: string
  timezone: string
  bot_id: string
  persona?: { id: string; name: string }
  models: Record<string, string>
  running: boolean
  error: string | null
  messages: ChatMessage[]
  /** Newest first, at most 20. */
  turns: ChatTurn[]
}
export interface ChatSend {
  uid: string
  nickname: string
  role: 'member' | 'admin' | 'owner'
  text: string
  mentions: string[]
  reply_to: string | null
}
export interface MessageReceipt {
  status: 'queued' | 'stored' | 'duplicate' | string
  message_seq: number
  error?: string | null
  reason?: string | null
}

/** One chat to talk to: a host trial or the isolated chat test. */
export interface ChatSource {
  /** Query key prefix and cache identity. */
  id: string
  base: string
}
export const trialSource = (id: string): ChatSource => ({
  id: `trial:${id}`,
  base: `/api/host/trials/${encodeURIComponent(id)}`,
})
export const isolatedSource: ChatSource = { id: 'isolated', base: '/api/chat-test' }

export const chatApi = {
  state: (source: ChatSource, signal?: AbortSignal) =>
    http.get<ChatState>(`${source.base}/state`, undefined, signal),
  send: (source: ChatSource, body: ChatSend) => http.post<MessageReceipt>(`${source.base}/messages`, body),
  steps: (source: ChatSource, turn: string, signal?: AbortSignal) =>
    http.get<TurnDetail>(`${source.base}/turns/${encodeURIComponent(turn)}/steps`, undefined, signal),
  avatar: (source: ChatSource) => `${source.base}/avatar`,
  image: (source: ChatSource, seq: number, index: number) => `${source.base}/messages/${seq}/images/${index}`,
  events: (source: ChatSource) =>
    `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${source.base}/events`,
}

/** `TrialInfo` */
export interface TrialInfo {
  id: string
  scene: string
  created: number
  stopped: number | null
  /** Group messages copied in at the start, rendered as text. */
  context: string[]
  active: boolean
  root: string
  excluded_tools: string[]
  memory: string
  /** The plugin that keeps the group's long-term memory; the trial runs on its own native memory. */
  memory_plugin: string | null
  persona: string
  persona_source: 'running' | 'draft' | string
  draft_path: string | null
  /** The role library directory of a draft trial. */
  draft_source: string | null
  models: Record<string, string>
}

export const trialsApi = {
  list: (signal?: AbortSignal) => http.get<{ items: TrialInfo[] }>('/api/host/trials', undefined, signal),
  /** Model requests still cost; platform sending is always simulated. */
  start: (scene: string, context: number, draft?: { directory: string; files: PersonaFiles }) =>
    http.post<TrialInfo>('/api/host/trials', {
      scene,
      acknowledge_model_cost: true,
      context_messages: context,
      ...(draft ? { persona_draft: draft } : {}),
    }),
  stop: (id: string) => http.post<TrialInfo>(`/api/host/trials/${encodeURIComponent(id)}/stop`),
}

/** `ScenePersona` of configuration/chat.py: what the isolated test scene adds to its role. */
export interface ScenePersonaValues {
  persona_aliases: string[]
  relationships: Record<string, string>
  behavior_addendum: string | null
}
export interface ScenePersonaResult {
  saved: ScenePersonaValues
  /** The saved values differ from what the running instance loaded. */
  restart_required: boolean
}
/** The role and scene the isolated instance is running with. */
export interface IsolatedSettings {
  scene: string
  timezone: string
  bot_id: string
  voice_mode: string
  delivery: string
  scene_persona: ScenePersonaValues
  persona: PersonaProfile & { id: string; tools: 'all' | string[]; skills: 'all' | string[] }
  selected_examples: PersonaExample[]
  knowledge: { filename: string; tags: string[]; characters: number }[]
  tools: { core: string[]; deferred: string[] }
}

export const chatTestApi = {
  settings: (signal?: AbortSignal) =>
    http.get<IsolatedSettings>('/api/chat-test/settings', undefined, signal),
  scenePersona: (signal?: AbortSignal) =>
    http.get<ScenePersonaResult>('/api/chat-test/scene-persona', undefined, signal),
  saveScenePersona: (values: ScenePersonaValues) =>
    http.put<ScenePersonaResult>('/api/chat-test/scene-persona', values),
}
