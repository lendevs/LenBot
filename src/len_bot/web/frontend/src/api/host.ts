import { http } from './client'

export interface ItemHealth {
  name: string
  status: string
  error: string | null
  error_count: number
  latest_error: unknown
}

export interface HostScene {
  scene: string
  persona: { id: string; name: string }
  persona_path: string
  voice_mode: string
  timezone: string
  chat_enabled: boolean
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

export const hostApi = {
  state: (signal?: AbortSignal) => http.get<HostState>('/api/host/state', undefined, signal),
  sceneTitles: (signal?: AbortSignal) => http.get<SceneTitles>('/api/host/scene-titles', undefined, signal),
}
