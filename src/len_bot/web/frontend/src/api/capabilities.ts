import { http, request } from './client'
import type { ReadService, SearchService } from './webServices'
import type { SettingsSnapshot } from './settings'

/** Types of panel/routes/mcp.py, browser.py, skills.py and the capability parts of settings.py. */

/** A saved MCP service; env and header values come back as null, only their names are shown. */
export interface McpService {
  enabled: boolean
  scenes: string[]
  timeout_seconds: number
  max_response_bytes: number
  transport:
    | { type: 'stdio'; command: string; args: string[]; cwd: string; env: Record<string, string | null> }
    | { type: 'http'; url: string; headers: Record<string, string | null> }
}

/** `tools/mcp_host.py` state_one(). */
export interface McpConnection {
  name: string
  status: 'disabled' | 'connecting' | 'running' | 'failed' | 'stopped' | string
  error: string | null
  scenes: string[]
  protocol: string | null
  server: Record<string, unknown> | null
  transport: 'stdio' | 'http'
  tools: { name: string; description: string; parameters: Record<string, unknown> }[]
  /** Newest first. */
  errors: { at: number; error: string }[]
}

export interface McpState {
  saved: Record<string, McpService>
  /** Groups in the saved configuration. */
  scenes: string[]
  restart_required: boolean
  running: McpConnection[]
  /** Set by connect and disconnect. */
  result?: { status: string; error?: string | null } | null
}

export interface WebRead {
  provider: ReadService
  connection: string | null
  timeout_seconds: number | null
}
export interface WebSearch {
  provider: SearchService
  connection: string | null
  timeout_seconds: number | null
  max_results: number | null
}
export interface Network {
  fake_ip_networks: string[]
  public_dns_url: string
}

export type EgressMode = 'off' | 'allowlist' | 'public'
/** The package-registry preset the task settings offer for allowlist mode. */
export const PACKAGE_HOSTS = ['pypi.org', 'files.pythonhosted.org', 'registry.npmjs.org']
export interface Egress {
  mode: EgressMode
  allowed_hosts: string[]
  max_task_upload_bytes: number | null
  max_task_bytes: number | null
  max_scene_daily_bytes: number | null
  max_connections: number | null
  bytes_per_second: number | null
  connect_timeout_seconds: number | null
  header_timeout_seconds: number | null
}
export type StoragePool = { kind: 'ext4'; mount: string; image?: string } | { kind: 'apfs'; mount: string }

/** What the host detects for a first task setup: Docker, its own account and directories in the instance. */
export type WorkerDefaults = Partial<
  Pick<
    Worker,
    | 'docker_binary'
    | 'docker_host'
    | 'image'
    | 'workspace_root'
    | 'runtime_root'
    | 'delivery_root'
    | 'uid'
    | 'gid'
  >
>

/** `configuration/tasks.py` WorkerSettings; number fields are null while their input is empty. */
export interface Worker {
  sandbox?: 'docker' | 'bwrap'
  docker_binary: string
  docker_host: string
  image: string
  bwrap_binary?: string | null
  task_runtime?: string | null
  workspace_root: string
  runtime_root: string
  delivery_root: string
  storage_pool: StoragePool | null
  skills_directory: string | null
  uid: number | null
  gid: number | null
  cpus: number | null
  memory: string
  tmpfs_size: string
  pids_limit: number | null
  command_timeout_seconds: number | null
  max_running: number | null
  max_containers: number | null
  max_scene_containers: number | null
  max_calls: number | null
  max_request_bytes: number | null
  max_response_bytes: number | null
  max_tokens: number | null
  compaction_reserve_tokens: number | null
  compaction_keep_recent_tokens: number | null
  active_timeout_seconds: number | null
  input_timeout_seconds: number | null
  max_file_bytes: number | null
  max_delivery_bytes: number | null
  max_workspace_bytes: number | null
  disk_reserve_bytes: number | null
  disk_stop_bytes: number | null
  workspace_retention_days: number | null
  storage_check_seconds: number | null
  input_support: 'text' | 'text-image'
  model_reasoning: boolean | null
  egress: Egress
  mcp: boolean
}

