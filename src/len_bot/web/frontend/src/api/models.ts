import { http } from './client'
import type { SettingsSnapshot } from './settings'

/** Types of the model helpers in panel/routes/settings.py. */

/** One saved provider as GET /api/host/settings shows it; the key itself is never sent back. */
export interface SavedProvider {
  api: string
  base_url: string
  api_key_configured: boolean
  proxy: string | null
}

/** `models/providers.py` PROTOCOLS: what each native API can be used for. */
export interface Protocol {
  api: string
  title: string
  /** Address filled in when the protocol is chosen; empty for services with their own address. */
  base_url: string
  roles: string[]
  description: string
}

export interface EmbeddingBinding {
  provider: string
  model: string
  dimensions: number | null
}

/** `configuration/models.py` Binding; number fields are null while their input is empty. */
export interface ChatBinding {
  provider: string
  model: string
  context_window_tokens: number | null
  temperature: number | null
  max_output_tokens: number | null
  timeout_seconds: number | null
  reasoning_effort: string | null
  thinking_budget_tokens: number | null
  output_token_field: 'max_completion_tokens' | 'max_tokens'
  history_policy: 'native' | 'omit-reasoning'
  retry_delays_seconds: number[]
}

export interface AsrBinding {
  api: 'openai-audio'
  provider: string
  model: string
  timeout_seconds: number | null
  language: string | null
}

export type ChatRole = 'mind' | 'vision' | 'memory' | 'learner' | 'worker'
export type ModelRoles = { mind: ChatBinding } & Record<Exclude<ChatRole, 'mind'>, ChatBinding | null> & {
    asr: AsrBinding | null
  }

/** A provider as the list and probe helpers take it; a null key means the key saved under `alias`. */
export interface Candidate {
  alias: string | null
  provider: { api: string; base_url: string; api_key: string | null; proxy: string | null }
}

export interface ListedModel {
  id: string
  name: string
}

export interface ProbeResult {
  model?: string
  kind: 'text' | 'tools' | 'embedding'
  text: string
  usage?: unknown
}

/** PUT /api/host/settings/models */
export interface ModelsChange {
  providers: Record<
    string,
    {
      previous_alias: string | null
      api: string
      base_url: string
      api_key: string | null
      proxy: string | null
    }
  >
  roles: ModelRoles
  memory_embedding?: EmbeddingBinding | null
  learning_embeddings: Record<string, EmbeddingBinding | null>
}

export interface UsageRow {
  input: number
  output: number
  cached: number
  calls: number
  known_calls: number
  unknown_calls: number
}

/** GET /api/host/usage */
export interface Usage extends UsageRow {
  timezone: string
  period: 'day' | 'month'
  groups: (UsageRow & { scene: string; role: string })[]
  wakes: (UsageRow & {
    scene: string
    day: string
    channel: string
    wakes: number
    spoken: number
    speech_rate: number
  })[]
}

export const trimUrl = (value: string | null | undefined) => (value ?? '').replace(/\/+$/, '')

/** A saved provider as a request candidate: the host fills in its stored key by alias. */
export const savedCandidate = (alias: string, provider: SavedProvider): Candidate => ({
  alias,
  provider: {
    api: provider.api,
    base_url: trimUrl(provider.base_url),
    api_key: null,
    proxy: provider.proxy || null,
  },
})

export const modelsApi = {
  protocols: (signal?: AbortSignal) =>
    http.get<{ protocols: Protocol[] }>('/api/host/models/protocols', undefined, signal),
  list: (candidate: Candidate) => http.post<{ models: ListedModel[] }>('/api/host/models/list', candidate),
  probe: (
    candidate: Candidate,
    binding: ChatBinding | EmbeddingBinding,
    kind: 'text' | 'tools' | 'embedding',
  ) => http.post<ProbeResult>('/api/host/models/probe', { ...candidate, binding, kind }),
  save: (change: ModelsChange) => http.put<SettingsSnapshot>('/api/host/settings/models', change),
  usage: (period: 'day' | 'month', signal?: AbortSignal) =>
    http.get<Usage>('/api/host/usage', { period }, signal),
  /** `version` is the snapshot's `versions.limits`; a stale one is refused with 409 and the latest snapshot. */
  saveLimits: (change: {
    daily_tokens: number | null
    scene_daily_tokens: Record<string, number>
    version?: string
  }) => http.put<SettingsSnapshot>('/api/host/settings/limits', change),
}
