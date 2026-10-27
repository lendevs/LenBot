import { http, request } from './client'

/** Types of panel/routes/plugins.py, plugins/host.py state() and plugins/catalog.py. */

export type FieldType =
  | 'string'
  | 'secret'
  | 'integer'
  | 'number'
  | 'boolean'
  | 'string_list'
  | 'scene'
  | 'scene_list'
  | 'path'
  | 'url'
  | 'object_list'

export type FieldValue = string | number | boolean | null | FieldValue[] | { [key: string]: FieldValue }

/** One `[config.<key>]` declaration as `_field_info` sends it; `fields` are an object list's sub-fields. */
export interface ConfigField {
  key: string
  type: FieldType
  description: string
  label: string | null
  placeholder: string | null
  multiline: boolean
  group: string | null
  required: boolean
  /** Never sent for secrets. */
  default: FieldValue
  options: { value: string | number; label: string }[] | null
  minimum: number | null
  maximum: number | null
  fields: ConfigField[]
}

export interface Permission {
  name: string
  title: string
}

/** Where an installed plugin's source came from (`plugins/install.py` Source). */
export interface Source {
  kind: 'git' | 'zip'
  location: string
  ref: string | null
  branch: string | null
  revision: string
  version: string
}

/** `PluginInstaller.details()`: the installed source's fields, plus the candidate and the previous one. */
export interface SourceDetails extends Partial<Source> {
  installed: Source | null
  candidate: Source | null
  previous: Source | null
  application: 'plugin' | 'host'
  requested: boolean
  error: string | null
}

/** One directory that provides a plugin; a failed read only has `directory` and `error`. */
export interface AvailableEntry {
  directory: string
  error: string | null
  managed: boolean
  source: SourceDetails | null
  version?: string
  description?: string
  authors?: string[]
  license?: string
  repository?: string | null
  homepage?: string | null
  dependencies?: string[]
  requires_lenbot?: string
  requires_python?: string
  platforms?: string[]
  reload?: 'plugin' | 'host'
  fields?: ConfigField[]
  /** null: undeclared, the plugin keeps every capability. */
  permissions?: Permission[] | null
  isolation?: 'inline' | 'process'
}

export interface Health {
  level: 'failed' | 'stopped' | 'starting' | 'degraded' | 'ok'
  errors_last_hour: number
  failing: string[]
  last_error_at: number | null
}

export interface PluginTool {
  name: string
  description: string
  summary: string
  parameters: Record<string, unknown>
  needs_source: boolean
}

export interface PluginCall {
  id: number
  scene: string
  role: string
  started: number
  ended: number | null
  usage: unknown
  tokens: unknown
  error: string | null
}

/** A loaded plugin as the plugin host reports it. */
export interface RunningPlugin {
  name: string
  status: 'running' | 'failed' | 'stopped' | string
  error: string | null
  health: Health
  directory: string
  version: string | null
  description: string | null
  isolation: 'inline' | 'process'
  permissions: Permission[] | null
  scenes: string[]
  commands: { name: string; description: string }[]
  rules: { kind: 'fullmatch' | 'regex'; pattern: string; description: string; priority?: number }[]
  notices: string[]
  tools: PluginTool[]
  instructions: string | null
  /** Entries a group may choose this plugin for as its memory or recap. */
  memory_entries: ('recall' | 'memory_tool' | 'compact')[]
  backgrounds: {
    method: string
    every_seconds: number
    last_started: number | null
    last_finished: number | null
    last_error: string | null
  }[]
  /** Newest first. */
  errors: { at: number; where: string; error: string }[]
  crons: {
    name: string
    scene: string
    expression: string
    timezone: string
    next_run: number | null
    last_started: number | null
    last_finished: number | null
    last_error: string | null
  }[]
  skills: string[]
  model_calls: PluginCall[]
}

/** A group's memory implementation and compaction recap: a plugin name, or null for the native one. */
export interface SceneMemory {
  memory_plugin: string | null
  recap_plugin: string | null
}

/** A saved value: secrets only say whether they are set, values of unknown plugins stay hidden. */
export type SavedValue = { value: FieldValue } | { configured: boolean } | { hidden: true }

