import { http, request } from './client'
import type { Identities, SettingsSnapshot } from './settings'

/** Types of the system parts of panel/routes/settings.py, operations.py (retention), prompts.py and updates.py. */

export interface OneBotCommon {
  action_transport: 'websocket' | 'http'
  http_url: string | null
  request_timeout_seconds: number | null
  ping_interval_seconds: number | null
  ping_timeout_seconds: number | null
  max_frame_bytes: number | null
}
export type OneBot =
  | (OneBotCommon & { mode: 'forward_ws'; ws_url: string })
  | (OneBotCommon & { mode: 'reverse_ws'; listen_host: string; listen_port: number | null })
export type SavedOneBot = OneBot & { access_token_configured: boolean }

/** Telegram without the token; the Bot account follows from the token. */
export interface TelegramLink {
  api_url: string
  proxy: string | null
  poll_timeout_seconds: number | null
  request_timeout_seconds: number | null
}
export type SavedTelegram = TelegramLink & { bot_id: string }

/** Feishu without the App Secret; `bot_id` comes from a connection test. */
export interface FeishuLink {
  bot_id: string
  app_id: string
  domain: 'feishu' | 'lark'
  request_timeout_seconds: number | null
}

export type ChatPlatform = 'onebot' | 'telegram' | 'feishu'

export interface TextDelivery {
  max_chars: number | null
  min_interval_seconds: number | null
  max_interval_seconds: number | null
  chars_per_second: number | null
}

/** `saved.connection`; number fields are null while their input is empty. */
export interface Connection {
  bot_id: string
  owners: string[]
  /** An owner's private message opens a private chat with them. */
  owner_private_chat: boolean
  onebot: SavedOneBot | null
  telegram: SavedTelegram | null
  feishu: FeishuLink | null
  /** Edited in the config file only. */
  timezone: string
  /** Follows whether a platform is configured. */
  max_steps: number | null
  turn_timeout_seconds: number | null
  max_model_requests: number | null
  text_delivery: TextDelivery
}

export interface PanelAccount {
  host: string
  port: number | null
  username: string
  cookie_secure: boolean
}

export interface SpeechLimits {
  messages_per_hour: number | null
  direct_reserve: number | null
  speech_notice_text: string | null
}

export interface Commands {
  group_managers_chat_reset: boolean
  [field: string]: unknown
}

export interface Retention {
  request_days: number | null
  timeline_days: number | null
  message_days: Record<string, number>
}
/** Counts of records a cleanup batch removes or would remove. */
export type RetentionCounts = Partial<
  Record<
    | 'messages'
    | 'turns'
    | 'model_snapshots'
    | 'auxiliary_snapshots'
    | 'task_snapshots'
    | 'memory_snapshots'
    | 'extraction_jobs'
    | 'notices',
    number
  >
>
export interface RetentionState {
  enabled: boolean
  busy: boolean
  last_result: RetentionCounts | null
  error: string | null
  preview: RetentionCounts | null
}

export interface Processing {
  compaction: {
    input_tokens: number | null
    keep_recent_tokens: number | null
    max_output_tokens: number | null
  }
  images: {
    max_bytes: number | null
    max_pixels: number | null
    max_dimension: number | null
    timeout_seconds: number | null
  }
  audio: {
    max_bytes: number | null
    max_seconds: number | null
    timeout_seconds: number | null
    wait_seconds: number | null
  }
  logging: { directory: string; retention_days: number | null; level: 'INFO' | 'WARNING' | 'ERROR' }
}

/** The system sections of GET /api/host/settings. */
export interface SystemSettings {
  connection: Connection
  panel: PanelAccount | null
  limits: SpeechLimits
  commands: Commands
  permissions: Identities
  retention: Retention | null
  processing: Processing
}
export const systemOf = (snapshot: SettingsSnapshot) => snapshot.saved as unknown as SystemSettings

export interface PromptSummary {
  version: string
  /** The version the edits were made on; null without edits. */
  edited_version: string | null
  keep_on_update: boolean
  items: { name: string; edited: boolean }[]
}
export interface PromptDocument {
  name: string
  default: string
  text: string
  edited: boolean
  placeholders: string[]
}

