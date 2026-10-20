import { http } from './client'

export interface ItemHealth {
  name: string
  status: string
  error: string | null
  error_count: number
  latest_error: unknown
}

/** Whether the Bot speaks here unprompted now; `changes_at` is when that changes without an event (Unix seconds). */
export interface ChatStatus {
  status: 'chatting' | 'paused' | 'quiet' | 'limited'
  changes_at: number | null
}

export interface HostScene {
  scene: string
  persona: { id: string; name: string }
  persona_path: string
  voice_mode: string
  timezone: string
  chat_enabled: boolean
  chat_status: ChatStatus
}

export interface HostState {
  bot_id: string | null
  timezone: string
  delivery: string
  connection: {
    mode: 'telegram' | 'simulated' | 'forward_ws' | 'reverse_ws' | string
    connected: boolean
    status: string
    addresses: string[]
    last_error: string | null
    can_connect: boolean
    can_disconnect: boolean
    disconnect_requested: boolean
    accepting: boolean
  }
  scenes: HostScene[]
  send_hold: boolean
  memory_backend: string | null
  plugins: ItemHealth[] | null
  mcp: ItemHealth[]
}

export interface SceneTitles {
  titles: Record<string, string>
  members: Record<string, number>
  errors: Record<string, string>
}

/** GET /api/host/scenes/{scene}/control */
export interface SceneControl {
  scene: string
  timezone: string
  temporary_quiet: {
    started: number
    until: number
    direct: 'allow' | 'defer'
    requester: string | null
  } | null
  paused: boolean
  quiet_until: number | null
  direct: string
}

/** A group the Bot is in (OneBot) or has recently seen (Telegram) that is not connected yet. */
export interface AvailableScene {
  scene: string
  name: string | null
  members?: number | null
  last_seen: number | null
}

export interface PersonaSummary {
  key: string
  /** The role's folder, which a group's `persona` setting points at. */
  path: string
  id: string | null
  name?: string
  brief?: string | null
  config_path: string
  error?: unknown
  avatar?: boolean
  duplicate_id?: boolean
  scenes?: string[]
}

export const personaAvatar = (role: PersonaSummary) =>
  role.avatar
    ? `/api/host/personas/${encodeURIComponent(role.key)}/avatar/image?directory=${encodeURIComponent(role.path)}`
    : null

const scenePath = (scene: string) => `/api/host/scenes/${encodeURIComponent(scene)}`

export const hostApi = {
  state: (signal?: AbortSignal) => http.get<HostState>('/api/host/state', undefined, signal),
  sceneTitles: (signal?: AbortSignal) => http.get<SceneTitles>('/api/host/scene-titles', undefined, signal),
  setChat: (scene: string, enabled: boolean) =>
    http.put<SceneControl>(`${scenePath(scene)}/control/chat`, { enabled }),
  control: (scene: string, signal?: AbortSignal) =>
    http.get<SceneControl>(`${scenePath(scene)}/control`, undefined, signal),
  quiet: (scene: string, seconds: number, direct: 'allow' | 'defer') =>
    http.post<SceneControl>(`${scenePath(scene)}/control/quiet`, { seconds, direct }),
  resume: (scene: string) => http.post<SceneControl>(`${scenePath(scene)}/control/resume`),
  availableScenes: (signal?: AbortSignal) =>
    http.get<{ items: AvailableScene[] }>('/api/host/settings/scenes/available', undefined, signal),
  addScene: (scene: string, persona: string) =>
    http.post<unknown>('/api/host/settings/scenes', { scene, persona }),
  personas: (signal?: AbortSignal) =>
    http.get<{ roles: PersonaSummary[] }>('/api/host/personas', undefined, signal),
}