/** GET /api/host/plugins and the answer of every plugin write. */
export interface PluginsSnapshot {
  running: { plugins: RunningPlugin[]; discovery_errors: string[] }
  available: Record<string, AvailableEntry[]>
  discovery_errors: string[]
  saved: {
    paths: string[]
    data_directory: string
    disabled: string[]
    plugins: Record<string, Record<string, SavedValue>>
  }
  /** Data directories of plugins no longer configured. */
  retained_data: { name: string; directory: string }[]
  /** Groups in the saved configuration, the choices of scene fields. */
  scene_choices: string[]
  /** Running groups: the plugins saved for each and the ones running now. */
  scenes: Record<
    string,
    {
      saved: string[] | null
      running: string[]
      memory_plugin: { saved: string | null; running: string | null }
      recap_plugin: { saved: string | null; running: string | null }
    }
  >
  restart_required: boolean
  /** What an install, apply or other operation returned. */
  operation?: {
    name: string
    needs_config?: boolean
    restart_required?: boolean
    [key: string]: unknown
  } | null
}

export interface PluginHealth {
  plugins: { name: string; status: string; error: string | null; version: string | null; health: Health }[]
}

export interface CatalogEntry {
  name: string
  title: string
  description: string
  authors: string[]
  license: string
  version: string
  interface: number
  requires_lenbot: string | null
  category: string
  capabilities: string[]
  usage: string[]
  install: 'git'
  repository: string
  homepage: string | null
  ref: string | null
  /** Bare permission names; absent or null when the entry does not list them. */
  permissions?: string[] | null
}

export interface CatalogView {
  source: 'builtin' | 'remote'
  url: string | null
  loaded_at: number | null
  entries: CatalogEntry[]
}

export interface MarketEntry extends CatalogEntry {
  installed: boolean
  installed_version: string | null
  update_available: boolean
  compatible: boolean
  incompatible_reason: string | null
}

export interface MarketView {
  source: 'builtin' | 'remote'
  url: string | null
  loaded_at: number | null
  categories: string[]
  total: number
  entries: MarketEntry[]
}

const name = (value: string) => encodeURIComponent(value)

export type PluginAction = 'apply' | 'cancel' | 'rollback' | 'reload'

export const pluginsApi = {
  read: (signal?: AbortSignal) => http.get<PluginsSnapshot>('/api/host/plugins', undefined, signal),
  /** name, status, error, version and health of every loaded plugin, without reading the disk. */
  health: (signal?: AbortSignal) => http.get<PluginHealth>('/api/host/plugins/health', undefined, signal),
  /** Saving parameters also enables the plugin; secrets left null keep their saved value. */
  save: (plugin: string, enabled: boolean, config: Record<string, FieldValue> = {}) =>
    http.put<PluginsSnapshot>(`/api/host/plugins/${name(plugin)}`, { enabled, config }),
  putScene: (scene: string, plugins: string[], memory: SceneMemory) =>
    http.put<PluginsSnapshot>(`/api/host/scenes/${name(scene)}/plugins`, { plugins, ...memory }),
  putPaths: (paths: string[], dataDirectory: string) =>
    http.put<PluginsSnapshot>('/api/host/plugin-paths', { paths, data_directory: dataDirectory }),
  install: (url: string, ref: string | null, switchSource: boolean) =>
    http.post<PluginsSnapshot>('/api/host/plugins/install', { url, ref, switch_source: switchSource }),
  importZip: (file: File, switchSource: boolean) => {
    const body = new FormData()
    body.append('file', file)
    body.append('switch_source', String(switchSource))
    return http.post<PluginsSnapshot>('/api/host/plugins/zip', body)
  },
  act: (plugin: string, action: PluginAction) =>
    http.post<PluginsSnapshot>(`/api/host/plugins/${name(plugin)}/${action}`),
  update: (plugin: string, ref: string | null) =>
    http.post<PluginsSnapshot>(`/api/host/plugins/${name(plugin)}/update`, { ref }),
  /** Removes the source and the saved settings; the data directory stays. */
  uninstall: (plugin: string) =>
    request<PluginsSnapshot>(`/api/host/plugins/${name(plugin)}`, { method: 'DELETE' }),
  removeData: (plugin: string) =>
    request<PluginsSnapshot>(`/api/host/plugin-data/${name(plugin)}`, { method: 'DELETE' }),
  catalog: (signal?: AbortSignal) => http.get<CatalogView>('/api/host/plugin-catalog', undefined, signal),
  /** null goes back to the catalog shipped with this version. */
  setCatalog: (url: string | null) => http.put<CatalogView>('/api/host/plugin-catalog', { url }),
  refreshCatalog: () => http.post<CatalogView>('/api/host/plugin-catalog/refresh'),
  /** The catalog marked with what is installed here; filtered on the server. */
  market: (query: string, category: string | null, signal?: AbortSignal) =>
    http.get<MarketView>('/api/host/plugin-market', { query, category }, signal),
  /** The server takes repository, version and permissions from the catalog entry. */
  installEntry: (plugin: string) =>
    http.post<PluginsSnapshot>(`/api/host/plugin-market/${name(plugin)}/install`),
}
