import { request } from './client'
import type { ListedModel, Protocol } from './models'

/** Types of the first-run wizard in panel/setup.py; every request carries the token printed at startup. */

const TOKEN_KEY = 'lenbot-setup-token'
let memoryToken: string | null = null

/**
 * The startup link is `/#token=…`; the hash router may already have rewritten it to `#/token=…`. The token
 * is moved into this tab's session storage and the address becomes `#/setup` before the first navigation,
 * so the token is neither routed nor left in the history.
 */
export function captureSetupToken(): void {
  const match = /^#\/?token=([^&]+)/.exec(location.hash)
  if (!match) return
  try {
    sessionStorage.setItem(TOKEN_KEY, decodeURIComponent(match[1]))
  } catch {
    // Storage refused: the token lives in memory for this page only.
    memoryToken = decodeURIComponent(match[1])
  }
  history.replaceState(null, '', `${location.pathname}#/setup`)
}

export function setupToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? memoryToken
  } catch {
    return memoryToken
  }
}

export function forgetSetupToken(): void {
  memoryToken = null
  try {
    sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // Nothing stored.
  }
}

export type OneBotLink =
  | { mode: 'forward_ws'; ws_url: string; access_token: string; request_timeout_seconds: number }
  | {
      mode: 'reverse_ws'
      listen_host: string
      listen_port: number
      access_token: string
      request_timeout_seconds: number
    }

export interface SetupProvider {
  api: string
  base_url: string
  api_key: string
  proxy: string | null
}

/** `configuration/models.py` Binding as the wizard sends it; the rest keeps the host defaults. */
export interface SetupBinding {
  provider: 'primary'
  model: string
  context_window_tokens: number
  max_output_tokens: number
  temperature: number | null
  reasoning_effort: string | null
  thinking_budget_tokens: number | null
  output_token_field: 'max_completion_tokens' | 'max_tokens'
}

export interface SetupEmbedding {
  provider: 'primary' | 'vectors'
  model: string
  dimensions: number | null
}

/** One official plugin offered by GET /api/setup/plugins. */
export interface SetupPlugin {
  name: string
  title: string
  description: string
  version: string
  repository: string
  capabilities: string[]
  installed: boolean
  prepared: boolean
  /** The error of the last failed installation. */
  error: string | null
}

/** POST /api/setup, `FirstSetup` in panel/setup.py. */
export interface FirstSetup {
  bot_id: string
  owners: string[]
  timezone: string
  delivery: 'simulated' | 'onebot'
  onebot: OneBotLink
  provider: SetupProvider
  mind: SetupBinding
  embedding: { provider: SetupProvider | null; model: string; dimensions: number | null } | null
  voice_mode: 'direct'
  compaction: { input_tokens: number }
  scene: string
  persona_id: string
  persona_name?: string
  brief?: string
  voice_text?: string
  boundaries?: string
  panel_port: number
  username: string
  password: string
  password_confirmation: string
  install_plugins: string[]
}

export interface SetupSaved {
  saved: boolean
  panel_url: string
  panel_port: number
  delivery: string
  plugins: { name: string; installed: boolean; version: string }[]
}

export interface ProbeAnswer {
  model: string
  text: string
  kind: string
  dimensions?: number | null
}

/** A model from the provider's list; some providers also report the context window. */
export type SetupModel = ListedModel & { context_window_tokens?: number | null }

function call<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: body === undefined ? 'GET' : 'POST',
    body,
    headers: { 'X-Setup-Token': setupToken() ?? '' },
  })
}

export const setupApi = {
  protocols: () =>
    call<{ protocols: Protocol[]; container: boolean; panel_port: number | null }>('/api/setup/protocols'),
  platform: (onebot: OneBotLink) => call<{ bot_id: string }>('/api/setup/platform', { onebot }),
  models: (provider: SetupProvider) => call<{ models: SetupModel[] }>('/api/setup/models', { provider }),
  model: (provider: SetupProvider, mind: SetupBinding, kind: 'text' | 'tools') =>
    call<ProbeAnswer>('/api/setup/model', { provider, mind, kind }),
  embedding: (provider: SetupProvider, binding: SetupEmbedding) =>
    call<ProbeAnswer>('/api/setup/embedding', { provider, binding }),
  plugins: () => call<{ plugins: SetupPlugin[] }>('/api/setup/plugins'),
  save: (body: FirstSetup) => call<SetupSaved>('/api/setup', body),
}