/** `runtime/releases.py` ReleaseCheck.state(). */
export interface ReleaseCheck {
  enabled: boolean
  checked_at: number | null
  latest: string | null
  latest_prerelease: string | null
  update_available: boolean
  error: string | null
}
/** `runtime/updater.py` Updater.state(): what the running host is doing for an update. */
export interface UpdateOperation {
  stage: 'idle' | 'download' | 'install' | 'restart' | 'failed'
  target: string | null
  /** Bytes while downloading. */
  progress: { done: number; total: number } | null
  error: string | null
}
/** One plugin brought to its catalog version after an update; `name` `*` when the step itself failed. */
export interface PluginUpdateResult {
  name: string
  from?: string
  to?: string
  restart_required?: boolean
  error: string | null
}
/** What the launcher did with the last request (`deployment.py` Switch). */
export interface UpdateResult {
  action: 'update' | 'restore'
  status: 'complete' | 'rolled_back' | 'failed'
  from: string
  to: string
  error?: string | null
  snapshot?: string
  finished_at: number
  /** `pending` until the new host updated the plugins; null when not asked. */
  plugins?: 'pending' | PluginUpdateResult[] | null
}
/** A snapshot the launcher took before an update or a restore. */
export interface UpdateSnapshot {
  name: string
  version: string
  reason: string
  created_at: number
  bytes: number
  /** That version is still installed, so the snapshot can be restored with it. */
  restorable: boolean
}
export interface UpdateState {
  version: string
  /** How the program is installed; null for a source checkout, which updates with Git. */
  managed: 'package' | 'docker' | null
  check: ReleaseCheck
  operation: UpdateOperation
  result: UpdateResult | null
  snapshots: UpdateSnapshot[]
}
export interface Release {
  tag: string
  version: string
  prerelease: boolean
  newer: boolean
  notes: string
}

const named = (value: string) => encodeURIComponent(value)

export const systemApi = {
  /** `access_token`, `telegram_token` and `feishu_secret` null keep the saved ones. */
  saveConnection: (
    body: Omit<Connection, 'bot_id' | 'onebot' | 'telegram' | 'feishu'> & {
      onebot: OneBot | null
      access_token: string | null
      bot_id?: string
      /** An absent platform section keeps its saved value. */
      telegram?: TelegramLink | null
      telegram_token?: string | null
      feishu?: FeishuLink | null
      feishu_secret?: string | null
    },
  ) => http.put<SettingsSnapshot>('/api/host/settings/connection', body),
  /** Checks typed Telegram or Feishu settings without saving; empty secrets use the saved ones. */
  testConnection: (
    body:
      | { platform: 'telegram'; telegram: TelegramLink; telegram_token: string | null }
      | { platform: 'feishu'; feishu: FeishuLink; feishu_secret: string | null },
  ) => http.post<{ bot_id: string; name: string }>('/api/host/settings/connection/test', body),
  /** `password` null keeps the saved one. */
  savePanel: (body: PanelAccount & { password: string | null }) =>
    http.put<SettingsSnapshot>('/api/host/settings/panel', body),
  /** `version` is the snapshot's `versions.limits`; a stale one is refused with 409 and code `limits_conflict`. */
  saveSpeech: (body: SpeechLimits & { version?: string }) =>
    http.put<SettingsSnapshot>('/api/host/settings/limits', body),
  saveCommands: (groupManagers: boolean) =>
    http.put<SettingsSnapshot>('/api/host/settings/commands', { group_managers_chat_reset: groupManagers }),
  savePermissions: (permissions: Identities) =>
    http.put<SettingsSnapshot>('/api/host/settings/permissions', { permissions }),
  saveRetention: (retention: Retention | null) =>
    http.put<SettingsSnapshot>('/api/host/settings/retention', { retention }),
  saveProcessing: (processing: Processing) =>
    http.put<SettingsSnapshot>('/api/host/settings/processing', processing),

  retention: (signal?: AbortSignal) => http.get<RetentionState>('/api/host/retention', undefined, signal),
  prune: () =>
    request<RetentionCounts>('/api/host/retention', { method: 'POST', query: { confirmed: true } }),

  prompts: (signal?: AbortSignal) => http.get<PromptSummary>('/api/host/prompts', undefined, signal),
  prompt: (name: string, signal?: AbortSignal) =>
    http.get<PromptDocument>(`/api/host/prompts/${named(name)}`, undefined, signal),
  savePrompt: (name: string, text: string) =>
    http.put<PromptSummary>(`/api/host/prompts/${named(name)}`, { text }),
  resetPrompt: (name: string) =>
    request<PromptSummary>(`/api/host/prompts/${named(name)}`, { method: 'DELETE' }),
  keepPrompts: (keep: boolean) =>
    http.put<PromptSummary>('/api/host/prompt-settings', { keep_on_update: keep }),

  updates: (signal?: AbortSignal) => http.get<UpdateState>('/api/host/updates', undefined, signal),
  releases: (signal?: AbortSignal) => http.get<Release[]>('/api/host/updates/releases', undefined, signal),
  /** Downloads and installs the release, then the host restarts into it; `plugins` updates them afterwards. */
  startUpdate: (tag: string, plugins: boolean) =>
    http.post<UpdateState>('/api/host/updates/start', { tag, plugins }),
  restoreSnapshot: (name: string) =>
    http.post<UpdateState>(`/api/host/updates/snapshots/${named(name)}/restore`),
  deleteSnapshot: (name: string) =>
    request<UpdateState>(`/api/host/updates/snapshots/${named(name)}`, { method: 'DELETE' }),
}