/** The capability sections of GET /api/host/settings. */
export interface CapabilitySettings {
  web_read: WebRead | null
  web_search: WebSearch | null
  network: Network
  worker: Worker | null
}
export const capabilitiesOf = (snapshot: SettingsSnapshot) => snapshot.saved as unknown as CapabilitySettings

export type SkillSource = 'builtin' | 'shared' | 'scene' | 'task' | 'plugin'
export interface SkillInfo {
  name: string
  description: string
  source: SkillSource
  path: string
  model_invocation: boolean
}
/** GET /api/host/skills: the skills a group could use and what the group's role allows. */
export interface SkillsState {
  scene: string
  directory: string | null
  running_directory: string | null
  role_skills: {
    directory: string
    persona: { id: string; name: string }
    saved: 'all' | string[]
    running: 'all' | string[]
    restart_required: boolean
    affected_scenes: string[]
  }
  catalog: (SkillInfo & { selected: boolean })[]
  running: SkillInfo[]
}
export interface SkillFiles {
  skill: SkillInfo
  files: { path: string; size: number }[]
  used_by_running: string[]
  referenced_by_saved?: string[]
}
export interface SkillText {
  path: string
  offset: number
  content: string
  next_offset: number | null
}
/** Which skill: a task's own skills also need the task. */
export interface SkillPlace {
  scene: string
  source: SkillSource
  name: string
  taskId?: number | null
}
const where = (place: SkillPlace) => ({
  scene: place.scene,
  source: place.source,
  name: place.name,
  task_id: place.source === 'task' ? (place.taskId ?? undefined) : undefined,
})

const named = (value: string) => encodeURIComponent(value)

export const capabilitiesApi = {
  mcp: (signal?: AbortSignal) => http.get<McpState>('/api/host/mcp', undefined, signal),
  saveMcp: (name: string, settings: McpService) =>
    http.put<McpState>(`/api/host/mcp/${named(name)}`, { settings }),
  removeMcp: (name: string) => request<McpState>(`/api/host/mcp/${named(name)}`, { method: 'DELETE' }),
  connectMcp: (name: string) => http.post<McpState>(`/api/host/mcp/${named(name)}/connect`),
  disconnectMcp: (name: string) => http.post<McpState>(`/api/host/mcp/${named(name)}/disconnect`),

  saveWebRead: (value: WebRead | null) =>
    http.put<SettingsSnapshot>('/api/host/settings/web-read', { web_read: value }),
  saveWebSearch: (value: WebSearch | null) =>
    http.put<SettingsSnapshot>('/api/host/settings/web-search', { web_search: value }),
  saveNetwork: (value: Network) =>
    http.put<SettingsSnapshot>('/api/host/settings/network', { network: value }),
  saveWorker: (value: Worker | null) =>
    http.put<SettingsSnapshot>('/api/host/settings/worker', { worker: value }),
  workerDefaults: (signal?: AbortSignal) =>
    http.get<WorkerDefaults>('/api/host/settings/worker/defaults', undefined, signal),

  skills: (scene: string, signal?: AbortSignal) =>
    http.get<SkillsState>('/api/host/skills', { scene }, signal),
  skillFiles: (place: SkillPlace, signal?: AbortSignal) =>
    http.get<SkillFiles>('/api/host/skills/files', where(place), signal),
  skillText: (place: SkillPlace, path: string, offset: number) =>
    http.get<SkillText>('/api/host/skills/text', { ...where(place), path, offset }),
  moveSkill: (place: SkillPlace, target: 'scene' | 'shared') =>
    request<unknown>('/api/host/skills/move', {
      method: 'POST',
      query: { scene: place.scene },
      body: {
        source: place.source,
        name: place.name,
        task_id: place.source === 'task' ? place.taskId : null,
        target,
      },
    }),
  removeSkill: (place: SkillPlace) =>
    request<unknown>(`/api/host/skills/${named(place.source)}/${named(place.name)}`, {
      method: 'DELETE',
      query: { scene: place.scene },
    }),
}
