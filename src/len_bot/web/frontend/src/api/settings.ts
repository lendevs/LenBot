import type { PluginsSnapshot, SceneMemory } from './plugins'
import { http, request } from './client'

/** Types of panel/routes/settings.py, permissions.py and the parts of plugins.py a group's settings use. */

export interface QuietHours {
  start: string
  end: string
  direct: 'allow' | 'notice' | 'defer'
  notice_text: string | null
}

/** `configuration/chat.py` Attention; fields the form does not show are sent back as they were. */
export interface Attention {
  only_direct: boolean
  keywords: string[]
  other_bot_ids: string[]
  direct_idle_seconds: number
  direct_max_seconds: number
  named_idle_seconds: number
  named_max_seconds: number
  keyword_cooldown_seconds: number
  focus_seconds: number
  close_focus_on_silence: boolean
  focus_idle_seconds: number
  focus_max_seconds: number
  activity: number
  ambient_threshold: number
  ambient_min_interval_seconds: number
  ambient_max_interval_seconds: number
  explore_probability: number
  max_extensions: number
  quiet_hours: QuietHours | null
  [field: string]: unknown
}

export interface Proactive {
  idle_seconds: number
  start: string
  end: string
}

export interface SceneTasks {
  enabled: boolean
  max_running: number
  max_daily_tasks: number
  egress_max_task_bytes: number | null
  egress_max_daily_bytes: number | null
  egress_bytes_per_second: number | null
  [field: string]: unknown
}

export interface SceneSettings {
  persona: string
  timezone: string | null
  voice_mode: 'direct'
  attention: Attention
  schedules: { enabled: boolean; max_pending: number; autonomous: boolean; [field: string]: unknown }
  proactive: Proactive | null
  transcribe_audio: boolean
  tasks: SceneTasks
  learning: unknown
  scene_persona: {
    persona_aliases: string[]
    relationships: Record<string, string>
    behavior_addendum: string | null
  }
}

/** GET /api/host/settings; only the parts a group's settings read are typed. */
export interface SettingsSnapshot {
  saved: {
    limits: { messages_per_hour: number | null; scene_messages_per_hour: Record<string, number | null> }
    scenes: Record<string, SceneSettings>
    [section: string]: unknown
  }
  restart_required: { scenes: Record<string, boolean>; [section: string]: unknown }
  [field: string]: unknown
}

/** PUT /api/host/settings/scenes/{scene} */
export interface SceneChange {
  timezone: string | null
  voice_mode: 'direct'
  attention: Attention
  /** Number fields are null while the input is empty; saving is blocked until they are filled. */
  schedules: { enabled: boolean; max_pending: number | null; autonomous: boolean }
  proactive: Proactive | null
  transcribe_audio: boolean
  persona_aliases: string[]
  relationships: Record<string, string>
  behavior_addendum: string | null
}

export interface TaskChange {
  enabled: boolean
  max_running: number | null
  max_daily_tasks: number | null
  egress_max_task_bytes: number | null
  egress_max_daily_bytes: number | null
  egress_bytes_per_second: number | null
}

export type SpeechMode = 'global' | 'custom' | 'unlimited'
export interface SpeechChange {
  mode: SpeechMode
  value: number | null
}

/** One group's hourly speaking window from GET /api/host/limits. */
export interface SpeechState {
  source: string
  limit: number | null
  used: number
  remaining: number | null
  reserve: number
  reserve_left: number
  held_until: number | null
  blocked_until: number | null
}

export interface LimitsState {
  scenes: {
    scene: string
    blocked: boolean
    reason: string | null
    until: number | null
    speech: SpeechState
  }[]
}

export type Role = 'owner' | 'admin' | 'group_manager' | 'whitelist' | 'member'
export interface Identities {
  admins: string[]
  whitelist: string[]
  blacklist: string[]
}
export interface ScopedIdentities {
  owner: string | null
  admins: string[]
  whitelist: string[]
}
export type Ability =
  | 'delegate'
  | 'long_running'
  | 'task_manage'
  | 'own_reminder'
  | 'other_reminder'
  | 'reminder_manage'
  | 'chat_control'

export interface Permissions {
  global_identities: Identities
  scene_identities: Identities | null
  task_identities: ScopedIdentities
  schedule_identities: ScopedIdentities
  matrix: Record<Ability, Role[]>
}

export interface PermissionsSnapshot {
  saved: Permissions
  owners: string[]
  restart_required: boolean
}

export interface RoleSwitch {
  results: { scene: string; status: string; error?: string; handover?: string }[]
}

const scenePath = (scene: string) => encodeURIComponent(scene)

export const settingsApi = {
  read: (signal?: AbortSignal) => http.get<SettingsSnapshot>('/api/host/settings', undefined, signal),
  putScene: (scene: string, body: SceneChange) =>
    http.put<SettingsSnapshot>(`/api/host/settings/scenes/${scenePath(scene)}`, body),
  putTasks: (scene: string, tasks: TaskChange) =>
    http.put<SettingsSnapshot>(`/api/host/settings/scenes/${scenePath(scene)}/tasks`, { tasks }),
  putSpeech: (scene: string, body: SpeechChange) =>
    http.put<SettingsSnapshot>(`/api/host/settings/limits/scenes/${scenePath(scene)}`, body),
  removeScene: (scene: string) =>
    request<SettingsSnapshot>(`/api/host/settings/scenes/${scenePath(scene)}`, { method: 'DELETE' }),
  limits: (signal?: AbortSignal) => http.get<LimitsState>('/api/host/limits', undefined, signal),
  resetSpeech: (scene: string) => http.post<unknown>(`/api/host/scenes/${scenePath(scene)}/speech/reset`),
  permissions: (scene: string, signal?: AbortSignal) =>
    http.get<PermissionsSnapshot>('/api/host/permissions', { scene }, signal),
  putPermissions: (scene: string, body: Permissions) =>
    request<PermissionsSnapshot>('/api/host/permissions', { method: 'PUT', query: { scene }, body }),
  plugins: (signal?: AbortSignal) => http.get<PluginsSnapshot>('/api/host/plugins', undefined, signal),
  putScenePlugins: (scene: string, plugins: string[], memory: SceneMemory) =>
    http.put<PluginsSnapshot>(`/api/host/scenes/${scenePath(scene)}/plugins`, { plugins, ...memory }),
  useRole: (key: string, scenes: string[]) =>
    http.post<RoleSwitch>(`/api/host/personas/${encodeURIComponent(key)}/scenes`, { scenes }),
}
